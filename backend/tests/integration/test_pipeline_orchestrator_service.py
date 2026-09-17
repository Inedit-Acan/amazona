import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.cfo_report import CFOReport
from app.db.models.storefront import Storefront
from app.pipeline.service import PipelineOrchestrator, PipelineRequest


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


def test_healthy_category_completes_all_nine_steps(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.status == "COMPLETED"
    assert run.failed_step is None
    assert run.product_id is not None
    assert set(run.steps.keys()) == {
        "research",
        "sourcing",
        "economics",
        "legal",
        "ecommerce",
        "marketplace",
        "marketing",
        "operations",
        "cfo",
    }
    # every step got its own distinct correlation_id, plus the pipeline's own.
    correlation_ids = {run.correlation_id} | {step["correlation_id"] for step in run.steps.values()}
    assert len(correlation_ids) == 10


def test_low_sale_price_produces_a_no_go_economics_step_but_the_pipeline_keeps_going(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=0.5, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.status == "COMPLETED"
    assert run.steps["economics"]["recommendation"] == "NO_GO"
    # downstream steps still ran despite the NO_GO — no auto-halt (ADR 0005).
    assert "operations" in run.steps
    assert "cfo" in run.steps


def test_unknown_category_with_no_research_candidates_is_partial(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="does-not-exist", sale_price=50.0, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.status == "PARTIAL"
    assert run.failed_step == "research"
    assert run.product_id is None
    assert "sourcing" not in run.steps


def test_picks_the_highest_opportunity_score_candidate(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="electronics", sale_price=50.0, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    # "Smart water bottle" has the highest opportunity_score in the
    # electronics fixture: 0.65 demand * 1.0 low-competition factor = 0.65,
    # beating "Wireless earbuds pro" at 0.82 * 0.6 (medium) = 0.492.
    from app.db.models.product import Product

    product = db_session.get(Product, run.product_id)
    assert product.name == "Smart water bottle"


def test_cfo_report_reflects_the_product_this_pipeline_run_created(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    cfo_report_id = run.steps["cfo"]["entity_id"]
    cfo_report = db_session.get(CFOReport, cfo_report_id)
    assert cfo_report.data["total_products_analyzed"] == 1


def test_two_runs_for_the_same_category_never_collide_on_store_slug(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    first_run = orchestrator.run_pipeline(request)
    second_run = orchestrator.run_pipeline(request)

    # Both runs pick the same top-ranked mock candidate ("Silicone kitchen
    # organizer") since research creates a fresh Product every time — the
    # slug must still differ because it identifies the real product.
    first_storefront = db_session.get(Storefront, first_run.steps["ecommerce"]["entity_id"])
    second_storefront = db_session.get(Storefront, second_run.steps["ecommerce"]["entity_id"])
    assert first_storefront.store_slug != second_storefront.store_slug


def test_run_pipeline_raises_when_the_kill_switch_is_disabled(db_session: Session):
    from app.core.errors import PipelineDisabledError
    from app.db.models.product import Product
    from app.pipeline.kill_switch import PipelineKillSwitchService

    kill_switch = PipelineKillSwitchService(db_session)
    kill_switch.disable(reason="incident", actor="ops@amazona.local", correlation_id="corr-disable")
    orchestrator = PipelineOrchestrator(db_session, kill_switch=kill_switch)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    with pytest.raises(PipelineDisabledError):
        orchestrator.run_pipeline(request)

    assert db_session.query(Product).count() == 0
