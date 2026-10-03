"""Apoyo compartido de las pruebas de la reconciliación programada (Milestone 45, ADR 0029).

Módulo auxiliar de tests, **no** un test. Pone en el estado que se quiera —con la edad que se quiera— una acción
externa, un cobro o un evento
de pago, sobre SQLite y sobre un PostgreSQL de verdad (donde viven las carreras, los bloqueos y los compare-and-set),
y ofrece los mandos para
medir sin esperar: el tiempo no se espera, se **envejece** la fila.

Ningún test sale de la máquina (la guarda de `conftest.py` lo hace cumplir): los proveedores son dobles que cuentan
sus efectos.
"""

import datetime
from collections.abc import Iterator
from decimal import Decimal

import pytest
from action_test_support import FakeProviderAdapter
from order_test_support import make_engine, session_factory
from pg_test_support import ephemeral_postgres
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.actions.contract import ActionStatus
from app.actions.service import ExternalActionService
from app.budgets.service import BudgetLedgerService
from app.db.models.external_action import ExternalAction
from app.db.models.payment import PaymentEvent

OWNER = "owner@amazona.local"
NOW = datetime.datetime(2026, 10, 3, 12, 0, tzinfo=datetime.UTC)


def ago(**delta) -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) - datetime.timedelta(**delta)


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request) -> Iterator:
    if request.param == "sqlite":
        built = make_engine()
        try:
            yield built
        finally:
            built.dispose()
    else:
        with ephemeral_postgres() as built:
            yield built


@pytest.fixture()
def factory(engine) -> sessionmaker:
    return session_factory(engine)


@pytest.fixture()
def db(factory) -> Iterator[Session]:
    with factory() as session:
        yield session


def authorise_budget(db: Session, hard_limit: float = 1_000.0) -> None:
    BudgetLedgerService(db).authorise_budget(hard_limit=hard_limit, actor=OWNER)
    db.commit()


def outstanding(db: Session, action: ExternalAction) -> Decimal:
    db.expire_all()
    return BudgetLedgerService(db).outstanding(action.reservation_reference)


def make_action(
    db: Session,
    *,
    state: str = "PENDING",
    reference: str = "pipeline_step:run-1:marketing",
    operation: str = "activate_ads",
    amount: float | None = 40.0,
    adapter: FakeProviderAdapter | None = None,
) -> ExternalAction:
    """Una acción en el estado pedido (`PENDING`, `CALLING` o `UNKNOWN_OUTCOME`), con su reserva si gasta, creada por
    el servicio real
    (la misma frontera de durabilidad que en producción)."""
    adapter = adapter or FakeProviderAdapter()
    service = ExternalActionService(db)
    action = service.open(
        reference=reference,
        adapter=adapter,
        operation=operation,
        amount=amount,
        payload={"k": reference},
        correlation_id=f"corr-{reference}",
    )
    if amount:
        assert service.reserve(action), "the test budget must cover the reservation"
    db.commit()
    if state == "PENDING":
        return action
    service.begin_call(action)
    if state == "UNKNOWN_OUTCOME":
        service.finish(action, ActionStatus.UNKNOWN_OUTCOME, error="the response was lost")
    return action


def age_action(
    db: Session,
    action: ExternalAction,
    *,
    updated: datetime.datetime | None = None,
    call_started: datetime.datetime | None = None,
    created: datetime.datetime | None = None,
) -> None:
    """Envejece la fila: el tiempo no se espera."""
    values = {}
    if updated is not None:
        values["updated_at"] = updated
    if call_started is not None:
        values["call_started_at"] = call_started
    if created is not None:
        values["created_at"] = created
    db.execute(update(ExternalAction).where(ExternalAction.id == action.id).values(**values))
    db.commit()
    db.expire_all()


def status_of(db: Session, action: ExternalAction) -> str:
    db.expire_all()
    return db.scalars(select(ExternalAction.status).where(ExternalAction.id == action.id)).one()


def stored_event(
    db: Session,
    *,
    event_id: str = "evt-1",
    received_ago: datetime.timedelta = datetime.timedelta(minutes=30),
    status: str = "RECEIVED",
    attempts: int = 0,
    payment_ref: str | None = None,
    client_reference: str | None = None,
    amount: str | None = None,
    event_type: str = "payment.succeeded",
) -> PaymentEvent:
    """Un `PaymentEvent` ya guardado, sin pasar por la puerta (el proceso «cayó» antes de aplicarlo)."""
    received = datetime.datetime.now(datetime.UTC) - received_ago
    event = PaymentEvent(
        provider="simulated-payments",
        provider_event_id=event_id,
        event_type=event_type,
        provider_payment_ref=payment_ref,
        client_reference=client_reference,
        amount=Decimal(amount) if amount is not None else None,
        currency="EUR" if amount is not None else None,
        occurred_at=received,
        received_at=received,
        payload_hash=f"hash-{event_id}",
        data={"failure_code": None},
        processing_status=status,
        reconcile_attempts=attempts,
    )
    db.add(event)
    db.commit()
    return event


def event_row(db: Session, event_id: str) -> PaymentEvent:
    db.expire_all()
    return db.scalars(select(PaymentEvent).where(PaymentEvent.provider_event_id == event_id)).one()
