import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.ids import new_correlation_id
from app.costs.service import ApiBudgetExceededError
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis as EconomicAnalysisModel
from app.db.models.exchange_rate import ExchangeRate as ExchangeRateModel
from app.db.session import get_db
from app.economics.service import DEFAULT_CHANNEL, EconomicAnalysisService
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.integrations.fx.ecb import FeedUnavailableError
from app.money.ecb import ATTRIBUTION, NOTICE, is_ecb_source
from app.money.fx_refresh import FxRefreshService, FxSourceNotConfiguredError, RefreshResult
from app.money.rates import ExchangeRate
from app.permissions.policies import ApiAction
from app.sourcing.provenance import SupplierFactProvenance
from app.sourcing.trade_terms import ACCOUNTING_CURRENCY

router = APIRouter(tags=["economics"])


class EconomicAnalysisRunCreate(BaseModel):
    product_id: str
    supplier_quote_id: str
    sale_price: float
    monthly_fixed_costs: float = Field(default=500.0)
    monthly_unit_sales_base: float | None = None
    #: Dónde se vende. Del catálogo del Milestone 38.
    channel: str = DEFAULT_CHANNEL
    #: La moneda de todo el análisis.
    currency: str = ACCOUNTING_CURRENCY
    #: Cuántas unidades lleva un pedido. **Sin valor por defecto**: un 1 que
    #: nadie ha declarado dejaría el techo de CAC calculado sobre una suposición.
    units_per_order: int | None = Field(default=None, ge=1)
    payment_cost_per_unit: float | None = Field(default=None, ge=0.0)
    other_variable_cost_per_unit: float | None = Field(default=None, ge=0.0)


class EconomicAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correlation_id: str
    product_id: str
    supplier_quote_id: str
    sale_price: float
    monthly_fixed_costs: float
    margin_percent: float | None
    recommendation: str
    confidence: float
    channel: str | None
    currency: str | None
    units_per_order: int | None
    units_per_order_provenance: str | None
    #: `evaluable` o `not_evaluable`. **No es un resultado económico.**
    margin_evaluability: str
    cac_evaluability: str
    missing_inputs: list | None
    #: Importes como cadena: en JavaScript un número es un `float64`, y mandar
    #: `6.4` devolvería el error de redondeo por la puerta de atrás.
    contribution_margin_per_unit: str | None
    contribution_margin_per_order: str | None
    allocated_fixed_cost_per_order: str | None
    max_breakeven_cac: str | None
    fx_conversions: list | None
    data: dict | None


class ExchangeRateCreate(BaseModel):
    """Alta manual de un tipo de cambio (Milestone 40).

    `1 base_currency = rate quote_currency`. La dirección va en los nombres de
    los campos: sin eso, un 1,08 puede ser dólares por euro o al revés, y entre
    las dos lecturas hay un 16 %.
    """

    base_currency: str
    quote_currency: str
    rate: Decimal = Field(gt=0)
    effective_date: datetime.date
    source: str | None = None
    provenance: str = SupplierFactProvenance.DECLARED.value
    declared_by: str | None = None
    note: str | None = None


class ExchangeRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    effective_date: datetime.date
    source: str
    provenance: str
    declared_by: str | None
    note: str | None
    #: Cuándo entró la tasa en nuestra base. No es la fecha efectiva: esa es la del
    #: día al que pertenece la tasa (Milestone 42).
    ingested_at: datetime.datetime = Field(validation_alias="created_at")
    #: Solo en las referencias del BCE: la atribución que su licencia exige y la
    #: advertencia de que no es una tasa transaccional.
    attribution: str | None = None
    notice: str | None = None

    @model_validator(mode="after")
    def _explain_the_source(self) -> "ExchangeRateOut":
        if is_ecb_source(self.source):
            self.attribution = ATTRIBUTION
            self.notice = NOTICE
        return self


class RepublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pair: str
    effective_date: datetime.date
    previous_rate: Decimal
    new_rate: Decimal


class RefreshOut(BaseModel):
    """Lo que hizo un refresco de tasas del BCE."""

    model_config = ConfigDict(from_attributes=True)

    mode: str
    days_examined: int
    latest_effective_date: datetime.date
    ingested_at: datetime.datetime
    stored: int
    unchanged: int
    republished: list[RepublicationOut]
    omitted_currencies: list[str]


