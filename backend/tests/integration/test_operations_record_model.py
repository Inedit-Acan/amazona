import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.operations_record import OperationsRecord
from app.db.models.product import Product


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_product(db_session: Session) -> Product:
    product = Product(name="Silicone kitchen organizer", category="home", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def test_operations_record_can_be_persisted_without_a_marketing_campaign(db_session: Session):
    product = _make_product(db_session)

    record = OperationsRecord(
        product_id=product.id,
        marketing_campaign_id=None,
        market="us",
        operations_status="READY",
        recommendation="GO",
        confidence=0.85,
        data={"order": {}},
        correlation_id="corr-ops-1",
    )
    db_session.add(record)
    db_session.commit()

    persisted = db_session.get(OperationsRecord, record.id)
    assert persisted.operations_status == "READY"
    assert persisted.marketing_campaign_id is None


def test_operations_record_requires_a_valid_product_id(db_session: Session):
    record = OperationsRecord(
        product_id=new_id(),  # does not exist
        market="us",
        operations_status="READY",
        recommendation="GO",
        confidence=0.85,
        correlation_id="corr-ops-2",
    )
    db_session.add(record)

    with pytest.raises(IntegrityError):
        db_session.commit()
