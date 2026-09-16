from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.pipeline_run import PipelineRun as PipelineRunModel
from app.db.session import get_db
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
    steps: dict


def _load_run(correlation_id: str, db: Session) -> PipelineRunOut:
    record = db.query(PipelineRunModel).filter_by(correlation_id=correlation_id).first()
    if record is None:
        raise NotFoundError(f"pipeline run {correlation_id} not found")
    return PipelineRunOut.model_validate(record)


@router.post("/api/pipeline/runs", response_model=PipelineRunOut, status_code=201)
def create_pipeline_run(payload: PipelineRunCreate, db: Session = Depends(get_db)) -> PipelineRunOut:
    request = PipelineRequest(**payload.model_dump())
    run = PipelineOrchestrator(db).run_pipeline(request)
    return _load_run(run.correlation_id, db)


@router.get("/api/pipeline/runs/{correlation_id}", response_model=PipelineRunOut)
def get_pipeline_run(correlation_id: str, db: Session = Depends(get_db)) -> PipelineRunOut:
    return _load_run(correlation_id, db)


@router.get("/api/pipeline/runs", response_model=list[PipelineRunOut])
def list_pipeline_runs(db: Session = Depends(get_db)) -> list[PipelineRunModel]:
    return db.query(PipelineRunModel).order_by(PipelineRunModel.created_at.desc()).all()
