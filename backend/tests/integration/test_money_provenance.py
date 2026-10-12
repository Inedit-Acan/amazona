"""El origen del dinero viaja del proveedor al cobro, al evento y al registro, y no se mezcla (Milestone 46, ADR 0031).

    PaymentProvider.kind → Payment.provider_kind
                         → PaymentEvent.provider_kind (capturado en `PaymentIngress.receive`, ANTES de emparejar)
                         → RevenueLedgerEntry.provider_kind (copiado del cobro)        Refund: sin columna, el de su
                         cobro

Todo con un proveedor simulado **con guion** y SQLite con las claves ajenas activas (las claves compuestas que impiden
cruzar el origen son lo que se ejerce). Lo propio de PostgreSQL está en `test_money_provenance_postgres.py`.

Los tres orígenes se prueban con **el mismo nombre de proveedor** (`simulated-payments`, el único con política de
operaciones): lo que distingue un cobro de otro es el `kind` que declara el proveedor, nunca su nombre.
"""

import pytest
from payment_test_support import (
    NOW,
    SIMULATION,
    MockPaymentProvider,
    RealPaymentProvider,
    SandboxPaymentProvider,
    ScriptedPaymentProvider,
    deliver,
    events,
    ingress,
    start_attempt,
)
from revenue_test_support import (
    REFUND_SUCCEEDED,
    SUCCEEDED,
    capture,
    capture_entry,
    confirm_refund,
    entries,
    new_order,
    provider_refund,
    refund_of,
)
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.errors import ConflictError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.db.models.revenue import RevenueLedgerEntry
from app.integrations.ports import ProviderKind
from app.money.money import Money
from app.payments.domain import EventProcessing
from app.payments.port import PaymentProviderKindError
from app.payments.service import PaymentService
from app.revenue.ledger import RevenueLedger, RevenueLedgerWriteError

MockProvider, SandboxProvider, RealProvider = MockPaymentProvider, SandboxPaymentProvider, RealPaymentProvider

PROVIDERS = {"mock": MockProvider, "sandbox": SandboxProvider, "real": RealProvider}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


_orders = iter(range(1, 10_000))


def an_order(db: Session) -> Order:
    return new_order(db, name=f"Widget {next(_orders)}")  # 2 × 25.00 = 50.00 EUR


def opened(db: Session, provider, ref: str | None = None) -> Payment:
    """Un cobro abierto (aún sin capturar) con el origen del proveedor; si se pide, con una referencia fijada."""
    payment = start_attempt(db, an_order(db), provider)
    if ref is not None:
        payment.provider_payment_ref = ref
        db.commit()
    return payment


def event_by_ref(db: Session, provider, ref: str | None, *, event_id: str | None = None, client_reference=None):
    """Lo que enviaría el proveedor **solo con su referencia** (sin nuestro id): firmado y entregado por la puerta."""
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=ref,
        client_reference=client_reference,
        amount=Money.of("50.00", "EUR"),
        event_id=event_id,
    )
    return ingress(db, provider).receive(provider.name, headers, raw)


def kinds(db: Session) -> dict[str, str]:
    db.expire_all()
    return {row.id: row.provider_kind for row in db.scalars(select(Payment))}


# --- 1. El origen nace en el proveedor
# ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["mock", "sandbox", "real"])
def test_a_payment_is_opened_with_the_origin_its_provider_declares(db: Session, kind: str):
    payment = opened(db, PROVIDERS[kind]())

    assert payment.provider_kind == kind
    assert db.get(Payment, payment.id).provider_kind == kind


def test_the_name_and_is_simulated_classify_nothing(db: Session):
    """Un proveedor llamado «simulated-payments» que declara `real` abre un cobro `real`; y el pedido sigue siendo de
    una simulación (`sim_…`): `Order.is_simulated` es contexto del pedido, no origen del dinero."""
    provider = RealProvider()
    order = an_order(db)
    assert order.is_simulated is True and provider.name == "simulated-payments"

    payment = start_attempt(db, order, provider)

    assert payment.provider_kind == "real"
    assert db.get(Order, order.id).is_simulated is True


