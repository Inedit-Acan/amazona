"""Milestone 13 (IVA-31): formalizes the manual investigation sweep run
before this milestone (3 categories x 3 markets x several price points x
known/unknown destination regions, 0 unhandled exceptions, 0 unexpected
statuses) as a permanent regression test over the real combinatorial
space the system already supports.

Desde el Milestone 33 una ejecución puede acabar legítimamente parada delante
del ActionGate (`WAITING_APPROVAL`) en vez de `COMPLETED`: un `REVIEW` legal o
económico ya no se publica solo. Lo que el barrido sigue exigiendo es lo de
siempre —ninguna excepción sin tratar y ningún estado inesperado— más que el
análisis llegue entero hasta legal en todas las combinaciones."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.pipeline_run import PipelineRun
from app.db.models.pipeline_step import PipelineStep
from app.pipeline.service import PipelineOrchestrator, PipelineRequest, steps_view

_KNOWN_CATEGORIES = ["electronics", "home", "accessories"]
_KNOWN_MARKETS = ["us", "eu", "mx"]


def run_now(orchestrator: PipelineOrchestrator, request: PipelineRequest) -> PipelineRun:
    """Encolar y ejecutar en el acto: este barrido mide resultados de negocio, no
    el ciclo del runtime (Milestone 32)."""
    run = orchestrator.enqueue_run(request)
    return orchestrator.execute_run(run.id)


def view(db: Session, run: PipelineRun) -> dict[str, dict]:
    return steps_view(db.query(PipelineStep).filter_by(pipeline_run_id=run.id).all())


#: Los dos finales legítimos de una ejecución sana: terminó, o está esperando a
#: que una persona autorice la primera acción con efecto.
SETTLED = {"COMPLETED", "WAITING_APPROVAL"}


def analysis_completed(steps: dict[str, dict]) -> bool:
    """El análisis no lo detiene nada (plan maestro §7)."""
    return all(steps[name]["step_status"] == "COMPLETED" for name in ("research", "sourcing", "economics", "legal"))


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


@pytest.mark.parametrize("category", _KNOWN_CATEGORIES)
@pytest.mark.parametrize("market", _KNOWN_MARKETS)
def test_every_known_category_and_market_combo_completes_without_error(
    db_session: Session, category: str, market: str
):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(
        category=category, market=market, sale_price=50.0, destination_region="mexico"
    )

    run = run_now(orchestrator, request)

    steps = view(db_session, run)
    assert run.status in SETTLED
    assert analysis_completed(steps)
    assert steps["economics"]["recommendation"] in {"GO", "REVIEW", "NO_GO"}
    assert steps["legal"]["recommendation"] in {"GO", "REVIEW", "NO_GO"}


@pytest.mark.parametrize("category", _KNOWN_CATEGORIES)
def test_a_too_low_sale_price_always_produces_no_go_economics(db_session: Session, category: str):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category=category, sale_price=0.5, destination_region="mexico")

    run = run_now(orchestrator, request)

    steps = view(db_session, run)
    assert steps["economics"]["recommendation"] == "NO_GO"
    # El análisis no se detiene (ADR 0005); actuar sobre un NO_GO, sí
    # (Milestone 33, ADR 0011).
    assert analysis_completed(steps)
    assert run.status in SETTLED


def test_economics_can_produce_a_review_outcome_near_the_margin_boundary(db_session: Session):
    """The manual sweep never found a REVIEW outcome (only GO/NO_GO) —
    this searches for the boundary at runtime instead of hardcoding a
    fragile magic price that would silently stop meaning anything the
    moment the fixture data changes."""
    orchestrator = PipelineOrchestrator(db_session)

    found_review = False
    sale_price = 30.0
    while sale_price >= 2.0:
        run = run_now(
            orchestrator,
            PipelineRequest(category="home", sale_price=sale_price, destination_region="mexico"),
        )
        if view(db_session, run)["economics"]["recommendation"] == "REVIEW":
            found_review = True
            break
        sale_price -= 0.5

    assert found_review, "no sale_price in [2.0, 30.0] produced a REVIEW economics outcome"


def test_an_unrecognized_destination_region_still_completes(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="narnia")

    run = run_now(orchestrator, request)

    assert run.status in SETTLED
    assert analysis_completed(view(db_session, run))


def test_an_unrecognized_market_still_completes_with_a_flagged_legal_risk(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", market="ca", sale_price=50.0, destination_region="mexico")

    run = run_now(orchestrator, request)

    steps = view(db_session, run)
    assert analysis_completed(steps)
    assert steps["legal"]["recommendation"] == "REVIEW"
    # Y ese riesgo legal ya no es solo una anotación: detiene la publicación
    # hasta que alguien la autorice (Milestone 33).
    assert run.status == "WAITING_APPROVAL"
