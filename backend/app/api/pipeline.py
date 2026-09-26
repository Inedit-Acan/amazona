import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import actor_name, authorize
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, PipelineReviewNotPendingError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.pipeline_review import PipelineReview as PipelineReviewModel
from app.db.models.pipeline_run import PipelineRun as PipelineRunModel
from app.db.models.pipeline_step import PipelineStep as PipelineStepModel
from app.db.models.pipeline_step import PipelineStepAttempt as PipelineStepAttemptModel
from app.db.session import get_db
from app.permissions.policies import ApiAction
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.service import PipelineOrchestrator, PipelineRequest, load_steps_views, steps_view

router = APIRouter(tags=["pipeline"])


class PipelineRunCreate(BaseModel):
    category: str
    sale_price: float
    destination_region: str
    market: str = "us"
    marketplace_platform: str = "amazon"
    marketing_platform: str = "meta"
    daily_budget: float = 20.0
    monthly_fixed_costs: float = 500.0
    certification_available: bool = False
    max_results: int = 5


class PipelineRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str | None
    category: str
    market: str
    status: str
    failed_step: str | None
    needs_review: bool
    #: Reconstruido desde las filas de `pipeline_steps` (ADR 0010): misma forma
    #: que el JSON que esta API devuelve desde el Milestone 12, más el estado de
    #: ejecución de cada paso en `step_status`.
    steps: dict
    #: El trabajo que la ejecuta. Su bitácora está en `GET /api/jobs/{id}`.
    job_id: str | None


class PipelineStepAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: str
    number: int
    status: str
    error: str | None
    job_id: str | None
    started_at: datetime.datetime
    finished_at: datetime.datetime | None


class PipelineRunDetailOut(PipelineRunOut):
    #: Cada pasada por cada paso, en orden. Es lo que explica por qué alguien
    #: tuvo que reanudar una ejecución (plan maestro §21).
    attempts: list[PipelineStepAttemptOut]


class PipelineRunResumeIn(BaseModel):
    actor: str | None = None
    #: Paso por el que continuar. Por defecto, el primero que no esté COMPLETED
    #: —que es el que falló—. Indicarlo fuerza rehacer ese paso y los siguientes.
    from_step: str | None = None


class PipelineRunCancelIn(BaseModel):
    actor: str | None = None


class PipelineReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str
    reasons: list[str]
    status: str
    resolved_at: datetime.datetime | None
    resolved_by: str | None
    correlation_id: str


class PipelineReviewActionIn(BaseModel):
    actor: str


class KillSwitchOut(BaseModel):
    enabled: bool
    reason: str | None
    updated_by: str | None


class KillSwitchSetIn(BaseModel):
    enabled: bool
    reason: str | None = None
    actor: str


def _require_run(correlation_id: str, db: Session) -> PipelineRunModel:
    record = db.query(PipelineRunModel).filter_by(correlation_id=correlation_id).first()
    if record is None:
        raise NotFoundError(f"pipeline run {correlation_id} not found")
    return record


def _run_fields(record: PipelineRunModel) -> dict:
    """Los campos de la fila. `steps` no sale de aquí: vive en sus propias filas
    y se reconstruye aparte (ADR 0010)."""
    return {
        "correlation_id": record.correlation_id,
        "product_id": record.product_id,
        "category": record.category,
        "market": record.market,
        "status": record.status,
        "failed_step": record.failed_step,
        "needs_review": record.needs_review,
        "job_id": record.job_id,
    }


def _view(record: PipelineRunModel, db: Session) -> PipelineRunOut:
    steps = db.query(PipelineStepModel).filter_by(pipeline_run_id=record.id).all()
    return PipelineRunOut(**_run_fields(record), steps=steps_view(steps))


@router.post("/api/pipeline/runs", response_model=PipelineRunOut, status_code=202)
def create_pipeline_run(
    payload: PipelineRunCreate,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.PIPELINE_RUN)),
) -> PipelineRunOut:
    """Encola una ejecución del pipeline. **No la ejecuta**: de eso se encarga un
    worker (Milestone 32, ADR 0010), así que responde 202 con la ejecución en
    QUEUED y sus nueve pasos en PENDING. El resultado se sigue por
    `GET /api/pipeline/runs/{correlation_id}`."""
    request = PipelineRequest(**payload.model_dump())
    run = PipelineOrchestrator(db).enqueue_run(request, created_by=identity.audit_name)
    return _view(run, db)