@pytest.mark.parametrize("bad", ["mock", None, ProviderKind.COMPOSITE], ids=["a-string", "none", "composite"])
def test_a_provider_without_a_structured_kind_opens_no_payment_and_receives_no_event(db: Session, bad):
    good = MockProvider()
    payment = opened(db, good)
    nameless = type("Undeclared", (ScriptedPaymentProvider,), {"kind": bad})()
    order = an_order(db)  # crear un pedido escribe auditoría: se hace antes de medir
    audit_before = db.scalar(select(text("count(*)")).select_from(AuditLog))

    with pytest.raises(PaymentProviderKindError):
        start_attempt(db, order, nameless)
    headers, raw = nameless.simulate_event(SUCCEEDED, provider_payment_ref=None, client_reference=payment.id,
                                           amount=Money.of("50.00", "EUR"))  # fmt: skip
    with pytest.raises(PaymentProviderKindError):
        ingress(db, nameless).receive(nameless.name, headers, raw)

    db.rollback()
    assert events(db) == [], "no event was stored"
    assert [p.id for p in db.scalars(select(Payment))] == [payment.id], "no payment was opened"
    assert db.scalar(select(text("count(*)")).select_from(AuditLog)) == audit_before, "and nothing else was written"


# --- 2. El evento captura el origen antes de emparejar, y un UNMATCHED lo conserva
# ----------------------------------------------


@pytest.mark.parametrize("kind", ["mock", "sandbox", "real"])
def test_an_unmatched_event_keeps_a_known_origin_without_a_payment(db: Session, kind: str):
    provider = PROVIDERS[kind]()

    result = event_by_ref(db, provider, "ghost_ref", client_reference="ghost_payment")

    assert result.outcome == "unmatched"
    stored = events(db)[0]
    assert (stored.provider_kind, stored.payment_id, stored.processing_status) == (kind, None, "UNMATCHED")
    assert entries(db) == []


def test_the_origin_is_captured_before_the_event_is_matched_or_applied(db: Session, monkeypatch):
    """Aunque aplicar el evento falle, el evento ya está guardado con su origen: se capturó antes de emparejar."""
    provider = SandboxProvider()
    payment = opened(db, provider)

    def boom(self, event_id):
        raise RuntimeError("the process died between the two transactions")

    monkeypatch.setattr(PaymentService, "apply", boom)
    with pytest.raises(RuntimeError):
        deliver(db, provider, SUCCEEDED, payment)

    db.rollback()
    stored = events(db)[0]
    assert (stored.provider_kind, stored.processing_status, stored.payment_id) == ("sandbox", "RECEIVED", None)


def test_a_received_event_is_applied_with_the_origin_it_was_stored_with_whatever_the_configuration_says_now(
    db: Session, monkeypatch
):
    """La reconciliación reaplica un evento `RECEIVED` sin consultar a ningún proveedor ni a la configuración."""
    provider = MockProvider()
    payment = opened(db, provider)
    monkeypatch.setattr(PaymentService, "apply", lambda self, event_id: (_ for _ in ()).throw(RuntimeError("died")))
    with pytest.raises(RuntimeError):
        deliver(db, provider, SUCCEEDED, payment)
    db.rollback()
    monkeypatch.undo()
    stored = events(db)[0]
    assert stored.processing_status == "RECEIVED"

    # La configuración dice ahora otra cosa: da igual, el hecho ya tiene su origen.
    SIMULATION.model_copy(update={"payments_provider": ProviderKind.SANDBOX})
    outcome = PaymentService(db).apply(stored.id)

    assert outcome == EventProcessing.APPLIED.value
    assert capture_entry(db, payment).provider_kind == "mock"


def test_facts_already_persisted_keep_their_origin_when_the_provider_changes(db: Session):
    old = capture(db, MockProvider(), an_order(db))
    old_entry = capture_entry(db, old)

    new = capture(db, SandboxProvider(), an_order(db))

    assert (kinds(db)[old.id], kinds(db)[new.id]) == ("mock", "sandbox")
    assert capture_entry(db, old).provider_kind == "mock" == old_entry.provider_kind
    assert capture_entry(db, new).provider_kind == "sandbox"
    assert {e.provider_kind for e in events(db)} == {"mock", "sandbox"}


# --- 3. F12: las identidades llevan el origen (B-parcial)
# ---------------------------------------------------------------------


def test_scenario_1_same_provider_and_reference_in_the_same_origin_is_the_same_object(db: Session):
    """(1) Misma referencia, mismo origen: la identidad sigue siendo única; un segundo cobro con ella se rechaza."""
    provider = SandboxProvider()
    opened(db, provider, ref="shared_ref")

    with pytest.raises(IntegrityError, match="UNIQUE"):
        opened(db, provider, ref="shared_ref")
    db.rollback()


