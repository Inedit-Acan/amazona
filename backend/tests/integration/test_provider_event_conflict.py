"""Un identificador de evento del proveedor se recibe una vez; con otro contenido es un conflicto limpio (M45, P3-12).

El simulador pone en el cuerpo del evento el instante en que lo hace (`created`), y el hash que se guarda es el del
cuerpo bruto: repetir `--event-id` desde la consola produce otro contenido con el mismo identificador. La puerta lo
rechaza (correcto, es la defensa del webhook) con un `ConflictError`, pero la consola solo traducía `BootstrapError`:
el rechazo salía como un *traceback*.

Contrato que se prueba, en el servicio (la puerta) y en la consola:

- mismo id y **mismo contenido** → una entrega repetida: no cambia nada, no hay un segundo efecto (la firma, que va en
  la cabecera y lleva su propio sello de tiempo, no forma parte del contenido);
- mismo id y **otro contenido** → `ProviderEventConflictError` (un `ConflictError`: un 409 en el webhook, igual que
  siempre), sea cual sea el estado del evento original; el original no se sobrescribe, ni se aplica, ni se resuelve, y
  ningún pago, pedido ni reembolso cambia; solo queda una entrada de auditoría sin cuerpo;
- la consola termina con un mensaje claro, **sin traceback**, sin cuerpo ni hash ni firma, y con el código de salida 3
  (el 2 es «el comando se negó a ejecutarse»).
"""

import datetime
from decimal import Decimal

import pytest
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import (
    REQUESTER,
    SIMULATION,
    ScriptedPaymentProvider,
    add_order,
    captured_total,
    deliver,
    events,
    fresh_order_status,
    ingress,
    reload,
    start_attempt,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import cli
from app.core.errors import ConflictError
from app.db.models.audit import AuditLog
from app.db.models.external_action import ExternalAction
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent, Refund
from app.money.money import Money
from app.orders.payment_attempts import PaymentAttemptService
from app.orders.refunds import RefundService
from app.payments.ingress import ProviderEventConflictError
from app.payments.port import PaymentEventType
from app.payments.service import PaymentService

SUCCEEDED = PaymentEventType.PAYMENT_SUCCEEDED
T1 = datetime.datetime(2026, 10, 3, 10, 0, tzinfo=datetime.UTC)
T2 = datetime.datetime(2026, 10, 3, 10, 0, 1, tzinfo=datetime.UTC)  # un segundo después


@pytest.fixture()
def db():
    engine = make_engine()
    session = session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def order(db: Session) -> Order:
    return add_order(db, add_product(db))  # 2 × 25.00 = 50.00


def snapshot(db: Session) -> dict:
    """Lo que un evento rechazado no puede tocar: el evento, los cobros, los pedidos, los reembolsos y las acciones."""
    db.expire_all()
    return {
        "events": [
            (e.id, e.provider_event_id, e.event_type, e.payload_hash, e.processing_status, e.processed_at, e.note)
            + (e.payment_id, e.refund_id, str(e.amount), e.currency, e.occurred_at, e.received_at)
            for e in db.scalars(select(PaymentEvent).order_by(PaymentEvent.id))
        ],
        "payments": [
            (p.id, p.status, str(p.captured_amount), str(p.refunded_amount), str(p.refund_committed_amount))
            + (p.last_event_at, p.closed_at, p.succeeded_at, p.last_failure_code)
            for p in db.scalars(select(Payment).order_by(Payment.id))
        ],
        "orders": [(o.id, o.status, o.paid_at) for o in db.scalars(select(Order).order_by(Order.id))],
        "refunds": [(r.id, r.status, str(r.amount)) for r in db.scalars(select(Refund).order_by(Refund.id))],
        "actions": [(a.id, a.status) for a in db.scalars(select(ExternalAction).order_by(ExternalAction.id))],
    }


def audit_count(db: Session, action: str) -> int:
    return len(list(db.scalars(select(AuditLog).where(AuditLog.action == action))))


# =====================================================================================================================
# La puerta (servicio)
# =====================================================================================================================


@pytest.fixture()
def provider() -> ScriptedPaymentProvider:
    return ScriptedPaymentProvider()


def test_the_same_id_and_content_with_another_signature_stamp_is_one_repeated_delivery(
    db: Session, order: Order, provider
):
    """La firma lleva su propio sello de tiempo y se regenera en cada entrega: no forma parte del contenido."""
    payment = start_attempt(db, order, provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
        event_id="evt_same",
        occurred_at=T1,
    )
    first = ingress(db, provider).receive(provider.name, headers, raw)
    assert first.outcome == "applied" and first.duplicate is False
    before = snapshot(db)
    other_signature = provider.sign(raw, timestamp=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=30))
    assert other_signature != headers, "the signature really is another one"

    again = ingress(db, provider).receive(provider.name, other_signature, raw)

    assert again.duplicate is True and again.outcome == "applied" and again.event_id == first.event_id
    assert snapshot(db) == before, "a repeated delivery changes nothing"
    assert captured_total(db, order) == Decimal("50") and audit_count(db, "payment.captured") == 1


