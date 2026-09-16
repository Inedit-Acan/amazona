import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.legal.service import LegalComplianceService


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_product(db_session: Session, category: str = "accessories") -> Product:
    product = Product(name="Leather phone strap", category=category, created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def _make_supplier_quote(db_session: Session, product: Product, verified: bool = False) -> SupplierQuote:
    supplier = Supplier(name="Yiwu Accessory Hub", verified=verified, region="china", reliability_score=0.7)
    db_session.add(supplier)
    db_session.commit()

    quote = SupplierQuote(
        product_id=product.id,
        supplier_id=supplier.id,
        unit_price=1.3,
        moq=1500,
        lead_time_days=28,
        verified=verified,
        reliability_score=0.7,
        logistics_cost_per_unit=0.4,
        total_landed_cost_per_unit=1.7,
        correlation_id="corr-sourcing-1",
    )
    db_session.add(quote)
    db_session.commit()
    return quote


def test_run_analysis_uses_the_products_real_category(db_session: Session):
    product = _make_product(db_session, category="accessories")
    service = LegalComplianceService(db_session)

    analysis = service.run_analysis(
        product_id=product.id, market="eu", correlation_id="corr-legal-1"
    )

    # accessories/eu fixture is restricted with REACH required.
    assert analysis.restricted is True
    assert "REACH" in analysis.data["required_certifications"]


def test_run_analysis_uses_real_sourcing_data_when_available(db_session: Session):
    product = _make_product(db_session, category="accessories")
    _make_supplier_quote(db_session, product, verified=False)
    service = LegalComplianceService(db_session)

    analysis = service.run_analysis(
        product_id=product.id, market="us", correlation_id="corr-legal-2"
    )

    assert any("cross-border" in risk for risk in analysis.data["risks"])


def test_run_analysis_works_without_any_prior_sourcing_or_economics(db_session: Session):
    product = _make_product(db_session, category="home")
    service = LegalComplianceService(db_session)

    analysis = service.run_analysis(
        product_id=product.id, market="mx", correlation_id="corr-legal-3"
    )

    assert analysis.product_id == product.id
    assert analysis.recommendation in {"GO", "REVIEW", "NO_GO"}


def test_run_analysis_raises_not_found_for_an_unknown_product(db_session: Session):
    service = LegalComplianceService(db_session)

    with pytest.raises(NotFoundError):
        service.run_analysis(product_id=new_id(), market="eu", correlation_id="corr-legal-4")


def test_run_analysis_audits_the_run(db_session: Session):
    product = _make_product(db_session, category="home")
    service = LegalComplianceService(db_session)

    service.run_analysis(product_id=product.id, market="mx", correlation_id="corr-legal-5")

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-legal-5").all()
    assert any(e.action == "legal.run" for e in entries)


def test_run_analysis_persists_a_reconstructable_row(db_session: Session):
    product = _make_product(db_session, category="home")
    service = LegalComplianceService(db_session)

    analysis = service.run_analysis(product_id=product.id, market="mx", correlation_id="corr-legal-6")

    persisted = db_session.get(LegalAnalysis, analysis.id)
    assert persisted is not None
    assert persisted.correlation_id == "corr-legal-6"
    assert persisted.supplier_quote_id is None