def _to_out(analysis: EconomicAnalysisModel) -> EconomicAnalysisOut:
    return EconomicAnalysisOut(
        correlation_id=analysis.correlation_id,
        product_id=analysis.product_id,
        supplier_quote_id=analysis.supplier_quote_id,
        sale_price=analysis.sale_price,
        monthly_fixed_costs=analysis.monthly_fixed_costs,
        margin_percent=analysis.margin_percent,
        recommendation=analysis.recommendation,
        confidence=analysis.confidence,
        channel=analysis.channel,
        currency=analysis.currency,
        units_per_order=analysis.units_per_order,
        units_per_order_provenance=analysis.units_per_order_provenance,
        margin_evaluability=analysis.margin_evaluability,
        cac_evaluability=analysis.cac_evaluability,
        missing_inputs=analysis.missing_inputs,
        contribution_margin_per_unit=_amount(analysis.contribution_margin_per_unit),
        contribution_margin_per_order=_amount(analysis.contribution_margin_per_order),
        allocated_fixed_cost_per_order=_amount(analysis.allocated_fixed_cost_per_order),
        max_breakeven_cac=_amount(analysis.max_breakeven_cac),
        fx_conversions=analysis.fx_conversions,
        data=analysis.data,
    )


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _load_run(correlation_id: str, db: Session) -> EconomicAnalysisOut:
    analysis = db.query(EconomicAnalysisModel).filter_by(correlation_id=correlation_id).first()
    if analysis is None:
        raise NotFoundError(f"economic analysis run {correlation_id} not found")
    return _to_out(analysis)


@router.post("/api/economics/runs", response_model=EconomicAnalysisOut, status_code=201)
def create_economic_analysis_run(
    payload: EconomicAnalysisRunCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.AGENT_RUN)),
) -> EconomicAnalysisOut:
    correlation_id = new_correlation_id()
    EconomicAnalysisService(db).run_analysis(
        product_id=payload.product_id,
        supplier_quote_id=payload.supplier_quote_id,
        sale_price=payload.sale_price,
        monthly_fixed_costs=payload.monthly_fixed_costs,
        monthly_unit_sales_base=payload.monthly_unit_sales_base,
        channel=payload.channel,
        currency=payload.currency,
        units_per_order=payload.units_per_order,
        payment_cost_per_unit=payload.payment_cost_per_unit,
        other_variable_cost_per_unit=payload.other_variable_cost_per_unit,
        actor=actor.audit_name,
        correlation_id=correlation_id,
    )
    return _load_run(correlation_id, db)


@router.get("/api/economics/runs/{correlation_id}", response_model=EconomicAnalysisOut)
def get_economic_analysis_run(correlation_id: str, db: Session = Depends(get_db)) -> EconomicAnalysisOut:
    return _load_run(correlation_id, db)


@router.get("/api/products/{product_id}/economics", response_model=list[EconomicAnalysisOut])
def list_product_economics(product_id: str, db: Session = Depends(get_db)) -> list[EconomicAnalysisOut]:
    rows = (
        db.query(EconomicAnalysisModel)
        .filter_by(product_id=product_id)
        .order_by(EconomicAnalysisModel.created_at.desc())
        .all()
    )
    return [_to_out(row) for row in rows]


@router.get("/api/exchange-rates", response_model=list[ExchangeRateOut])
def list_exchange_rates(db: Session = Depends(get_db)) -> list[ExchangeRateModel]:
    """Las tasas declaradas, de la más reciente a la más antigua.

    No se borran ni se machacan: el margen que se calculó en marzo se calculó
    con la de marzo, y esta lista es la única forma de reconstruirlo.
    """
    return (
        db.query(ExchangeRateModel)
        .order_by(ExchangeRateModel.effective_date.desc(), ExchangeRateModel.created_at.desc())
        .all()
    )