def test_the_same_id_made_at_another_instant_is_a_conflict_that_keeps_the_original_and_touches_nothing(
    db: Session, order: Order, provider
):
    payment = start_attempt(db, order, provider)
    deliver(db, provider, SUCCEEDED, payment, event_id="evt_same", occurred_at=T1)
    before = snapshot(db)

    with pytest.raises(ProviderEventConflictError) as raised:
        deliver(db, provider, SUCCEEDED, payment, event_id="evt_same", occurred_at=T2)

    assert isinstance(raised.value, ConflictError), "still the 409 of the webhook"
    assert raised.value.provider_event_id == "evt_same"
    assert str(raised.value) == (
        "this provider event id was already received with different content: the original is kept"
    )
    assert snapshot(db) == before, "the original is not overwritten and nothing else moves"
    assert captured_total(db, order) == Decimal("50") and fresh_order_status(db, order) == "PAID"
    mismatch = db.scalars(select(AuditLog).where(AuditLog.action == "payment_event.payload_mismatch")).one()
    assert set(mismatch.after) == {"provider", "provider_event_id"}, "no body, no hash in the trail"


@pytest.mark.parametrize("state", ["APPLIED", "STALE", "CONFLICT", "UNMATCHED", "REJECTED"])
def test_a_conflicting_delivery_leaves_an_event_in_any_settled_state_as_it_was(
    db: Session, order: Order, provider, state: str
):
    payment = start_attempt(db, order, provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
        event_id="evt_state",
        occurred_at=T1,
    )
    ingress(db, provider).receive(provider.name, headers, raw)
    db.execute(update(PaymentEvent).values(processing_status=state, note="as it was"))
    db.commit()
    before = snapshot(db)

    with pytest.raises(ProviderEventConflictError):
        deliver(db, provider, SUCCEEDED, payment, event_id="evt_state", occurred_at=T2)
    assert snapshot(db) == before

    again = ingress(db, provider).receive(provider.name, headers, raw)
    assert again.duplicate is True and again.outcome == state.lower(), "the identical delivery gets the settled state"
    assert snapshot(db) == before


