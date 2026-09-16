import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier import Supplier


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


def test_product_can_be_persisted_with_defaults(db_session: Session):
    product = Product(name="Wireless earbuds", category="electronics", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()

    persisted = db_session.get(Product, product.id)
    assert persisted.status == "CANDIDATE"
    assert persisted.source == "manual"


def test_supplier_can_be_persisted(db_session: Session):
    supplier = Supplier(name="Acme Supplies", verified=True, region="EU", reliability_score=0.9)
    db_session.add(supplier)
    db_session.commit()

    persisted = db_session.get(Supplier, supplier.id)
    assert persisted.verified is True
    assert persisted.reliability_score == 0.9


def test_product_analysis_requires_a_valid_product_id(db_session: Session):
    analysis = ProductAnalysis(
        product_id=new_id(),  # does not exist
        analysis_type="research",
        opportunity_score=0.8,
        confidence=0.7,
        data={"demand_signal": 0.6},
    )
    db_session.add(analysis)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_product_analysis_links_to_an_existing_product(db_session: Session):
    product = Product(name="Phone case", category="accessories", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()

    analysis = ProductAnalysis(
        product_id=product.id,
        analysis_type="research",
        opportunity_score=0.65,
        confidence=0.8,
        data={"demand_signal": 0.7},
    )
    db_session.add(analysis)
    db_session.commit()

    persisted = db_session.get(ProductAnalysis, analysis.id)
    assert persisted.product_id == product.id
    assert persisted.objective_id is None
    assert persisted.data["demand_signal"] == 0.7
