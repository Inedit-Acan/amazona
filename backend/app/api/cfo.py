from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.cfo.service import CFOService
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.cfo_report import CFOReport as CFOReportModel
from app.db.session import get_db

router = APIRouter(tags=["cfo"])


class CFOReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    financial_health_status: str
    recommendation: str
    confidence: float
    data: dict | None


def _load_run(correlation_id: str, db: Session) -> CFOReportOut:
    record = db.query(CFOReportModel).filter_by(correlation_id=correlation_id).first()
    if record is None:
        raise NotFoundError(f"cfo run {correlation_id} not found")
    return CFOReportOut.model_validate(record)


@router.post("/api/cfo/runs", response_model=CFOReportOut, status_code=201)
def create_cfo_run(db: Session = Depends(get_db)) -> CFOReportOut:
    correlation_id = new_correlation_id()
    CFOService(db).run_generation(correlation_id=correlation_id)
    return _load_run(correlation_id, db)


@router.get("/api/cfo/runs/{correlation_id}", response_model=CFOReportOut)
def get_cfo_run(correlation_id: str, db: Session = Depends(get_db)) -> CFOReportOut:
    return _load_run(correlation_id, db)


@router.get("/api/cfo/runs", response_model=list[CFOReportOut])
def list_cfo_runs(db: Session = Depends(get_db)) -> list[CFOReportModel]:
    return db.query(CFOReportModel).order_by(CFOReportModel.created_at.desc()).all()