@router.post("/api/exchange-rates", response_model=ExchangeRateOut, status_code=201)
def create_exchange_rate(
    payload: ExchangeRateCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.EXCHANGE_RATE_WRITE)),
) -> ExchangeRateModel:
    source = payload.source or f"manual:{actor.audit_name}"
    if is_ecb_source(source):
        # El prefijo es de la ingesta del BCE: una tasa escrita a mano con él se
        # leería como referencia del BCE, con su ventana y su precedencia.
        raise ValidationError(
            "the 'ecb:' source prefix is reserved for the ECB refresh; a declared rate "
            "carries its own source"
        )
    # Construir el objeto del dominio antes de guardarlo es lo que rechaza una
    # moneda fuera de catálogo, una tasa negativa, un par contra sí mismo y un
    # `third_party_verified` sin emisor. La validación vive en el dominio.
    rate = ExchangeRate(
        base_currency=payload.base_currency,
        quote_currency=payload.quote_currency,
        rate=payload.rate,
        effective_date=payload.effective_date,
        source=source,
        provenance=SupplierFactProvenance(payload.provenance),
        declared_by=payload.declared_by,
    )
    if rate.effective_date > datetime.datetime.now(datetime.UTC).date():
        raise ValidationError(
            "an exchange rate cannot be dated in the future: converting today with "
            "tomorrow's rate is reading the answer before the exam"
        )

    row = ExchangeRateModel(
        base_currency=rate.base_currency,
        quote_currency=rate.quote_currency,
        rate=rate.rate,
        effective_date=rate.effective_date,
        source=rate.source,
        provenance=rate.provenance.value,
        declared_by=rate.declared_by,
        note=payload.note,
    )
    db.add(row)
    db.add(
        AuditLog(
            actor=actor.audit_name,
            action="exchange_rate.declare",
            resource=f"exchange_rate:{rate.pair}",
            before=None,
            after={
                "pair": rate.pair,
                "rate": str(rate.rate),
                "effective_date": rate.effective_date.isoformat(),
                "provenance": rate.provenance.value,
            },
            correlation_id=new_correlation_id(),
        )
    )
    db.commit()
    return row


def _refresh(action: str, actor: Actor, db: Session) -> RefreshResult:
    service = FxRefreshService(db)
    try:
        if action == "backfill":
            return service.backfill_history(actor=actor.audit_name)
        return service.refresh_daily(actor=actor.audit_name)
    except FxSourceNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApiBudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except FeedUnavailableError as exc:
        # 502: la fuente no contestó bien. No se guardó nada ni se borró nada.
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _refresh_once(
    action: str,
    actor: Actor,
    db: Session,
    response: Response,
    settings: Settings,
    idempotency_key: str | None,
) -> RefreshResult:
    """Una llamada externa que escribe: con `Idempotency-Key`, un reintento no vuelve a salir a la fuente."""
    return run_idempotent(
        db,
        scope=f"fx.{action}",
        identity=actor,
        client_key=idempotency_key,
        settings=settings,
        payload={"action": action},
        response=response,
        status_code=200,
        response_model=RefreshOut,
        work=lambda: _refresh(action, actor, db),
    )


@router.post("/api/exchange-rates/refresh", response_model=RefreshOut)
def refresh_exchange_rates(
    response: Response,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.EXCHANGE_RATE_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> RefreshResult:
    """Trae las referencias diarias del BCE y las guarda. Es una llamada externa:
    pasa por la matriz de derechos y por el contador de coste. El análisis
    económico no la hace nunca: lee lo que este endpoint dejó guardado."""
    return _refresh_once("daily", actor, db, response, settings, idempotency_key)


@router.post("/api/exchange-rates/backfill", response_model=RefreshOut)
def backfill_exchange_rates(
    response: Response,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.EXCHANGE_RATE_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> RefreshResult:
    """Recuperación explícita con el histórico de 90 días del BCE. Solo la pide una
    persona: no es el respaldo automático de un fallo del refresco diario."""
    return _refresh_once("backfill", actor, db, response, settings, idempotency_key)


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
    api/approvals.py::_as_aware_utc).

    Desde el Milestone 40 solo entran los análisis **evaluables**: promediar un
    margen que no se pudo calcular exigiría tratarlo como cero, y una media con
    ceros inventados dentro es peor que no tener media."""
    since = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=days)
    day_col = func.date(EconomicAnalysisModel.created_at).label("day")

    rows = (
        db.query(
            day_col,
            func.count(EconomicAnalysisModel.id).label("analyses_count"),
            func.avg(EconomicAnalysisModel.margin_percent).label("avg_margin_percent"),
            func.avg(EconomicAnalysisModel.sale_price).label("avg_sale_price"),
        )
        .filter(
            EconomicAnalysisModel.created_at >= since,
            EconomicAnalysisModel.margin_percent.isnot(None),
        )
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
