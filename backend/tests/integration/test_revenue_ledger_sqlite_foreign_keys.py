"""La herencia de un reembolso la hace cumplir la base también en SQLite, con las claves ajenas activas (ADR 0030 §14).

El motor SQLite de las demás pruebas no activa `PRAGMA foreign_keys`, así que la clave ajena **compuesta** que
obliga a un reembolso a heredar clasificación, moneda y cobro de su captura solo se ejercita en PostgreSQL. Aquí
se activa en SQLite y se comprueba que el rechazo es por esa restricción y por nada más: la misma fila, honesta,
sí entra.
"""

import pytest
from payment_test_support import deliver
from revenue_test_support import (
    SUCCEEDED,
    ScriptedPaymentProvider,
    capture_entry,
    confirm_refund,
    duplicate_pair,
    entries,
    new_order,
    refund_of,
)
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.payment import PaymentEvent
from app.db.models.revenue import RevenueLedgerEntry

COLUMNS = (
    "kind", "classification", "payment_event_id", "payment_id", "order_id", "refund_id", "capture_entry_id",
    "amount", "currency", "occurred_at", "recorded_at",
)  # fmt: skip


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


def clone(entry: RevenueLedgerEntry, **changes) -> RevenueLedgerEntry:
    values = {column: getattr(entry, column) for column in COLUMNS}
    values.update(changes)
    return RevenueLedgerEntry(**values)


def rejects(db: Session, entry: RevenueLedgerEntry) -> None:
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        db.add(entry)
        db.flush()
    db.rollback()


def test_a_refund_cannot_claim_another_classification_currency_or_payment_than_its_capture_in_sqlite(db: Session):
    provider = ScriptedPaymentProvider()
    canonical, duplicate = duplicate_pair(db, provider, new_order(db))
    confirm_refund(db, provider, refund_of(db, provider, duplicate, "20.00", reason="duplicate_capture"))
    ref = [e for e in entries(db) if e.kind == "REFUND"][0]
    assert ref.classification == "DUPLICATE_RECEIPT" and ref.capture_entry_id == capture_entry(db, duplicate).id
    deliver(db, provider, SUCCEEDED, duplicate, event_id="evt_spare")  # STALE: un id de evento libre
    spare = db.scalars(select(PaymentEvent).where(PaymentEvent.provider_event_id == "evt_spare")).one()
    second = refund_of(db, provider, duplicate, "10.00", reason="duplicate_capture")  # sin confirmar

    honest = clone(ref, id="honest", payment_event_id=spare.id, refund_id=second.id)
    rejects(db, clone(honest, id="x1", classification="ORDER_PAYMENT"))
    rejects(db, clone(honest, id="x2", currency="USD"))
    rejects(db, clone(honest, id="x3", payment_id=canonical.id))

    db.add(clone(honest, id="honest"))  # la misma fila, honesta, entra: el rechazo era por la herencia y por nada más
    db.flush()
    assert {e.id for e in entries(db)} >= {"honest"}