def test_a_conflicting_delivery_does_not_apply_an_event_that_was_stored_and_never_applied(
    db: Session, order: Order, provider, monkeypatch
):
    """Un evento `RECEIVED` espera su reentrega idéntica; otra con distinto contenido no lo aplica ni lo cambia."""

    class Crash(BaseException):
        pass

    payment = start_attempt(db, order, provider)
    headers, raw = provider.simulate_event(
        SUCCEEDED,
        provider_payment_ref=payment.provider_payment_ref,
        client_reference=payment.id,
        amount=Money.of("50.00", "EUR"),
        event_id="evt_pending",
        occurred_at=T1,
    )
    real_apply = PaymentService.apply

    def crash(self, event_id):
        raise Crash("died between the two transactions")

    monkeypatch.setattr(PaymentService, "apply", crash)
    with pytest.raises(Crash):
        ingress(db, provider).receive(provider.name, headers, raw)
    monkeypatch.setattr(PaymentService, "apply", real_apply)
    db.rollback()
    (stored,) = events(db)
    assert stored.processing_status == "RECEIVED"
    before = snapshot(db)

    with pytest.raises(ProviderEventConflictError):
        deliver(db, provider, SUCCEEDED, payment, event_id="evt_pending", occurred_at=T2)

    assert snapshot(db) == before, "still RECEIVED, still not applied, the order still unpaid"
    assert reload(db, payment).status == "OPEN" and fresh_order_status(db, order) == "AWAITING_PAYMENT"

    resumed = ingress(db, provider).receive(provider.name, headers, raw)
    assert resumed.duplicate is True and resumed.outcome == "applied"
    assert captured_total(db, order) == Decimal("50") and len(events(db)) == 1


# =====================================================================================================================
# La consola
# =====================================================================================================================


@pytest.fixture()
def console(db: Session, monkeypatch):
    """`cli.main` contra la base de la prueba, con el indicador de arranque puesto."""
    factory = session_factory(db.get_bind())
    monkeypatch.setenv(cli.BOOTSTRAP_ENV, "1")
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    return cli.main


@pytest.fixture()
def payment(db: Session, order: Order) -> Payment:
    # Con el proveedor del registro, como en un despliegue: la clave de firma es la del proceso, que usa el CLI.
    return PaymentAttemptService(db, settings=SIMULATION).start(order.id, requester=REQUESTER)


def simulate(console, order: Order, *extra: str) -> int:
    return console(["simulate-payment", "--order-id", order.id, *extra])


def test_the_console_refuses_a_reused_event_id_cleanly_with_exit_code_3(
    db: Session, order: Order, payment: Payment, console, capsys
):
    """La prueba que falla con el código anterior: `main` dejaba escapar el `ConflictError` (un traceback)."""
    assert simulate(console, order, "--outcome", "succeeded", "--event-id", "evt_cli") == 0
    capsys.readouterr()
    before = snapshot(db)

    status = simulate(console, order, "--outcome", "succeeded", "--event-id", "evt_cli")

    captured = capsys.readouterr()
    assert status == cli.EXIT_CONFLICT == 3
    assert captured.out == "", "a refused command prints nothing on stdout"
    assert "evt_cli" in captured.err and "different content" in captured.err
    assert "original event is kept and nothing was changed" in captured.err
    assert "--event-id" in captured.err and "--occurred-at" in captured.err, "it says what to do"
    assert "Traceback" not in captured.err
    assert snapshot(db) == before and fresh_order_status(db, order) == "PAID"


def test_the_console_never_prints_the_body_the_hash_or_the_signature_of_a_refused_event(
    db: Session, order: Order, payment: Payment, console, capsys
):
    simulate(console, order, "--outcome", "succeeded", "--event-id", "evt_cli", "--amount", "50.00")
    stored_hash = events(db)[0].payload_hash
    capsys.readouterr()

    simulate(console, order, "--outcome", "succeeded", "--event-id", "evt_cli", "--amount", "49.00")

    shown = capsys.readouterr()
    for text in (shown.out, shown.err):
        assert stored_hash not in text and "v1=" not in text and '"data"' not in text and "49.00" not in text