def test_scenario_2_same_provider_and_reference_in_another_origin_is_another_payment(db: Session):
    """(2) Misma referencia, otro origen: son dos cobros distintos, y cada evento va al suyo y a ninguno más."""
    mock, sandbox = MockProvider(), SandboxProvider()
    a = opened(db, mock, ref="shared_ref")
    b = opened(db, sandbox, ref="shared_ref")

    assert event_by_ref(db, sandbox, "shared_ref").outcome == "applied"
    db.expire_all()
    assert (db.get(Payment, b.id).status, db.get(Payment, a.id).status) == ("SUCCEEDED", "OPEN")
    assert event_by_ref(db, mock, "shared_ref").outcome == "applied"
    db.expire_all()
    assert db.get(Payment, a.id).status == "SUCCEEDED"
    assert {e.payment_id: e.provider_kind for e in events(db)} == {a.id: "mock", b.id: "sandbox"}


@pytest.mark.parametrize("pair", [("mock", "sandbox"), ("sandbox", "real")], ids=["mock-sandbox", "sandbox-real"])
def test_scenarios_3_and_4_the_same_event_id_in_two_origins_is_two_events(db: Session, pair):
    """(3, 4) El mismo id de evento en dos orígenes: dos eventos, ninguno es «reentrega» del otro; ambos se aplican."""
    first, second = (PROVIDERS[k]() for k in pair)
    a, b = opened(db, first), opened(db, second)

    ra = deliver(db, first, SUCCEEDED, a, event_id="evt_same", occurred_at=NOW)
    rb = deliver(db, second, SUCCEEDED, b, event_id="evt_same", occurred_at=NOW)

    assert (ra.outcome, ra.duplicate, rb.outcome, rb.duplicate) == ("applied", False, "applied", False)
    # Con las dos filas ya guardadas, una reentrega sigue siendo la reentrega **de la suya** y de ninguna más.
    assert deliver(db, second, SUCCEEDED, b, event_id="evt_same", occurred_at=NOW).duplicate is True
    assert deliver(db, first, SUCCEEDED, a, event_id="evt_same", occurred_at=NOW).duplicate is True
    stored = {(e.provider_kind, e.provider_event_id): e.payment_id for e in events(db)}
    assert stored == {(pair[0], "evt_same"): a.id, (pair[1], "evt_same"): b.id}
    assert capture_entry(db, a).provider_kind == pair[0] and capture_entry(db, b).provider_kind == pair[1]


def test_the_same_event_id_in_the_same_origin_is_still_one_event(db: Session):
    provider = SandboxProvider()
    payment = opened(db, provider)

    deliver(db, provider, SUCCEEDED, payment, event_id="evt_same", occurred_at=NOW)
    again = deliver(db, provider, SUCCEEDED, payment, event_id="evt_same", occurred_at=NOW)

    assert again.duplicate is True
    assert len(events(db)) == 1


def test_scenario_6_an_event_of_another_origin_cannot_attach_to_the_payment_it_names(db: Session):
    """(6) Un evento `sandbox` que nombra, por nuestro id, un cobro `mock`: `CONFLICT`. Se conserva como evidencia, no
    se
    enlaza al cobro, no toca el cobro ni el pedido, y no llega al registro."""
    mock, sandbox = MockProvider(), SandboxProvider()
    payment = opened(db, mock)

    result = deliver(db, sandbox, SUCCEEDED, payment)

    assert result.outcome == "conflict"
    stored = events(db)[0]
    assert (stored.provider_kind, stored.payment_id, stored.processing_status) == ("sandbox", None, "CONFLICT")
    assert "another origin" in (stored.note or "")
    db.expire_all()
    assert db.get(Payment, payment.id).status == "OPEN" and db.get(Payment, payment.id).captured_amount == 0
    assert db.get(Order, payment.order_id).status == "AWAITING_PAYMENT"
    assert entries(db) == []
    mismatch = db.scalars(select(AuditLog).where(AuditLog.action == "payment_event.origin_mismatch")).all()
    assert (
        len(mismatch) == 1
        and mismatch[0].after["event_kind"] == "sandbox"
        and mismatch[0].after["payment_kind"] == "mock"
    )


def test_a_reference_match_in_another_origin_is_not_a_match(db: Session):
    """Solo la referencia coincide, y es de otro origen: no es el mismo hecho financiero. El evento queda
    `UNMATCHED`."""
    payment = opened(db, MockProvider(), ref="only_in_mock")

    result = event_by_ref(db, SandboxProvider(), "only_in_mock")

    assert result.outcome == "unmatched"
    db.expire_all()
    assert db.get(Payment, payment.id).status == "OPEN" and entries(db) == []
    assert events(db)[0].provider_kind == "sandbox"


