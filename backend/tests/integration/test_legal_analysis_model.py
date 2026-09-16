import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.ids import new_id
from app.db.base import Base
from app.db.models.legal_analysis import LegalAnalysis
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
    product = Product(name="Wireless earbuds", category="electronics", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def test_legal_analysis_can_be_persisted_without_a_supplier_quote(db_session: Session):
    product = _make_product(db_session)

    analysis = LegalAnalysis(
        product_id=product.id,
        supplier_quote_id=None,
        market="eu",
        restricted=False,
        recommendation="GO",
        confidence=0.85,
        data={"required_certifications": ["CE", "RoHS"]},
        correlation_id="corr-legal-1",
    )
    db_session.add(analysis)
    db_session.commit()

    persisted = db_session.get(LegalAnalysis, analysis.id)
    assert persisted.analysis_type == "legal_compliance"
    assert persisted.supplier_quote_id is None
    assert persisted.market == "eu"


def test_legal_analysis_requires_a_valid_product_id(db_session: Session):
    analysis = LegalAnalysis(
        product_id=new_id(),  # does not exist
        market="eu",
        restricted=False,
        recommendation="GO",
        confidence=0.85,
        correlation_id="corr-legal-2",
    )
    db_session.add(analysis)

    with pytest.raises(IntegrityError):
        db_session.commit()
