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
from app.db.session import get_db
from app.permissions.policies import ApiAction
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

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
    steps: dict


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


def _load_run(correlation_id: str, db: Session) -> PipelineRunOut:
    record = db.query(PipelineRunModel).filter_by(correlation_id=correlation_id).first()
    if record is None:
        raise NotFoundError(f"pipeline run {correlation_id} not found")
    return PipelineRunOut.model_validate(record)


@router.post("/api/pipeline/runs", response_model=PipelineRunOut, status_code=201)
def create_pipeline_run(
    payload: PipelineRunCreate,
    db: Session = Depends(get_db),
    _actor: Actor = Depends(authorize(ApiAction.PIPELINE_RUN)),
) -> PipelineRunOut:
    request = PipelineRequest(**payload.model_dump())
    run = PipelineOrchestrator(db).run_pipeline(request)
    return _load_run(run.correlation_id, db)


@router.get("/api/pipeline/runs/{correlation_id}", response_model=PipelineRunOut)
def get_pipeline_run(correlation_id: str, db: Session = Depends(get_db)) -> PipelineRunOut:
    return _load_run(correlation_id, db)


@router.get("/api/pipeline/runs", response_model=list[PipelineRunOut])
def list_pipeline_runs(db: Session = Depends(get_db)) -> list[PipelineRunModel]:
    return db.query(PipelineRunModel).order_by(PipelineRunModel.created_at.desc()).all()


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