# --- 4. El registro copia el origen, y un reembolso conserva el del cobro que devuelve
# ---------------------------------------------


@pytest.mark.parametrize("kind", ["mock", "sandbox", "real"])
def test_the_ledger_entry_copies_the_origin_of_its_payment_and_of_its_event(db: Session, kind: str):
    payment = capture(db, PROVIDERS[kind](), an_order(db))

    entry = capture_entry(db, payment)

    assert entry.provider_kind == kind == payment.provider_kind
    assert db.get(PaymentEvent, entry.payment_event_id).provider_kind == kind


@pytest.mark.parametrize("kind", ["mock", "sandbox", "real"])
def test_scenario_7_a_refund_keeps_the_origin_of_the_payment_it_returns(db: Session, kind: str):
    provider = PROVIDERS[kind]()
    payment = capture(db, provider, an_order(db))
    refund = refund_of(db, provider, payment, "10.00")

    confirm_refund(db, provider, refund)

    refund_entry = next(e for e in entries(db) if e.kind == "REFUND")
    assert refund_entry.provider_kind == kind == capture_entry(db, payment).provider_kind
    assert not hasattr(Refund, "provider_kind"), "B-parcial: refunds never get their own provider_kind"
    assert db.get(Payment, refund.payment_id).provider_kind == kind


def test_a_refund_started_by_the_provider_keeps_the_origin_too(db: Session):
    provider = SandboxProvider()
    payment = capture(db, provider, an_order(db))

    provider_refund(db, provider, payment, "10.00", "re_provider_1", "evt_refund_1")

    refund_entry = next(e for e in entries(db) if e.kind == "REFUND")
    assert refund_entry.provider_kind == "sandbox"
    assert db.scalars(select(Refund)).one().origin == "PROVIDER"


def test_a_refund_cannot_be_requested_through_a_provider_of_another_origin(db: Session):
    payment = capture(db, SandboxProvider(), an_order(db))

    with pytest.raises(ConflictError, match="was taken at origin sandbox, not at mock"):
        refund_of(db, MockProvider(), payment, "10.00")

    db.rollback()
    assert db.get(Payment, payment.id).refund_committed_amount == 0
    assert db.scalars(select(Refund)).all() == []


def test_a_refund_event_of_another_origin_is_a_conflict_and_never_reaches_the_ledger(db: Session):
    sandbox, mock = SandboxProvider(), MockProvider()
    payment = capture(db, sandbox, an_order(db))
    refund = refund_of(db, sandbox, payment, "10.00")
    before = len(entries(db))

    result = confirm_refund(db, mock, refund)  # el reembolso lo confirma un proveedor de otro origen

    assert result.outcome == "conflict"
    assert len(entries(db)) == before and db.get(Refund, refund.id).status != "SUCCEEDED"
    assert events(db)[-1].payment_id is None and events(db)[-1].provider_kind == "mock"


def test_a_refund_reference_in_another_origin_is_not_a_match(db: Session):
    """`refunds` no lleva `provider_kind` (B-parcial): el origen se exige por el cobro del reembolso. Un evento `mock`
    que solo
    coincide con la referencia de un reembolso `sandbox` no es ese reembolso: queda `UNMATCHED` y el reembolso no se
    toca."""
    sandbox, mock = SandboxProvider(), MockProvider()
    payment = capture(db, sandbox, an_order(db))
    refund = refund_of(db, sandbox, payment, "10.00")
    refund.provider_refund_ref = "re_shared"
    db.commit()
    headers, raw = mock.simulate_event(
        REFUND_SUCCEEDED, provider_payment_ref=None, provider_refund_ref="re_shared", client_reference=None,
        amount=Money.of("10.00", "EUR"),
    )  # fmt: skip

    result = ingress(db, mock).receive(mock.name, headers, raw)

    assert result.outcome == "unmatched"
    db.expire_all()
    assert db.get(Refund, refund.id).status == "SENDING" and db.get(Payment, payment.id).refunded_amount == 0
    assert [e.kind for e in entries(db)] == ["CAPTURE"]
    assert events(db)[-1].provider_kind == "mock" and events(db)[-1].payment_id is None


