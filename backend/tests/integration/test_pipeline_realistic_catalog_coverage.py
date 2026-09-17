"""Milestone 13 (IVA-31): formalizes the manual investigation sweep run
before this milestone (3 categories x 3 markets x several price points x
known/unknown destination regions, 0 unhandled exceptions, 0 unexpected
statuses) as a permanent regression test over the real combinatorial
space the system already supports."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

_KNOWN_CATEGORIES = ["electronics", "home", "accessories"]
_KNOWN_MARKETS = ["us", "eu", "mx"]


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

    run = orchestrator.run_pipeline(request)

    assert run.status == "COMPLETED"
    assert run.steps["economics"]["recommendation"] in {"GO", "REVIEW", "NO_GO"}
    assert run.steps["legal"]["recommendation"] in {"GO", "REVIEW", "NO_GO"}


@pytest.mark.parametrize("category", _KNOWN_CATEGORIES)
def test_a_too_low_sale_price_always_produces_no_go_economics(db_session: Session, category: str):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category=category, sale_price=0.5, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.steps["economics"]["recommendation"] == "NO_GO"
    # No auto-halt (ADR 0005) — the pipeline still completes every step.
    assert run.status == "COMPLETED"


def test_economics_can_produce_a_review_outcome_near_the_margin_boundary(db_session: Session):
    """The manual sweep never found a REVIEW outcome (only GO/NO_GO) —
    this searches for the boundary at runtime instead of hardcoding a
    fragile magic price that would silently stop meaning anything the
    moment the fixture data changes."""
    orchestrator = PipelineOrchestrator(db_session)

    found_review = False
    sale_price = 30.0
    while sale_price >= 2.0:
        run = orchestrator.run_pipeline(
            PipelineRequest(category="home", sale_price=sale_price, destination_region="mexico")
        )
        if run.steps["economics"]["recommendation"] == "REVIEW":
            found_review = True
            break
        sale_price -= 0.5

    assert found_review, "no sale_price in [2.0, 30.0] produced a REVIEW economics outcome"


def test_an_unrecognized_destination_region_still_completes(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", sale_price=50.0, destination_region="narnia")

    run = orchestrator.run_pipeline(request)

    assert run.status == "COMPLETED"


def test_an_unrecognized_market_still_completes_with_a_flagged_legal_risk(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    request = PipelineRequest(category="home", market="ca", sale_price=50.0, destination_region="mexico")

    run = orchestrator.run_pipeline(request)

    assert run.status == "COMPLETED"
    assert run.steps["legal"]["recommendation"] == "REVIEW"
