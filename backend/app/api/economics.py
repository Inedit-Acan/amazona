from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.economic_analysis import EconomicAnalysis as EconomicAnalysisModel
from app.db.session import get_db
from app.economics.service import EconomicAnalysisService

router = APIRouter(tags=["economics"])


class EconomicAnalysisRunCreate(BaseModel):
    product_id: str
    supplier_quote_id: str
    sale_price: float
    monthly_fixed_costs: float = Field(default=500.0)
    monthly_unit_sales_base: float | None = None


class EconomicAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str
    supplier_quote_id: str
    sale_price: float
    monthly_fixed_costs: float
    margin_percent: float
    recommendation: str
    confidence: float
    data: dict | None


def _load_run(correlation_id: str, db: Session) -> EconomicAnalysisOut:
    analysis = db.query(EconomicAnalysisModel).filter_by(correlation_id=correlation_id).first()
    if analysis is None:
        raise NotFoundError(f"economic analysis run {correlation_id} not found")
    return EconomicAnalysisOut.model_validate(analysis)


@router.post("/api/economics/runs", response_model=EconomicAnalysisOut, status_code=201)
def create_economic_analysis_run(
    payload: EconomicAnalysisRunCreate, db: Session = Depends(get_db)
) -> EconomicAnalysisOut:
    correlation_id = new_correlation_id()
    EconomicAnalysisService(db).run_analysis(
        product_id=payload.product_id,
        supplier_quote_id=payload.supplier_quote_id,
        sale_price=payload.sale_price,
        monthly_fixed_costs=payload.monthly_fixed_costs,
        monthly_unit_sales_base=payload.monthly_unit_sales_base,
        correlation_id=correlation_id,
    )
    return _load_run(correlation_id, db)


@router.get("/api/economics/runs/{correlation_id}", response_model=EconomicAnalysisOut)
def get_economic_analysis_run(correlation_id: str, db: Session = Depends(get_db)) -> EconomicAnalysisOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/economics", response_model=list[EconomicAnalysisOut])
def list_product_economics(product_id: str, db: Session = Depends(get_db)) -> list[EconomicAnalysisModel]:
    return (
        db.query(EconomicAnalysisModel)
        .filter_by(product_id=product_id)
        .order_by(EconomicAnalysisModel.created_at.desc())
        .all()
    )
