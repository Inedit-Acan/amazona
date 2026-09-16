import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.cfo.service import CFOService
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation
from app.db.models.cfo_report import CFOReport
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.marketing_campaign import MarketingCampaign
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote


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


def _make_product(db_session: Session, name: str = "Product") -> Product:
    product = Product(name=name, category="home", created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def _make_quote(db_session: Session, product: Product) -> SupplierQuote:
    supplier = Supplier(name="Supplier Co", verified=True, region="china", reliability_score=0.9)
    db_session.add(supplier)
    db_session.commit()
    quote = SupplierQuote(
        product_id=product.id,
        supplier_id=supplier.id,
        unit_price=2.0,
        moq=500,
        lead_time_days=20,
        verified=True,
        reliability_score=0.9,
        logistics_cost_per_unit=0.4,
        total_landed_cost_per_unit=2.4,
        correlation_id="corr-sourcing-1",
    )
    db_session.add(quote)
    db_session.commit()
    return quote


def _make_economic_analysis(
    db_session: Session, product: Product, quote: SupplierQuote, recommendation: str, correlation_id: str
) -> EconomicAnalysis:
    analysis = EconomicAnalysis(
        product_id=product.id,
        supplier_quote_id=quote.id,
        sale_price=50.0,
        monthly_fixed_costs=500.0,
        margin_percent=0.9,
        recommendation=recommendation,
        confidence=0.85,
        data={"scenarios": {}},
        correlation_id=correlation_id,
    )
    db_session.add(analysis)
    db_session.commit()
    return analysis


def test_empty_catalog_needs_review(db_session: Session):
    service = CFOService(db_session)

    report = service.run_generation(correlation_id="corr-cfo-1")

    assert report.financial_health_status == "NEEDS_REVIEW"
    assert report.data["total_products_analyzed"] == 0


def test_healthy_mix_of_products_is_healthy(db_session: Session):
    product_a = _make_product(db_session, "A")
    product_b = _make_product(db_session, "B")
    quote_a = _make_quote(db_session, product_a)
    quote_b = _make_quote(db_session, product_b)
    _make_economic_analysis(db_session, product_a, quote_a, "GO", "corr-econ-a")
    _make_economic_analysis(db_session, product_b, quote_b, "GO", "corr-econ-b")
    service = CFOService(db_session)

    report = service.run_generation(correlation_id="corr-cfo-2")

    assert report.financial_health_status == "HEALTHY"
    assert report.data["total_products_analyzed"] == 2
    assert report.data["go_count"] == 2


def test_majority_no_go_across_catalog_is_critical(db_session: Session):
    product_a = _make_product(db_session, "A")
    product_b = _make_product(db_session, "B")
    product_c = _make_product(db_session, "C")
    for product, recommendation, corr in (
        (product_a, "NO_GO", "corr-econ-a"),
        (product_b, "NO_GO", "corr-econ-b"),
        (product_c, "GO", "corr-econ-c"),
    ):
        quote = _make_quote(db_session, product)
        _make_economic_analysis(db_session, product, quote, recommendation, corr)
    service = CFOService(db_session)

    report = service.run_generation(correlation_id="corr-cfo-3")

    assert report.financial_health_status == "CRITICAL"
    assert report.data["no_go_count"] == 2


def test_only_the_latest_economic_analysis_per_product_is_counted(db_session: Session):
    product = _make_product(db_session)
    quote = _make_quote(db_session, product)
    _make_economic_analysis(db_session, product, quote, "NO_GO", "corr-econ-old")
    _make_economic_analysis(db_session, product, quote, "GO", "corr-econ-new")
    service = CFOService(db_session)

    report = service.run_generation(correlation_id="corr-cfo-4")

    assert report.data["total_products_analyzed"] == 1
    assert report.data["go_count"] == 1
    assert report.data["no_go_count"] == 0


def test_aggregates_campaigns_and_budgets(db_session: Session):
    product = _make_product(db_session)
    quote = _make_quote(db_session, product)
    _make_economic_analysis(db_session, product, quote, "GO", "corr-econ-1")
    db_session.add(
        MarketingCampaign(
            product_id=product.id,
            market="us",
            platform="meta",
            daily_budget=25.0,
            campaign_status="READY",
            recommendation="GO",
            confidence=0.85,
            data={},
            correlation_id="corr-mktg-1",
        )
    )
    budget = Budget(name="Global", hard_limit=1000.0, soft_limit=800.0, period="monthly")
    db_session.add(budget)
    db_session.commit()
    db_session.add(BudgetAllocation(budget_id=budget.id, reserved=100.0, committed=50.0, spent=25.0))
    db_session.commit()
    service = CFOService(db_session)

    report = service.run_generation(correlation_id="corr-cfo-5")

    assert report.data["total_campaigns"] == 1
    assert report.data["active_campaigns"] == 1
    assert report.data["total_daily_budget"] == 25.0
    assert report.data["total_budget_hard_limit"] == 1000.0
    assert report.data["budget_utilization"] == pytest.approx(0.175)


def test_run_generation_audits_the_run(db_session: Session):
    service = CFOService(db_session)

    service.run_generation(correlation_id="corr-cfo-6")

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-cfo-6").all()
    assert any(e.action == "cfo.run" for e in entries)


def test_run_generation_persists_a_reconstructable_row(db_session: Session):
    service = CFOService(db_session)

    report = service.run_generation(correlation_id="corr-cfo-7")

    persisted = db_session.get(CFOReport, report.id)
    assert persisted is not None
    assert persisted.correlation_id == "corr-cfo-7"


def test_traceability_lists_the_included_analysis_and_campaign_ids(db_session: Session):
    product = _make_product(db_session)
    quote = _make_quote(db_session, product)
    analysis = _make_economic_analysis(db_session, product, quote, "GO", "corr-econ-1")
    campaign = MarketingCampaign(
        product_id=product.id,
        market="us",
        platform="meta",
        daily_budget=10.0,
        campaign_status="READY",
        recommendation="GO",
        confidence=0.85,
        data={},
        correlation_id="corr-mktg-1",
    )
    db_session.add(campaign)
    db_session.commit()
    service = CFOService(db_session)

    report = service.run_generation(correlation_id="corr-cfo-8")

    assert analysis.id in report.data["included_economic_analysis_ids"]
    assert campaign.id in report.data["included_marketing_campaign_ids"]
