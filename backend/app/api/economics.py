import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.economic_analysis import EconomicAnalysis as EconomicAnalysisModel
from app.db.session import get_db
from app.economics.service import EconomicAnalysisService
from app.permissions.policies import ApiAction

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
    payload: EconomicAnalysisRunCreate,
    db: Session = Depends(get_db),
    _actor: Actor = Depends(authorize(ApiAction.AGENT_RUN)),
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


class EconomicsTimeseriesPoint(BaseModel):
    day: str
    analyses_count: int
    avg_margin_percent: float
    avg_sale_price: float


@router.get("/api/economics/analyses/timeseries", response_model=list[EconomicsTimeseriesPoint])
def get_economics_timeseries(
    days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db)
) -> list[EconomicsTimeseriesPoint]:
    """Real, timestamped economic activity, grouped by day — not a sales
    ledger (none exists; nothing in AMAZONA charges real money yet, per
    ADR 0006). "Actividad económica", not "Ventas" — see
    docs/design/AMAZONA_handoff_backend_paneles_pendientes.md §2.

    `since` is naive UTC to match how SQLite (tests) round-trips
    `DateTime(timezone=True)` values — every timestamp in this schema is
    UTC by convention regardless of tzinfo (same caveat documented in
    api/approvals.py::_as_aware_utc)."""
    since = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=days)
    day_col = func.date(EconomicAnalysisModel.created_at).label("day")

    rows = (
        db.query(
            day_col,
            func.count(EconomicAnalysisModel.id).label("analyses_count"),
            func.avg(EconomicAnalysisModel.margin_percent).label("avg_margin_percent"),
            func.avg(EconomicAnalysisModel.sale_price).label("avg_sale_price"),
        )
        .filter(EconomicAnalysisModel.created_at >= since)
        .group_by(day_col)
        .order_by(day_col)
        .all()
    )

    return [
        EconomicsTimeseriesPoint(
            day=str(row.day),
            analyses_count=row.analyses_count,
            avg_margin_percent=round(row.avg_margin_percent, 4),
            avg_sale_price=round(row.avg_sale_price, 2),
        )
        for row in rows
    ]
