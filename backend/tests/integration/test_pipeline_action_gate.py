"""El ActionGate dentro del pipeline, con el worker de verdad (Milestone 33).

Lo que hay que demostrar aquí no es la regla —eso está en el test unitario— sino
sus consecuencias sobre una ejecución: que el análisis nunca se detiene, que una
acción con efecto sí, que esperar no gasta intentos, que aprobar continúa por
donde iba sin repetir nada, y que rechazar deja constancia y sigue.

Entradas reales, no parcheadas: `accessories` en `eu` sin certificación da un
NO_GO legal de verdad (`MockRegulatoryDirectory`: REACH, restringido), y un
precio de venta de 0,5 da un NO_GO económico de verdad.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.job import Job, JobAttempt
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_step import PipelineStep
from app.jobs.schemas import JobEventKind, JobStatus
from app.jobs.worker import Worker
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.schemas import (
    REVIEW_KIND_ACTION_GATE,
    REVIEW_KIND_POST_HOC,
    PipelineRunStatus,
    PipelineStepStatus,
)
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

#: Todo en orden: legal GO y economía GO.
CLEAN = PipelineRequest(category="home", sale_price=50.0, destination_region="mexico", market="us")
#: Legal NO_GO de verdad: categoría restringida en la UE sin certificación.
LEGAL_NO_GO = PipelineRequest(
    category="accessories", sale_price=50.0, destination_region="mexico", market="eu"
)
#: Economía NO_GO de verdad: el precio no cubre ni el coste.
ECONOMICS_NO_GO = PipelineRequest(
    category="home", sale_price=0.5, destination_region="mexico", market="us"
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def drain(db: Session, rounds: int = 12) -> None:
    worker = Worker(name="test-worker")
    for _ in range(rounds):
        if worker.run_once(db) is None:
            break


def statuses(db: Session, run_id: str) -> dict[str, str]:
    rows = db.query(PipelineStep).filter_by(pipeline_run_id=run_id).order_by(PipelineStep.ordinal).all()
    return {row.name: row.status for row in rows}


def gate_reviews(db: Session, run_id: str) -> list[PipelineReview]:
    return (
        db.query(PipelineReview)
        .filter_by(pipeline_run_id=run_id, kind=REVIEW_KIND_ACTION_GATE)
        .order_by(PipelineReview.created_at)
        .all()
    )


# --- ALLOW -----------------------------------------------------------------


def test_a_clean_run_goes_through_the_gate_without_stopping(db_session: Session):
    run = PipelineOrchestrator(db_session).enqueue_run(CLEAN)

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.COMPLETED
    assert set(statuses(db_session, run.id).values()) == {PipelineStepStatus.COMPLETED}
    assert gate_reviews(db_session, run.id) == []


def test_an_allowed_action_is_audited_as_allowed(db_session: Session):
    run = PipelineOrchestrator(db_session).enqueue_run(CLEAN)

    drain(db_session)

    allows = (
        db_session.query(AuditLog)
        .filter_by(correlation_id=run.correlation_id, action="action_gate.allow")
        .all()
    )
    # Tres pasos con efecto: tienda, marketplace y publicidad.
    assert len(allows) == 3
    assert {entry.after["side_effect_action"] for entry in allows} == {"publish_product", "activate_ads"}


# --- DENY ------------------------------------------------------------------


def test_a_legal_no_go_denies_the_actions_and_lets_the_analysis_finish(db_session: Session):
    """El ejemplo del plan maestro §7, de punta a punta."""
    run = PipelineOrchestrator(db_session).enqueue_run(LEGAL_NO_GO)

    drain(db_session)

    db_session.refresh(run)
    step_statuses = statuses(db_session, run.id)
    assert step_statuses["legal"] == PipelineStepStatus.COMPLETED
    assert step_statuses["ecommerce"] == PipelineStepStatus.DENIED
    assert step_statuses["marketplace"] == PipelineStepStatus.DENIED
    assert step_statuses["marketing"] == PipelineStepStatus.DENIED
    # Y lo que no tiene efecto siguió su curso: la cadena no se detiene para
    # analizar (ADR 0005), solo para actuar (ADR 0011).
    assert step_statuses["operations"] == PipelineStepStatus.COMPLETED
    assert step_statuses["cfo"] == PipelineStepStatus.COMPLETED
    assert run.status == PipelineRunStatus.COMPLETED


def test_a_denied_step_says_why_and_is_audited(db_session: Session):
    run = PipelineOrchestrator(db_session).enqueue_run(LEGAL_NO_GO)

    drain(db_session)

    ecommerce = (
        db_session.query(PipelineStep).filter_by(pipeline_run_id=run.id, name="ecommerce").one()
    )
    assert "legal recommendation is NO_GO" in (ecommerce.error or "")
    assert ecommerce.detail["outcome"] == "DENY"
    denies = (
        db_session.query(AuditLog)
        .filter_by(correlation_id=run.correlation_id, action="action_gate.deny")
        .all()
    )
    assert len(denies) == 3


def test_a_denied_action_puts_the_run_in_the_review_tray(db_session: Session):
    """Una acción que el sistema impidió es justo lo que alguien tiene que
    mirar, aunque el resto terminara bien (ADR 0006 + Milestone 33)."""
    run = PipelineOrchestrator(db_session).enqueue_run(LEGAL_NO_GO)

    drain(db_session)

    db_session.refresh(run)
    assert run.needs_review is True
    review = (
        db_session.query(PipelineReview)
        .filter_by(pipeline_run_id=run.id, kind=REVIEW_KIND_POST_HOC)
        .one()
    )
    assert any("denied by the action gate" in reason for reason in review.reasons)


def test_a_denied_run_does_not_burn_job_attempts(db_session: Session):
    """Denegar no es fallar: no hay nada que reintentar."""
    run = PipelineOrchestrator(db_session).enqueue_run(LEGAL_NO_GO)

    drain(db_session)

    job = db_session.get(Job, run.job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.attempt == 1


# --- REQUIRE_APPROVAL ------------------------------------------------------


def test_a_doubt_stops_the_run_and_asks_without_burning_attempts(db_session: Session):
    run = PipelineOrchestrator(db_session).enqueue_run(ECONOMICS_NO_GO)

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    assert run.needs_review is True

    step_statuses = statuses(db_session, run.id)
    assert step_statuses["economics"] == PipelineStepStatus.COMPLETED
    assert step_statuses["ecommerce"] == PipelineStepStatus.WAITING_APPROVAL
    assert step_statuses["marketplace"] == PipelineStepStatus.PENDING

    # Esperar a una persona no gasta intentos: lo que falta no es tiempo.
    job = db_session.get(Job, run.job_id)
    assert job.status == JobStatus.WAITING_APPROVAL
    assert job.attempt == 1


def test_the_job_log_says_it_is_waiting_for_a_person(db_session: Session):
    from app.db.models.job import JobEvent

    run = PipelineOrchestrator(db_session).enqueue_run(ECONOMICS_NO_GO)

    drain(db_session)

    kinds = [
        event.kind
        for event in db_session.query(JobEvent).filter_by(job_id=run.job_id).order_by(JobEvent.created_at)
    ]
    assert JobEventKind.AWAITING_APPROVAL in kinds
    attempt = db_session.query(JobAttempt).filter_by(job_id=run.job_id, number=1).one()
    assert attempt.status == JobStatus.WAITING_APPROVAL


def test_the_request_names_the_step_and_the_action(db_session: Session):
    run = PipelineOrchestrator(db_session).enqueue_run(ECONOMICS_NO_GO)

    drain(db_session)

    reviews = gate_reviews(db_session, run.id)
    assert len(reviews) == 1
    assert reviews[0].status == "PENDING"
    assert reviews[0].step == "ecommerce"
    assert reviews[0].action == "publish_product"
    assert any("economics" in reason for reason in reviews[0].reasons)


def test_a_waiting_run_is_not_claimed_again_by_the_runtime(db_session: Session):
    run = PipelineOrchestrator(db_session).enqueue_run(ECONOMICS_NO_GO)
    drain(db_session)

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    assert db_session.get(Job, run.job_id).attempt == 1


# --- Aprobar ---------------------------------------------------------------


def resolve(db: Session, review: PipelineReview, status: str, actor: str = "owner@amazona.local") -> None:
    """Lo que hace la API al resolver: marcar la revisión y reanudar."""
    import datetime

    review.status = status
    review.resolved_at = datetime.datetime.now(datetime.UTC)
    review.resolved_by = actor
    db.flush()
    run = review.pipeline_run_id
    from app.db.models.pipeline_run import PipelineRun

    PipelineOrchestrator(db).resume_run(db.get(PipelineRun, run), actor=actor)


def test_approving_continues_the_run_without_repeating_work(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(ECONOMICS_NO_GO)
    drain(db_session)
    before = {
        step.name: step.entity_id
        for step in db_session.query(PipelineStep).filter_by(pipeline_run_id=run.id)
    }

    resolve(db_session, gate_reviews(db_session, run.id)[0], "APPROVED")
    drain(db_session)

    db_session.refresh(run)
    after = {
        step.name: step.entity_id
        for step in db_session.query(PipelineStep).filter_by(pipeline_run_id=run.id)
    }
    # El análisis no se repitió: mismas filas.
    for name in ("research", "sourcing", "economics", "legal"):
        assert after[name] == before[name], name
    # Y el paso autorizado sí se ejecutó.
    assert statuses(db_session, run.id)["ecommerce"] == PipelineStepStatus.COMPLETED
    assert after["ecommerce"] is not None


def test_an_approval_authorises_that_step_and_not_the_next_one(db_session: Session):
    """Una autorización vale para la acción que la pidió. El siguiente paso con
    efecto vuelve a preguntar."""
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(ECONOMICS_NO_GO)
    drain(db_session)
    resolve(db_session, gate_reviews(db_session, run.id)[0], "APPROVED")

    drain(db_session)

    db_session.refresh(run)
    assert run.status == PipelineRunStatus.WAITING_APPROVAL
    reviews = gate_reviews(db_session, run.id)
    assert [review.step for review in reviews] == ["ecommerce", "marketplace"]
    assert reviews[1].status == "PENDING"


def test_approving_every_gate_takes_the_run_to_the_end(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(ECONOMICS_NO_GO)

    for _ in range(4):
        drain(db_session)
        db_session.refresh(run)
        if run.status != PipelineRunStatus.WAITING_APPROVAL:
            break
        pending = [review for review in gate_reviews(db_session, run.id) if review.status == "PENDING"]
        resolve(db_session, pending[0], "APPROVED")

    db_session.refresh(run)
    step_statuses = statuses(db_session, run.id)
    assert run.status == PipelineRunStatus.COMPLETED
    assert step_statuses["ecommerce"] == PipelineStepStatus.COMPLETED
    assert step_statuses["marketplace"] == PipelineStepStatus.COMPLETED
    # Publicidad gasta dinero y las cuentas dicen NO_GO: eso es un veto, y
    # ninguna firma lo levanta.
    assert step_statuses["marketing"] == PipelineStepStatus.DENIED
    assert step_statuses["cfo"] == PipelineStepStatus.COMPLETED


# --- Rechazar --------------------------------------------------------------


def test_rejecting_denies_the_step_and_the_chain_goes_on(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(ECONOMICS_NO_GO)
    drain(db_session)

    resolve(db_session, gate_reviews(db_session, run.id)[0], "REJECTED")
    drain(db_session)

    db_session.refresh(run)
    step_statuses = statuses(db_session, run.id)
    assert step_statuses["ecommerce"] == PipelineStepStatus.DENIED
    ecommerce = db_session.query(PipelineStep).filter_by(pipeline_run_id=run.id, name="ecommerce").one()
    assert "a human rejected this action" in (ecommerce.error or "")


def test_a_rejection_is_not_asked_again(db_session: Session):
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(ECONOMICS_NO_GO)
    drain(db_session)
    resolve(db_session, gate_reviews(db_session, run.id)[0], "REJECTED")

    drain(db_session)

    ecommerce_reviews = [review for review in gate_reviews(db_session, run.id) if review.step == "ecommerce"]
    assert len(ecommerce_reviews) == 1


# --- El kill switch gana ---------------------------------------------------


def test_the_kill_switch_denies_the_actions_of_a_run_already_under_way(db_session: Session):
    """El switch se apaga con la ejecución ya en marcha: los pasos de análisis
    que queden terminan, y ninguna acción con efecto se ejecuta."""
    orchestrator = PipelineOrchestrator(db_session)
    run = orchestrator.enqueue_run(ECONOMICS_NO_GO)
    drain(db_session)  # se para en la puerta de ecommerce
    PipelineKillSwitchService(db_session).disable(
        reason="incident", actor="owner@amazona.local", correlation_id="cid-kill"
    )

    resolve(db_session, gate_reviews(db_session, run.id)[0], "APPROVED")
    drain(db_session)

    db_session.refresh(run)
    # El trabajo ni siquiera llega a los pasos: el kill switch para la ejecución
    # entera al reclamarla (Milestone 32), que es la defensa de más afuera.
    assert run.status == PipelineRunStatus.BLOCKED
    assert db_session.get(Job, run.job_id).status == JobStatus.BLOCKED
    assert statuses(db_session, run.id)["ecommerce"] == PipelineStepStatus.PENDING


def test_with_the_switch_off_the_gate_would_deny_even_an_approved_action(db_session: Session):
    """Defensa de dentro: aunque la ejecución llegara al paso, el gate tampoco
    dejaría actuar. Una firma no levanta el kill switch."""
    from app.gates.action_gate import HumanApproval, SideEffectAction
    from app.gates.service import ActionGateService

    PipelineKillSwitchService(db_session).disable(
        reason="incident", actor="owner@amazona.local", correlation_id="cid-kill"
    )

    decision = ActionGateService(db_session).evaluate(
        SideEffectAction.PUBLISH_PRODUCT, human_approval=HumanApproval.GRANTED
    )

    assert decision.outcome.value == "DENY"