def test_the_ledger_refuses_an_entry_whose_event_is_of_another_origin_than_its_payment(db: Session):
    payment = capture(db, SandboxProvider(), an_order(db))
    stranger = PaymentEvent(
        provider=payment.provider,
        provider_kind="mock",
        provider_event_id="evt_stranger",
        event_type="payment.succeeded",
        occurred_at=payment.created_at,
        received_at=payment.created_at,
        payload_hash="h",
        processing_status="APPLIED",
    )
    db.add(stranger)
    db.flush()

    with pytest.raises(RevenueLedgerWriteError, match="from origin mock and its payment from sandbox"):
        RevenueLedger(db).record_capture(event=stranger, payment=payment, payment_status="SUCCEEDED", amount=50)


# --- 5. Nada se mezcla después de persistir
# -------------------------------------------------------------------------------------


def test_scenario_8_the_origin_of_a_payment_and_an_event_cannot_be_rewritten(db: Session):
    payment = capture(db, SandboxProvider(), an_order(db))
    stored = events(db)[0]

    for table, row_id in (("payments", payment.id), ("payment_events", stored.id)):
        with pytest.raises(DBAPIError, match="provider_kind is immutable"):
            db.execute(text(f"UPDATE {table} SET provider_kind = 'real' WHERE id = :id"), {"id": row_id})
        db.rollback()
        db.execute(
            text(f"UPDATE {table} SET provider_kind = 'sandbox' WHERE id = :id"), {"id": row_id}
        )  # el mismo valor
    assert kinds(db)[payment.id] == "sandbox"


def test_scenario_8_the_ledger_keeps_its_origin_it_is_append_only(db: Session):
    payment = capture(db, SandboxProvider(), an_order(db))
    entry = capture_entry(db, payment)

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE revenue_ledger_entries SET provider_kind = 'real' WHERE id = :id"), {"id": entry.id})
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM revenue_ledger_entries WHERE id = :id"), {"id": entry.id})
    db.rollback()
    assert capture_entry(db, payment).provider_kind == "sandbox"


def test_scenario_8_an_event_cannot_be_linked_to_a_payment_of_another_origin(db: Session):
    """La clave ajena compuesta lo impide también por debajo del código: un `UNMATCHED` mock no se enlaza a un cobro
    sandbox."""
    mock, sandbox = MockProvider(), SandboxProvider()
    event_by_ref(db, mock, "ghost", client_reference="ghost")
    stray = events(db)[0]
    target = opened(db, sandbox)

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        db.execute(text("UPDATE payment_events SET payment_id = :p WHERE id = :e"), {"p": target.id, "e": stray.id})
    db.rollback()
    assert events(db)[0].payment_id is None


@pytest.mark.parametrize("which", ["payment", "event"])
def test_scenario_8_a_ledger_entry_cannot_carry_another_origin_than_its_payment_or_its_event(db: Session, which: str):
    payment = opened(db, SandboxProvider())  # sin captura propia: el índice «una captura por cobro» no estorba
    good = capture(db, SandboxProvider(), an_order(db))
    good = capture_entry(db, good)
    other_event = PaymentEvent(
        provider=payment.provider, provider_kind="real", provider_event_id="evt_spare",
        event_type="payment.succeeded", occurred_at=good.occurred_at, received_at=good.occurred_at, payload_hash="h",
        processing_status="STALE",
    )  # fmt: skip
    db.add(other_event)
    db.flush()
    forged = RevenueLedgerEntry(
        kind="CAPTURE", classification="MISMATCH_RECEIPT", payment_event_id=other_event.id,
        payment_id=payment.id, order_id=payment.order_id, amount=1, currency="EUR", occurred_at=good.occurred_at,
        recorded_at=good.recorded_at, provider_kind="real" if which == "payment" else "sandbox",
    )  # fmt: skip

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        db.add(forged)
        db.flush()
    db.rollback()


def test_a_closed_set_of_origins_the_database_refuses_anything_else(db: Session):
    payment = capture(db, SandboxProvider(), an_order(db))

    with pytest.raises(IntegrityError, match="CHECK"):
        db.add(
            Payment(
                order_id=payment.order_id,
                attempt_number=9,
                provider="simulated-payments",
                provider_kind="composite",
                status="REQUESTED",
                amount=1,
                currency="EUR",
                correlation_id="c",
            )
        )
        db.flush()
    db.rollback()


def test_a_payment_without_an_origin_is_refused_there_is_no_default(db: Session):
    payment = capture(db, SandboxProvider(), an_order(db))

    with pytest.raises(IntegrityError, match="NOT NULL"):
        db.add(Payment(order_id=payment.order_id, attempt_number=9, provider="simulated-payments", status="REQUESTED",
                       amount=1, currency="EUR", correlation_id="c"))  # fmt: skip
        db.flush()
    db.rollback()
