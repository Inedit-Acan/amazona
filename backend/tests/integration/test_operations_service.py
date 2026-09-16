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
from app.db.models.operations_record import OperationsRecord
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.operations.service import OperationsService


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
        MarketingCampaign(
            product_id=product.id,
            marketplace_listing_id=None,
            market=market,
            platform="google",
            daily_budget=20.0,
            campaign_status="READY",
            recommendation="GO",
            confidence=0.85,
            data={},
            correlation_id="corr-mktg-1",
        )
    )
    db_session.commit()


def test_run_generation_uses_real_data_from_all_seven_prior_agents(db_session: Session):
    product = _make_product(db_session)
    _make_full_chain(db_session, product, market="us")
    service = OperationsService(db_session)

    record = service.run_generation(product_id=product.id, market="us", correlation_id="corr-ops-1")

    assert record.operations_status == "READY"
    assert record.marketing_campaign_id is not None
    assert record.data["order"]["tracking"]["lead_time_days_used"] == 30
    assert record.data["return_policy"]["refund_estimate"] is not None


def test_run_generation_uses_the_legal_and_campaign_data_for_the_requested_market_only(db_session: Session):
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
    service = OperationsService(db_session)

    record = service.run_generation(product_id=product.id, market="us", correlation_id="corr-ops-2")

    assert record.operations_status == "READY"


def test_run_generation_without_any_prior_agent_data_needs_review(db_session: Session):
    product = _make_product(db_session)
    service = OperationsService(db_session)

    record = service.run_generation(product_id=product.id, market="us", correlation_id="corr-ops-3")

    assert record.operations_status == "NEEDS_REVIEW"
    assert record.marketing_campaign_id is None


def test_run_generation_raises_not_found_for_an_unknown_product(db_session: Session):
    service = OperationsService(db_session)

    with pytest.raises(NotFoundError):
        service.run_generation(product_id=new_id(), market="us", correlation_id="corr-ops-4")


def test_run_generation_audits_the_run(db_session: Session):
    product = _make_product(db_session)
    service = OperationsService(db_session)

    service.run_generation(product_id=product.id, market="us", correlation_id="corr-ops-5")

    entries = db_session.query(AuditLog).filter_by(correlation_id="corr-ops-5").all()
    assert any(e.action == "operations.run" for e in entries)


def test_run_generation_persists_a_reconstructable_row(db_session: Session):
    product = _make_product(db_session)
    service = OperationsService(db_session)

    record = service.run_generation(product_id=product.id, market="us", correlation_id="corr-ops-6")

    persisted = db_session.get(OperationsRecord, record.id)
    assert persisted is not None
    assert persisted.correlation_id == "corr-ops-6"
