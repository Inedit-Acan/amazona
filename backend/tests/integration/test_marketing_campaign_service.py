import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.marketing_campaign import MarketingCampaign
from app.db.models.marketplace_listing import MarketplaceListing
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.marketing.service import MarketingCampaignService


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


def _make_product(db_session: Session, category: str = "home") -> Product:
    product = Product(name="Silicone kitchen organizer", category=category, created_by="owner@amazona.local")
    db_session.add(product)
    db_session.commit()
    return product


def _make_full_chain(db_session: Session, product: Product, market: str = "us") -> None:
    db_session.add(
        ProductAnalysis(
            product_id=product.id,
            analysis_type="research",
            opportunity_score=0.6,
            confidence=0.85,
            data={"demand_signal": 0.6, "competition_level": "low"},
            correlation_id="corr-research-1",
        )
    )
    supplier = Supplier(name="Kitchen Co", verified=True, region="china", reliability_score=0.9)
    db_session.add(supplier)
    db_session.commit()

    quote = SupplierQuote(
        product_id=product.id,
        supplier_id=supplier.id,
        unit_price=2.1,
        moq=1000,
        lead_time_days=30,
        verified=True,
        reliability_score=0.9,
        logistics_cost_per_unit=0.5,
        total_landed_cost_per_unit=2.6,
        correlation_id="corr-sourcing-1",
    )
    db_session.add(quote)
    db_session.commit()

    db_session.add(
        EconomicAnalysis(
            product_id=product.id,
            supplier_quote_id=quote.id,
            sale_price=50.0,
            monthly_fixed_costs=500.0,
            margin_percent=0.948,
            recommendation="GO",
            confidence=0.85,
            data={"scenarios": {}},
            correlation_id="corr-econ-1",
        )
    )
    db_session.add(
        LegalAnalysis(
            product_id=product.id,
            supplier_quote_id=quote.id,
            market=market,
            restricted=False,
            recommendation="GO",
            confidence=0.85,
            data={"required_certifications": []},
            correlation_id="corr-legal-1",
        )
    )
    db_session.add(
        MarketplaceListing(
            product_id=product.id,
            storefront_id=None,
            market=market,
            platform="amazon",
            listing_status="READY",
            recommendation="GO",
            confidence=0.85,
            data={},
            correlation_id="corr-mkt-1",
        )
    )
    db_session.commit()


def test_run_generation_uses_real_data_from_all_six_prior_agents(db_session: Session):
    product = _make_product(db_session)
    _make_full_chain(db_session, product, market="us")
    service = MarketingCampaignService(db_session)

    campaign = service.run_generation(
        product_id=product.id, market="us", platform="google", correlation_id="corr-mktg-1"
    )

    assert campaign.campaign_status == "READY"
    assert campaign.marketplace_listing_id is not None
    assert campaign.data["performance_estimate"]["projected_roas"] is not None


def test_run_generation_uses_the_legal_data_for_the_requested_market_only(db_session: Session):
    product = _make_product(db_session)
    _make_full_chain(db_session, product, market="us")
    db_session.add(
        LegalAnalysis(
            product_id=product.id,
            supplier_quote_id=None,
            market="eu",
            restricted=True,
            recommendation="NO_GO",
            confidence=0.95,
            data={"required_certifications": ["REACH"]},
            correlation_id="corr-legal-2",
        )
    )
    db_session.commit()
    service = MarketingCampaignService(db_session)

    campaign = service.run_generation(
        product_id=product.id, market="us", platform="google", correlation_id="corr-mktg-2"
    )

    assert campaign.campaign_status == "READY"


def test_run_generation_without_any_prior_agent_data_needs_review(db_session: Session):
    product = _make_product(db_session)
    service = MarketingCampaignService(db_session)

    campaign = service.run_generation(
        product_id=product.id, market="us", platform="google", correlation_id="corr-mktg-3"
    )

    assert campaign.campaign_status == "NEEDS_REVIEW"
    assert campaign.marketplace_listing_id is None


def test_run_generation_raises_not_found_for_an_unknown_product(db_session: Session):
    service = MarketingCampaignService(db_session)

    with pytest.raises(NotFoundError):
        service.run_generation(
            product_id=new_id(), market="us", platform="google", correlation_id="corr-mktg-4"
        )


def test_run_generation_audits_the_run(db_session: Session):
    product = _make_product(db_session)
    service = MarketingCampaignService(db_session)

    service.run_generation(product_id=product.id, market="us", platform="google", correlation_id="corr-mktg-5")

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-mktg-5").all()
    assert any(e.action == "marketing.run" for e in entries)


def test_run_generation_persists_a_reconstructable_row(db_session: Session):
    product = _make_product(db_session)
    service = MarketingCampaignService(db_session)

    campaign = service.run_generation(
        product_id=product.id, market="us", platform="google", correlation_id="corr-mktg-6"
    )

    persisted = db_session.get(MarketingCampaign, campaign.id)
    assert persisted is not None
    assert persisted.correlation_id == "corr-mktg-6"