def test_the_same_event_id_with_the_same_instant_is_a_repeated_delivery_from_the_console(
    db: Session, order: Order, payment: Payment, console, capsys
):
    arguments = ("--outcome", "succeeded", "--event-id", "evt_cli", "--occurred-at", T1.isoformat())
    assert simulate(console, order, *arguments) == 0
    assert "(a repeated delivery)" not in capsys.readouterr().out
    before = snapshot(db)

    assert simulate(console, order, *arguments) == 0

    assert "(a repeated delivery)" in capsys.readouterr().out
    assert snapshot(db) == before and len(events(db)) == 1
    assert captured_total(db, order) == Decimal("50") and audit_count(db, "payment.captured") == 1


@pytest.mark.parametrize(
    "other",
    [
        ("--occurred-at", T2.isoformat()),
        ("--occurred-at", T1.isoformat(), "--amount", "49.00"),
        ("--occurred-at", T1.isoformat(), "--outcome", "expired"),
    ],
    ids=["another instant", "another amount", "another outcome"],
)
def test_any_change_of_content_under_the_same_event_id_is_refused_from_the_console(
    db: Session, order: Order, payment: Payment, console, capsys, other
):
    base = ["--outcome", "succeeded", "--event-id", "evt_cli", "--occurred-at", T1.isoformat()]
    assert simulate(console, order, *base) == 0
    capsys.readouterr()
    before = snapshot(db)
    # `--outcome` repetido: gana el último, como en cualquier CLI
    status = simulate(console, order, *base, *other)

    assert status == 3 and "Traceback" not in capsys.readouterr().err
    assert snapshot(db) == before


def test_a_refund_confirmation_is_protected_the_same_way(db: Session, order: Order, payment: Payment, console, capsys):
    simulate(console, order, "--outcome", "succeeded")
    refund = RefundService(db, settings=SIMULATION).request(
        payment.id, amount=Money.of("10.00", "EUR"), reason="customer_request", requester=REQUESTER
    )
    arguments = ["simulate-refund", "--refund-id", refund.id, "--outcome", "succeeded", "--event-id", "evt_ref"]
    assert console([*arguments, "--occurred-at", T1.isoformat()]) == 0
    assert console([*arguments, "--occurred-at", T1.isoformat()]) == 0, "the identical delivery is repeated"
    capsys.readouterr()
    before = snapshot(db)

    assert console([*arguments, "--occurred-at", T2.isoformat()]) == 3

    shown = capsys.readouterr()
    assert "evt_ref" in shown.err and "Traceback" not in shown.err and shown.out == ""
    assert snapshot(db) == before
    settled = reload(db, payment)
    assert (settled.refund_committed_amount, settled.refunded_amount) == (10, 10), "the refund counted once"


def test_a_domain_conflict_of_any_command_is_the_consoles_409_and_not_a_traceback(console, capsys, monkeypatch):
    """La frontera es la del `ConflictError` (en HTTP, un 409): vale para cualquier comando, no solo los eventos."""

    def conflict(db, *, older_than_minutes):
        raise ConflictError("something else already moved this")

    monkeypatch.setattr(cli, "reconcile_actions", conflict)

    status = console(["reconcile-actions"])

    shown = capsys.readouterr()
    assert status == cli.EXIT_CONFLICT
    assert shown.err == "error: something else already moved this\n" and shown.out == ""


@pytest.mark.parametrize("value", ["not-a-date", "2026-10-03T10:00:00", "2026-13-45T00:00:00+00:00"])
def test_a_malformed_or_naive_instant_is_refused_by_the_command_with_exit_code_2(
    db: Session, order: Order, payment: Payment, console, capsys, value
):
    before = snapshot(db)

    status = simulate(console, order, "--outcome", "succeeded", "--occurred-at", value)

    assert status == cli.EXIT_REFUSED == 2
    assert "--occurred-at" in capsys.readouterr().err
    assert snapshot(db) == before


def test_the_exit_codes_are_distinct_and_stable():
    assert (cli.EXIT_REFUSED, cli.EXIT_CONFLICT) == (2, 3)
    assert issubclass(ProviderEventConflictError, ConflictError)
