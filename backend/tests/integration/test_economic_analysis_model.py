import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.economic_analysis import EconomicAnalysis
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


def _make_product_and_quote(db_session: Session) -> tuple[Product, SupplierQuote]:
    product = Product(name="Wireless earbuds", category="electronics", created_by="owner@amazona.local")
    db_session.add(product)
    supplier = Supplier(name="Shenzhen Volta Electronics", verified=True, region="china", reliability_score=0.88)
    db_session.add(supplier)
    db_session.commit()

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
        correlation_id="corr-sourcing-1",
    )
    db_session.add(quote)
    db_session.commit()
    return product, quote


def test_economic_analysis_can_be_persisted_with_a_valid_product_and_quote(db_session: Session):
    product, quote = _make_product_and_quote(db_session)

    analysis = EconomicAnalysis(
        product_id=product.id,
        supplier_quote_id=quote.id,
        sale_price=20.0,
        monthly_fixed_costs=500.0,
        margin_percent=0.75,
        recommendation="GO",
        confidence=0.85,
        data={"scenarios": {}},
        correlation_id="corr-econ-1",
    )
    db_session.add(analysis)
    db_session.commit()

    persisted = db_session.get(EconomicAnalysis, analysis.id)
    assert persisted.analysis_type == "economic_risk"
    assert persisted.product_id == product.id
    assert persisted.supplier_quote_id == quote.id
    assert persisted.recommendation == "GO"


def test_economic_analysis_requires_a_valid_product_id(db_session: Session):
    _, quote = _make_product_and_quote(db_session)

    analysis = EconomicAnalysis(
        product_id=new_id(),  # does not exist
        supplier_quote_id=quote.id,
        sale_price=20.0,
        monthly_fixed_costs=500.0,
        margin_percent=0.75,
        recommendation="GO",
        confidence=0.85,
        correlation_id="corr-econ-2",
    )
    db_session.add(analysis)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_economic_analysis_requires_a_valid_supplier_quote_id(db_session: Session):
    product, _ = _make_product_and_quote(db_session)

    analysis = EconomicAnalysis(
        product_id=product.id,
        supplier_quote_id=new_id(),  # does not exist
        sale_price=20.0,
        monthly_fixed_costs=500.0,
        margin_percent=0.75,
        recommendation="GO",
        confidence=0.85,
        correlation_id="corr-econ-3",
    )
    db_session.add(analysis)

    with pytest.raises(IntegrityError):
        db_session.commit()
