import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.economics.service import EconomicAnalysisService


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


def _make_product(db_session: Session, name: str = "Wireless earbuds") -> Product:
    product = Product(name=name, category="electronics", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def _make_research_analysis(db_session: Session, product: Product, demand_signal: float = 0.65) -> ProductAnalysis:
    analysis = ProductAnalysis(
        product_id=product.id,
        analysis_type="research",
        opportunity_score=0.6,
        confidence=0.85,
        data={"demand_signal": demand_signal, "competition_level": "low"},
        correlation_id="corr-research-1",
    )
    db_session.add(analysis)
    db_session.commit()
    return analysis


def _make_supplier_quote(db_session: Session, product: Product) -> SupplierQuote:
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
    return quote


def test_run_analysis_uses_real_research_and_sourcing_data(db_session: Session):
    product = _make_product(db_session)
    _make_research_analysis(db_session, product, demand_signal=0.65)
    quote = _make_supplier_quote(db_session, product)
    service = EconomicAnalysisService(db_session)

    analysis = service.run_analysis(
        product_id=product.id,
        supplier_quote_id=quote.id,
        sale_price=20.0,
        correlation_id="corr-econ-1",
    )

    assert analysis.product_id == product.id
    assert analysis.supplier_quote_id == quote.id
    assert analysis.analysis_type == "economic_risk"
    # margin_percent derives from the real landed cost (5.22), not a default.
    assert analysis.margin_percent == pytest.approx((20.0 - 5.22) / 20.0)
    assert analysis.data["scenarios"]["base"]["monthly_unit_sales"] > 0


def test_run_analysis_raises_not_found_for_an_unknown_product(db_session: Session):
    quote_owner = _make_product(db_session)
    quote = _make_supplier_quote(db_session, quote_owner)
    service = EconomicAnalysisService(db_session)

    with pytest.raises(NotFoundError):
        service.run_analysis(
            product_id=new_id(),
            supplier_quote_id=quote.id,
            sale_price=20.0,
            correlation_id="corr-econ-2",
        )


def test_run_analysis_raises_not_found_for_an_unknown_supplier_quote(db_session: Session):
    product = _make_product(db_session)
    service = EconomicAnalysisService(db_session)

    with pytest.raises(NotFoundError):
        service.run_analysis(
            product_id=product.id,
            supplier_quote_id=new_id(),
            sale_price=20.0,
            correlation_id="corr-econ-3",
        )


def test_run_analysis_raises_not_found_when_quote_belongs_to_a_different_product(db_session: Session):
    product_a = _make_product(db_session, name="Product A")
    product_b = _make_product(db_session, name="Product B")
    quote_for_b = _make_supplier_quote(db_session, product_b)
    service = EconomicAnalysisService(db_session)

    with pytest.raises(NotFoundError):
        service.run_analysis(
            product_id=product_a.id,
            supplier_quote_id=quote_for_b.id,
            sale_price=20.0,
            correlation_id="corr-econ-4",
        )


def test_run_analysis_audits_the_run(db_session: Session):
    product = _make_product(db_session)
    quote = _make_supplier_quote(db_session, product)
    service = EconomicAnalysisService(db_session)

    service.run_analysis(
        product_id=product.id,
        supplier_quote_id=quote.id,
        sale_price=20.0,
        monthly_unit_sales_base=300.0,
        correlation_id="corr-econ-5",
    )

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-econ-5").all()
    assert any(e.action == "economics.run" for e in entries)


def test_run_analysis_persists_a_reconstructable_row(db_session: Session):
    product = _make_product(db_session)
    quote = _make_supplier_quote(db_session, product)
    service = EconomicAnalysisService(db_session)

    analysis = service.run_analysis(
        product_id=product.id,
        supplier_quote_id=quote.id,
        sale_price=20.0,
        monthly_unit_sales_base=300.0,
        correlation_id="corr-econ-6",
    )

    persisted = db_session.get(EconomicAnalysis, analysis.id)
    assert persisted is not None
    assert persisted.correlation_id == "corr-econ-6"
