from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.supplier_quote import SupplierQuote as SupplierQuoteModel
from app.db.session import get_db
from app.permissions.policies import ApiAction
from app.sourcing.service import SourcingService

router = APIRouter(tags=["sourcing"])


class SourcingRunCreate(BaseModel):
    product_id: str
    category: str
    destination_region: str
    max_results: int = Field(default=5, ge=1, le=20)


class SupplierQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    supplier_id: str
    unit_price: float
    moq: int
    lead_time_days: int
    verified: bool
    reliability_score: float
    logistics_cost_per_unit: float
    total_landed_cost_per_unit: float
    data: dict | None


class SourcingRunOut(BaseModel):
    correlation_id: str
    quotes: list[SupplierQuoteOut]


def _load_run(correlation_id: str, db: Session) -> SourcingRunOut:
    quotes = db.query(SupplierQuoteModel).filter_by(correlation_id=correlation_id).all()
    if not quotes:
        raise NotFoundError(f"sourcing run {correlation_id} not found")

    return SourcingRunOut(
        correlation_id=correlation_id,
        quotes=[SupplierQuoteOut.model_validate(q) for q in quotes],
    )


@router.post("/api/sourcing/runs", response_model=SourcingRunOut, status_code=201)
def create_sourcing_run(
    payload: SourcingRunCreate,
    db: Session = Depends(get_db),
    _actor: Actor = Depends(authorize(ApiAction.AGENT_RUN)),
) -> SourcingRunOut:
    correlation_id = new_correlation_id()
    quotes = SourcingService(db).run_sourcing(
        product_id=payload.product_id,
        category=payload.category,
        destination_region=payload.destination_region,
        max_results=payload.max_results,
        correlation_id=correlation_id,
    )
    if not quotes:
        return SourcingRunOut(correlation_id=correlation_id, quotes=[])
    return _load_run(correlation_id, db)


@router.get("/api/sourcing/runs/{correlation_id}", response_model=SourcingRunOut)
def get_sourcing_run(correlation_id: str, db: Session = Depends(get_db)) -> SourcingRunOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/suppliers", response_model=list[SupplierQuoteOut])
def list_product_suppliers(product_id: str, db: Session = Depends(get_db)) -> list[SupplierQuoteModel]:
    return (
        db.query(SupplierQuoteModel)
        .filter_by(product_id=product_id)
        .order_by(SupplierQuoteModel.total_landed_cost_per_unit.asc())
        .all()
    )
