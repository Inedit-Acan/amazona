from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.operations_record import OperationsRecord as OperationsRecordModel
from app.db.session import get_db
from app.operations.service import OperationsService

router = APIRouter(tags=["operations"])


class OperationsRunCreate(BaseModel):
    product_id: str
    market: str


class OperationsRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str
    marketing_campaign_id: str | None
    market: str
    operations_status: str
    recommendation: str
    confidence: float
    data: dict | None


def _load_run(correlation_id: str, db: Session) -> OperationsRecordOut:
    record = db.query(OperationsRecordModel).filter_by(correlation_id=correlation_id).first()
    if record is None:
        raise NotFoundError(f"operations run {correlation_id} not found")
    return OperationsRecordOut.model_validate(record)


@router.post("/api/operations/runs", response_model=OperationsRecordOut, status_code=201)
def create_operations_run(payload: OperationsRunCreate, db: Session = Depends(get_db)) -> OperationsRecordOut:
    correlation_id = new_correlation_id()
    OperationsService(db).run_generation(
        product_id=payload.product_id,
        market=payload.market,
        correlation_id=correlation_id,
    )
    return _load_run(correlation_id, db)


@router.get("/api/operations/runs/{correlation_id}", response_model=OperationsRecordOut)
def get_operations_run(correlation_id: str, db: Session = Depends(get_db)) -> OperationsRecordOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/operations", response_model=list[OperationsRecordOut])
def list_product_operations(product_id: str, db: Session = Depends(get_db)) -> list[OperationsRecordModel]:
    return (
        db.query(OperationsRecordModel)
        .filter_by(product_id=product_id)
        .order_by(OperationsRecordModel.created_at.desc())
        .all()
    )
