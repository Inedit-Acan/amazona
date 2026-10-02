"""Los comandos del operador para los pagos (Milestone 44, ADR 0028 §1).

`simulate-payment` no toca pedidos ni cobros: el simulador firma un evento con su clave efímera y lo entrega a la
misma puerta que un webhook real. `reconcile-payment-events` aplica de nuevo lo que se guardó y no se aplicó. Ambos
exigen `AMAZONA_BOOTSTRAP=1`.
"""

import datetime

import pytest
from order_test_support import add_product, make_engine, session_factory
from payment_test_support import REQUESTER, SIMULATION, add_order, events, fresh_order_status, reload  # noqa: E402
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import cli
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.models.order import Order
from app.db.models.payment import Payment, PaymentEvent
from app.integrations.ports import ProviderKind
from app.orders.payment_attempts import PaymentAttemptService
from app.payments.service import PaymentService


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
    return add_order(db, add_product(db))


@pytest.fixture()
def payment(db: Session, order: Order) -> Payment:
    # Con el proveedor del registro, como en un despliegue: la clave de firma es la del proceso, que usa el CLI.
    return PaymentAttemptService(db, settings=SIMULATION).start(order.id, requester=REQUESTER)


def test_a_simulated_capture_goes_through_the_door_and_pays_the_order(db: Session, order: Order, payment: Payment):
    result = cli.simulate_payment(db, order_id=order.id, outcome="succeeded")

    assert result.outcome == "applied" and result.duplicate is False
    assert reload(db, payment).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    (event,) = events(db)
    assert event.provider == "simulated-payments" and event.processing_status == "APPLIED"


@pytest.mark.parametrize(
    "outcome, status",
    [("failed", "FAILED"), ("expired", "EXPIRED"), ("attempt-failed", "OPEN")],
)
def test_the_other_simulated_outcomes(db: Session, order: Order, payment: Payment, outcome, status):
    cli.simulate_payment(db, payment_id=payment.id, outcome=outcome)

    assert reload(db, payment).status == status and fresh_order_status(db, order) == "AWAITING_PAYMENT"


def test_a_simulated_capture_of_another_amount_is_recorded_as_a_mismatch(db: Session, order: Order, payment: Payment):
    cli.simulate_payment(db, order_id=order.id, outcome="succeeded", amount="12.50")

    assert reload(db, payment).status == "CAPTURE_MISMATCH" and fresh_order_status(db, order) == "AWAITING_PAYMENT"


def test_reusing_an_event_id_with_other_content_is_refused_as_a_conflict(db: Session, order: Order, payment: Payment):
    """El CLI vuelve a generar el evento (otro instante): mismo id, otro contenido. Un reenvío idéntico, byte a byte,
    es un duplicado y se prueba en `test_payment_events`."""
    cli.simulate_payment(db, order_id=order.id, outcome="succeeded", event_id="evt_cli")

    with pytest.raises(ConflictError, match="different content"):
        cli.simulate_payment(db, order_id=order.id, outcome="succeeded", event_id="evt_cli")

    assert len(events(db)) == 1 and fresh_order_status(db, order) == "PAID"


def test_the_command_says_which_payment_and_refuses_unknown_ones(db: Session, order: Order, payment: Payment):
    with pytest.raises(cli.BootstrapError, match="which payment"):
        cli.simulate_payment(db, outcome="succeeded")
    with pytest.raises(cli.BootstrapError, match="which payment"):
        cli.simulate_payment(db, outcome="succeeded", order_id=order.id, payment_id=payment.id)
    with pytest.raises(NotFoundError):
        cli.simulate_payment(db, outcome="succeeded", payment_id="missing")


def test_only_the_simulated_provider_can_emit_events(db: Session, order: Order, payment: Payment, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: Settings(_env_file=None, payments_provider=ProviderKind.REAL)
    )

    with pytest.raises(cli.BootstrapError, match="no payment provider"):
        cli.simulate_payment(db, order_id=order.id, outcome="succeeded")

    assert events(db) == [] and reload(db, payment).status == "OPEN"


@pytest.mark.parametrize(
    "argv",
    [
        ["simulate-payment", "--order-id", "x", "--outcome", "succeeded"],
        ["reconcile-payment-events"],
    ],
)
def test_the_commands_need_the_bootstrap_flag(monkeypatch, capsys, argv):
    monkeypatch.delenv(cli.BOOTSTRAP_ENV, raising=False)

    assert cli.main(argv) == 2
    assert "AMAZONA_BOOTSTRAP=1" in capsys.readouterr().err


def test_the_outcome_must_be_one_the_simulator_knows():
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["simulate-payment", "--order-id", "x", "--outcome", "paid"])
    assert parser.parse_args(["simulate-payment", "--order-id", "x", "--outcome", "succeeded"]).outcome == "succeeded"


class Crash(BaseException):
    pass


def test_an_event_stored_and_never_applied_is_applied_by_the_reconciliation(
    db: Session, order: Order, payment: Payment, monkeypatch
):
    real = PaymentService.apply
    monkeypatch.setattr(PaymentService, "apply", lambda self, event_id: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        cli.simulate_payment(db, order_id=order.id, outcome="succeeded")
    monkeypatch.setattr(PaymentService, "apply", real)
    db.rollback()
    (stuck,) = events(db)
    assert stuck.processing_status == "RECEIVED"

    assert cli.reconcile_payment_events(db, older_than_minutes=5) == {}, "a recent event may be applying right now"
    assert reload(db, payment).status == "OPEN"

    db.execute(
        update(PaymentEvent).values(received_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=30))
    )
    db.commit()
    applied = cli.reconcile_payment_events(db, older_than_minutes=5)

    assert applied == {"applied": 1}
    assert reload(db, payment).status == "SUCCEEDED" and fresh_order_status(db, order) == "PAID"
    assert cli.reconcile_payment_events(db, older_than_minutes=5) == {}, "nothing is applied twice"


def test_the_reconciliation_needs_a_sensible_threshold(db: Session):
    with pytest.raises(ValidationError):
        cli.reconcile_payment_events(db, older_than_minutes=0)