@router.get("/api/pipeline/runs/{correlation_id}", response_model=PipelineRunDetailOut)
def get_pipeline_run(correlation_id: str, db: Session = Depends(get_db)) -> PipelineRunDetailOut:
    record = _require_run(correlation_id, db)
    steps = db.query(PipelineStepModel).filter_by(pipeline_run_id=record.id).all()
    by_id = {step.id: step for step in steps}
    attempt_rows = (
        db.query(PipelineStepAttemptModel)
        .filter(PipelineStepAttemptModel.pipeline_step_id.in_(list(by_id) or [""]))
        .order_by(PipelineStepAttemptModel.started_at)
        .all()
    )
    attempts = [
        PipelineStepAttemptOut(
            step=by_id[row.pipeline_step_id].name,
            number=row.number,
            status=row.status,
            error=row.error,
            job_id=row.job_id,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
        for row in attempt_rows
    ]
    return PipelineRunDetailOut(**_run_fields(record), steps=steps_view(steps), attempts=attempts)


@router.get("/api/pipeline/runs", response_model=list[PipelineRunOut])
def list_pipeline_runs(db: Session = Depends(get_db)) -> list[PipelineRunOut]:
    records = db.query(PipelineRunModel).order_by(PipelineRunModel.created_at.desc()).all()
    views = load_steps_views(db, [record.id for record in records])
    return [
        PipelineRunOut(**_run_fields(record), steps=views.get(record.id, {})) for record in records
    ]


@router.post("/api/pipeline/runs/{correlation_id}/resume", response_model=PipelineRunOut)
def resume_pipeline_run(
    correlation_id: str,
    payload: PipelineRunResumeIn | None = None,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.PIPELINE_RUN)),
    settings: Settings = Depends(get_settings),
) -> PipelineRunOut:
    """Devuelve a la cola una ejecución parada, conservando los pasos que ya
    terminaron bien. Reintentar el paso que falló y reanudar la ejecución son la
    misma operación: el punto por el que se continúa **es** el paso fallido."""
    body = payload or PipelineRunResumeIn()
    record = _require_run(correlation_id, db)
    actor = actor_name(identity, body.actor, settings)
    run = PipelineOrchestrator(db).resume_run(
        record, actor=actor, identity=identity, from_step=body.from_step
    )
    return _view(run, db)


@router.post("/api/pipeline/runs/{correlation_id}/cancel", response_model=PipelineRunOut)
def cancel_pipeline_run(
    correlation_id: str,
    payload: PipelineRunCancelIn | None = None,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.PIPELINE_RUN)),
    settings: Settings = Depends(get_settings),
) -> PipelineRunOut:
    """Para una ejecución. Si un worker la tiene entre manos, se entera en su
    siguiente latido —entre pasos— y deja el paso en curso en CANCELLED."""
    body = payload or PipelineRunCancelIn()
    record = _require_run(correlation_id, db)
    actor = actor_name(identity, body.actor, settings)
    run = PipelineOrchestrator(db).cancel_run(record, actor=actor, identity=identity)
    return _view(run, db)


@router.get("/api/pipeline/reviews", response_model=list[PipelineReviewOut])
def list_pipeline_reviews(db: Session = Depends(get_db)) -> list[PipelineReviewModel]:
    return (
        db.query(PipelineReviewModel)
        .filter_by(status="PENDING")
        .order_by(PipelineReviewModel.created_at.desc())
        .all()
    )


@router.post("/api/pipeline/reviews/{review_id}/approve", response_model=PipelineReviewOut)
def approve_pipeline_review(
    review_id: str,
    payload: PipelineReviewActionIn,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.REVIEW_RESOLVE)),
    settings: Settings = Depends(get_settings),
) -> PipelineReviewModel:
    return _resolve_review(review_id, "APPROVED", db, identity, payload.actor, settings)


@router.post("/api/pipeline/reviews/{review_id}/reject", response_model=PipelineReviewOut)
def reject_pipeline_review(
    review_id: str,
    payload: PipelineReviewActionIn,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.REVIEW_RESOLVE)),
    settings: Settings = Depends(get_settings),
) -> PipelineReviewModel:
    return _resolve_review(review_id, "REJECTED", db, identity, payload.actor, settings)


def _resolve_review(
    review_id: str,
    new_status: str,
    db: Session,
    identity: Actor,
    declared: str | None,
    settings: Settings,
) -> PipelineReviewModel:
    actor = actor_name(identity, declared, settings)
    review = db.get(PipelineReviewModel, review_id)
    if review is None:
        raise NotFoundError(f"pipeline review {review_id} not found")
    if review.status != "PENDING":
        raise PipelineReviewNotPendingError(f"pipeline review {review_id} is not pending (status={review.status})")

    before_status = review.status
    review.status = new_status
    review.resolved_at = datetime.datetime.now(datetime.UTC)
    review.resolved_by = actor
    action_verb = "approve" if new_status == "APPROVED" else "reject"
    db.add(
        AuditLog(
            actor=actor,
            actor_role=identity.role,
            actor_source=identity.source,
            action=f"pipeline_review.{action_verb}",
            resource=f"pipeline_review:{review.id}",
            before={"status": before_status},
            after={"status": new_status},
            correlation_id=review.correlation_id,
        )
    )
    db.commit()
    db.refresh(review)
    return review


@router.get("/api/pipeline/kill-switch", response_model=KillSwitchOut)
def get_kill_switch(db: Session = Depends(get_db)) -> KillSwitchOut:
    state = PipelineKillSwitchService(db).get_state()
    return KillSwitchOut.model_validate(state, from_attributes=True)


@router.post("/api/pipeline/kill-switch", response_model=KillSwitchOut)
def set_kill_switch(
    payload: KillSwitchSetIn,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.KILL_SWITCH_WRITE)),
    settings: Settings = Depends(get_settings),
) -> KillSwitchOut:
    service = PipelineKillSwitchService(db)
    correlation_id = new_correlation_id()
    # The kill switch is the one control that must never be attributable to a
    # name the caller made up (plan maestro §P0.4).
    actor = actor_name(identity, payload.actor, settings)
    if payload.enabled:
        state = service.enable(actor=actor, correlation_id=correlation_id, identity=identity)
    else:
        state = service.disable(
            reason=payload.reason or "no reason given",
            actor=actor,
            correlation_id=correlation_id,
            identity=identity,
        )
    return KillSwitchOut.model_validate(state, from_attributes=True)
