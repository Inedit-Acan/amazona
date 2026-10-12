"""El origen del dinero con carreras reales y con lo propio de PostgreSQL (Milestone 46, ADR 0031 §6, §7 y §13).

Cada hilo tiene su propia sesión, en una base PostgreSQL efímera con el esquema de los modelos, y arrancan juntos tras
una
barrera. Lo que se afirma son invariantes, no tiempos: sea cual sea el orden en que se intercalen,

- el mismo id de evento en **dos orígenes** son dos eventos y se aplican los dos;
- el mismo evento en el **mismo origen**, entregado muchas veces a la vez, se guarda y se aplica **una** vez;
- dos cobros con la **misma referencia** de proveedores de **distinto origen** reciben cada uno su evento y solo el
  suyo.

La migración y la RLS de verdad están en `test_money_provenance_migration_postgres.py`.
"""

from decimal import Decimal

from order_test_support import add_product
from payment_test_support import (
    MockPaymentProvider,
    RealPaymentProvider,
    SandboxPaymentProvider,
    add_order,
    ingress,
    run_together,
    start_attempt,
)
from pg_test_support import ephemeral_postgres
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models.payment import Payment, PaymentEvent
from app.db.models.revenue import RevenueLedgerEntry
from app.money.money import Money
from app.payments.port import PaymentEventType

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED


def delivery(provider, payment_id: str | None, ref: str | None, event_id: str):
    """Un evento firmado por `provider`, entregado por la puerta desde una sesión propia."""
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=ref,
        client_reference=payment_id,
        amount=Money.of("50.00", "EUR"),
        event_id=event_id,
    )

    def job(session: Session):
        return ingress(session, provider).receive(provider.name, headers, raw)

    return job


def open_payment(engine, provider, name: str, ref: str | None = None) -> tuple[str, str | None]:
    with Session(engine) as db:
        payment = start_attempt(db, add_order(db, add_product(db, name=name)), provider)
        if ref is not None:
            payment.provider_payment_ref = ref
            db.commit()
        return payment.id, payment.provider_payment_ref


def errors(results: list) -> list[Exception]:
    return [r for r in results if isinstance(r, Exception)]


def test_the_same_event_id_in_two_origins_at_once_is_two_events_and_both_are_applied():
    with ephemeral_postgres() as engine:
        mock, sandbox = MockPaymentProvider(), SandboxPaymentProvider()
        a_id, a_ref = open_payment(engine, mock, "A")
        b_id, b_ref = open_payment(engine, sandbox, "B")

        results = run_together(
            engine, [delivery(mock, a_id, a_ref, "evt_race"), delivery(sandbox, b_id, b_ref, "evt_race")]
        )

        assert not errors(results), errors(results)
        assert [r.outcome for r in results] == ["applied", "applied"] and not any(r.duplicate for r in results)
        with Session(engine) as db:
            stored = {(e.provider_kind, e.provider_event_id): e.payment_id for e in db.scalars(select(PaymentEvent))}
            assert stored == {("mock", "evt_race"): a_id, ("sandbox", "evt_race"): b_id}
            ledger = {e.payment_id: e.provider_kind for e in db.scalars(select(RevenueLedgerEntry))}
            assert ledger == {a_id: "mock", b_id: "sandbox"}


def test_the_same_event_in_the_same_origin_delivered_twelve_times_at_once_is_applied_once():
    for provider in (SandboxPaymentProvider(), RealPaymentProvider()):
        with ephemeral_postgres() as engine:
            payment_id, ref = open_payment(engine, provider, "A")

            results = run_together(engine, [delivery(provider, payment_id, ref, "evt_same")] * 12)

            assert not errors(results), errors(results)
            assert sorted({r.outcome for r in results}) == ["applied"]
            assert sum(1 for r in results if not r.duplicate) == 1, "exactly one delivery stored the event"
            with Session(engine) as db:
                assert db.scalar(select(func.count()).select_from(PaymentEvent)) == 1
                assert db.scalar(select(func.count()).select_from(RevenueLedgerEntry)) == 1
                assert Decimal(str(db.get(Payment, payment_id).captured_amount)) == Decimal("50")
                assert db.scalars(select(RevenueLedgerEntry)).one().provider_kind == provider.kind.value


def test_two_payments_with_the_same_reference_in_two_origins_each_get_only_their_own_event():
    with ephemeral_postgres() as engine:
        mock, sandbox = MockPaymentProvider(), SandboxPaymentProvider()
        a_id, _ = open_payment(engine, mock, "A", ref="shared_ref")
        b_id, _ = open_payment(engine, sandbox, "B", ref="shared_ref")

        # Solo la referencia del proveedor, sin nuestro id: el origen es lo único que las distingue.
        results = run_together(
            engine, [delivery(mock, None, "shared_ref", "evt_a"), delivery(sandbox, None, "shared_ref", "evt_b")]
        )

        assert not errors(results), errors(results)
        assert [r.outcome for r in results] == ["applied", "applied"]
        with Session(engine) as db:
            events = {e.provider_event_id: (e.provider_kind, e.payment_id) for e in db.scalars(select(PaymentEvent))}
            assert events == {"evt_a": ("mock", a_id), "evt_b": ("sandbox", b_id)}
            assert {p.id: p.status for p in db.scalars(select(Payment))} == {a_id: "SUCCEEDED", b_id: "SUCCEEDED"}


def test_the_schema_built_from_the_models_has_the_postgres_triggers_that_freeze_the_origin():
    """Los disparadores del modelo (`after_create`) son los mismos que los de la migración: el esquema de las pruebas
    y el
    de la base real hablan de lo mismo."""
    with ephemeral_postgres() as engine:
        provider = SandboxPaymentProvider()
        payment_id, ref = open_payment(engine, provider, "A")
        with Session(engine) as db:
            names = {
                row[0]
                for row in db.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid::regclass::text IN "
                         "('payments', 'payment_events', 'revenue_ledger_entries')")
                )
            }  # fmt: skip
            config = db.execute(
                text("SELECT proconfig::text FROM pg_proc WHERE proname = 'provider_kind_immutable'")
            ).scalar()
        assert {"payments_provider_kind_immutable", "payment_events_provider_kind_immutable"} <= names
        assert {"revenue_ledger_entries_append_only_row", "revenue_ledger_entries_append_only_truncate"} <= names
        assert config is not None and "search_path=pg_catalog" in config

        with Session(engine) as db:
            try:
                db.execute(text("UPDATE payments SET provider_kind = 'real' WHERE id = :id"), {"id": payment_id})
            except DBAPIError as exc:
                assert "provider_kind is immutable" in str(exc.orig) and exc.orig.sqlstate == "23001"
            else:  # pragma: no cover - el disparador tiene que rechazarlo
                raise AssertionError("the origin of a payment was rewritten")
            db.rollback()
            db.execute(text("UPDATE payments SET provider_kind = 'sandbox' WHERE id = :id"), {"id": payment_id})
        assert ref is not None
