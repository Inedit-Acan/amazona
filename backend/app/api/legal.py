from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.legal_analysis import LegalAnalysis as LegalAnalysisModel
from app.db.session import get_db
from app.legal.service import LegalComplianceService

router = APIRouter(tags=["legal"])


class LegalAnalysisRunCreate(BaseModel):
    product_id: str
    market: str
    certification_available: bool = False


class LegalAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str
    supplier_quote_id: str | None
    market: str
    restricted: bool | None
    recommendation: str
    confidence: float
    data: dict | None


def _load_run(correlation_id: str, db: Session) -> LegalAnalysisOut:
    analysis = db.query(LegalAnalysisModel).filter_by(correlation_id=correlation_id).first()
    if analysis is None:
        raise NotFoundError(f"legal analysis run {correlation_id} not found")
    return LegalAnalysisOut.model_validate(analysis)


@router.post("/api/legal/runs", response_model=LegalAnalysisOut, status_code=201)
def create_legal_analysis_run(payload: LegalAnalysisRunCreate, db: Session = Depends(get_db)) -> LegalAnalysisOut:
    correlation_id = new_correlation_id()
    LegalComplianceService(db).run_analysis(
        product_id=payload.product_id,
        market=payload.market,
        certification_available=payload.certification_available,
        correlation_id=correlation_id,
    )
    return _load_run(correlation_id, db)


@router.get("/api/legal/runs/{correlation_id}", response_model=LegalAnalysisOut)
def get_legal_analysis_run(correlation_id: str, db: Session = Depends(get_db)) -> LegalAnalysisOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/legal", response_model=list[LegalAnalysisOut])
def list_product_legal(product_id: str, db: Session = Depends(get_db)) -> list[LegalAnalysisModel]:
    return (
        db.query(LegalAnalysisModel)
        .filter_by(product_id=product_id)
        .order_by(LegalAnalysisModel.created_at.desc())
        .all()
    )
