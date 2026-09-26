"""Semántica de orquestación del pipeline (Milestone 12/14, ADR 0005 y 0006).

Desde el Milestone 32 la ejecución vive en un trabajo del runtime, así que aquí se
encola y se ejecuta en el acto (`enqueue_run` + `execute_run`) sin pasar por un
worker: lo que estas pruebas protegen es **qué hace la cadena** —el orden, la
selección de candidato, que un NO_GO no la detenga—, no el ciclo de reclamo y
reintento, que es lo que cubre `test_pipeline_async_execution.py`.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.cfo_report import CFOReport
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep
from app.db.models.storefront import Storefront
from app.pipeline.service import PipelineOrchestrator, PipelineRequest, steps_view


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


def run_now(orchestrator: PipelineOrchestrator, db: Session, request: PipelineRequest) -> PipelineRun:
    """Encola y ejecuta en el acto, para poder afirmar sobre el resultado en una
    sola línea como antes de que el pipeline fuese asíncrono."""
    run = orchestrator.enqueue_run(request)
    return orchestrator.execute_run(run.id)


def view(db: Session, run: PipelineRun) -> dict[str, dict]:
    """Los pasos tal y como los devuelve la API, reconstruidos de sus filas."""
    return steps_view(db.query(PipelineStep).filter_by(pipeline_run_id=run.id).all())


def executed(db: Session, run: PipelineRun) -> dict[str, dict]:
    """Solo los pasos que llegaron a ejecutarse — el JSON `steps` de antes del
    Milestone 32 no contenía los demás."""
    return {name: step for name, step in view(db, run).items() if step["step_status"] != "SKIPPED"}


def test_healthy_category_completes_all_nine_steps(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    run = run_now(orchestrator, db_session, request)

    assert run.status == "COMPLETED"
    assert run.failed_step is None
    assert run.product_id is not None
    steps = view(db_session, run)
    assert set(steps.keys()) == {
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
    correlation_ids = {run.correlation_id} | {step["correlation_id"] for step in steps.values()}
    assert len(correlation_ids) == 10


def test_a_no_go_does_not_stop_analysis_but_does_stop_acting(db_session: Session):
    """Milestone 33 (ADR 0011) matiza la ADR 0005: la cadena sigue sin detenerse
    **para analizar**, y deja de seguir **para actuar**. Con economics en NO_GO
    los pasos de análisis terminan y el primero con efecto se para delante del
    gate."""
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=0.5, destination_region="mexico")

    run = run_now(orchestrator, db_session, request)

    steps = view(db_session, run)
    assert steps["economics"]["recommendation"] == "NO_GO"
    # El análisis entero se completó: research, sourcing, economics y legal.
    for name in ("research", "sourcing", "economics", "legal"):
        assert steps[name]["step_status"] == "COMPLETED", name
    # Y la primera acción con efecto no se ejecutó.
    assert run.status == "WAITING_APPROVAL"
    assert steps["ecommerce"]["step_status"] == "WAITING_APPROVAL"
    assert steps["cfo"]["step_status"] == "PENDING"


def test_unknown_category_with_no_research_candidates_is_partial(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="does-not-exist", sale_price=50.0, destination_region="mexico")

    run = run_now(orchestrator, db_session, request)

    assert run.status == "PARTIAL"
    assert run.failed_step == "research"
    assert run.product_id is None
    assert "sourcing" not in executed(db_session, run)


def test_picks_the_highest_opportunity_score_candidate(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="electronics", sale_price=50.0, destination_region="mexico")

    run = run_now(orchestrator, db_session, request)

    # "Smart water bottle" has the highest opportunity_score in the
    # electronics fixture: 0.65 demand * 1.0 low-competition factor = 0.65,
    # beating "Wireless earbuds pro" at 0.82 * 0.6 (medium) = 0.492.
    from app.db.models.product import Product

    product = db_session.get(Product, run.product_id)
    assert product.name == "Smart water bottle"


def test_cfo_report_reflects_the_product_this_pipeline_run_created(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    run = run_now(orchestrator, db_session, request)

    cfo_report_id = view(db_session, run)["cfo"]["entity_id"]
    cfo_report = db_session.get(CFOReport, cfo_report_id)
    assert cfo_report.data["total_products_analyzed"] == 1


def test_two_runs_for_the_same_category_never_collide_on_store_slug(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    first_run = run_now(orchestrator, db_session, request)
    second_run = run_now(orchestrator, db_session, request)

    # Both runs pick the same top-ranked mock candidate ("Silicone kitchen
    # organizer") since research creates a fresh Product every time — the
    # slug must still differ because it identifies the real product.
    first_storefront = db_session.get(Storefront, view(db_session, first_run)["ecommerce"]["entity_id"])
    second_storefront = db_session.get(Storefront, view(db_session, second_run)["ecommerce"]["entity_id"])
    assert first_storefront.store_slug != second_storefront.store_slug


def test_enqueueing_raises_when_the_kill_switch_is_disabled(db_session: Session):
    from app.core.errors import PipelineDisabledError
    from app.db.models.product import Product
    from app.pipeline.kill_switch import PipelineKillSwitchService

    kill_switch = PipelineKillSwitchService(db_session)
    kill_switch.disable(reason="incident", actor="ops@amazona.local", correlation_id="corr-disable")
    orchestrator = PipelineOrchestrator(db_session, kill_switch=kill_switch)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico")

    with pytest.raises(PipelineDisabledError):
        orchestrator.enqueue_run(request)

    assert db_session.query(Product).count() == 0
    assert db_session.query(PipelineRun).count() == 0
