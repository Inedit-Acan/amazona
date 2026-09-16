import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote


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
    product = Product(name="Wireless earbuds", category="electronics", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def _make_supplier(db_session: Session) -> Supplier:
    supplier = Supplier(name="Shenzhen Volta Electronics", verified=True, region="china", reliability_score=0.88)
    db_session.add(supplier)
    db_session.commit()
    return supplier


def test_supplier_quote_can_be_persisted_with_a_valid_product_and_supplier(db_session: Session):
    product = _make_product(db_session)
    supplier = _make_supplier(db_session)

    quote = SupplierQuote(
        product_id=product.id,
        supplier_id=supplier.id,
        unit_price=4.2,
        moq=500,
        lead_time_days=25,
        verified=True,
        reliability_score=0.88,
        logistics_cost_per_unit=1.02,
        total_landed_cost_per_unit=5.22,
        data={"region": "china"},
        correlation_id="corr-1",
    )
    db_session.add(quote)
    db_session.commit()

    persisted = db_session.get(SupplierQuote, quote.id)
    assert persisted.analysis_type == "sourcing"
    assert persisted.product_id == product.id
    assert persisted.supplier_id == supplier.id
    assert persisted.total_landed_cost_per_unit == 5.22


def test_supplier_quote_requires_a_valid_product_id(db_session: Session):
    supplier = _make_supplier(db_session)

    quote = SupplierQuote(
        product_id=new_id(),  # does not exist
        supplier_id=supplier.id,
        unit_price=4.2,
        moq=500,
        lead_time_days=25,
        verified=True,
        reliability_score=0.88,
        logistics_cost_per_unit=1.02,
        total_landed_cost_per_unit=5.22,
        correlation_id="corr-1",
    )
    db_session.add(quote)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_supplier_quote_requires_a_valid_supplier_id(db_session: Session):
    product = _make_product(db_session)

    quote = SupplierQuote(
        product_id=product.id,
        supplier_id=new_id(),  # does not exist
        unit_price=4.2,
        moq=500,
        lead_time_days=25,
        verified=True,
        reliability_score=0.88,
        logistics_cost_per_unit=1.02,
        total_landed_cost_per_unit=5.22,
        correlation_id="corr-1",
    )
    db_session.add(quote)

    with pytest.raises(IntegrityError):
        db_session.commit()
