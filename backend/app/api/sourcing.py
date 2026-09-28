import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.errors import NotFoundError
from app.core.ids import new_correlation_id
from app.db.models.supplier import Supplier as SupplierModel
from app.db.models.supplier_quote import SupplierQuote as SupplierQuoteModel
from app.db.session import get_db
from app.permissions.policies import ApiAction
from app.sourcing.capabilities import SupplyCapability, profile, unanswered
from app.sourcing.provenance import SupplierFactProvenance
from app.sourcing.risk import RiskDimension
from app.sourcing.service import SourcingService

router = APIRouter(tags=["sourcing"])


class SourcingRunCreate(BaseModel):
    product_id: str
    category: str
    destination_region: str
    max_results: int = Field(default=5, ge=1, le=20)


class SupplierOut(BaseModel):
    """La ficha de un proveedor. Cada hecho con quién lo sostiene (ADR 0017)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    identity_key: str | None
    identity_method: str | None
    region: str | None
    country: str | None
    city: str | None
    website: str | None
    #: `None` = nadie ha dicho de dónde sale esta ficha. No es «no verificado».
    verification: str | None
    verified_by: str | None
    reliability_score: float | None
    reliability_provenance: str | None
    last_checked_at: datetime.datetime | None


class CapabilityOut(BaseModel):
    """Una de las ocho del §16, declarada o no."""

    capability: str
    #: `None` significa **no declarado**, nunca «no lo soporta».
    supported: bool | None
    provenance: str
    source: str | None = None
    note: str | None = None
    observed_at: datetime.datetime | None = None
    product_specific: bool = False


class RiskOut(BaseModel):
    """Una dimensión de §11. No hay puntuación total y no es un olvido."""

    dimension: str
    level: str
    rationale: str
    provenance: str
    basis: list[str]


class SupplierQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    supplier_id: str
    unit_price: float | None
    currency: str | None
    quoted_unit: str | None
    quoted_quantity: int | None
    moq: int | None
    lead_time_days: int | None
    transit_days: int | None
    transport_mode: str | None
    incoterm: str | None
    payment_terms: str | None
    destination_market: str | None
    valid_from: datetime.datetime | None
    valid_until: datetime.datetime | None
    provenance: str | None
    source: str | None
    logistics_cost_per_unit: float | None
    logistics_provenance: str | None
    total_landed_cost_per_unit: float | None
    data: dict | None


class SupplierQuoteDetailOut(SupplierQuoteOut):
    """La cotización con lo que hace falta para decidir: quién es el proveedor,
    qué sabe hacer y qué riesgos quedan sin evaluar.

    Va junto en una sola respuesta a propósito: un precio sin saber si el
    proveedor acepta devoluciones en la UE es la mitad de la información, y
    hasta este milestone la otra mitad la ponía el frontend inventándola.
    """

    supplier: SupplierOut | None
    capabilities: list[CapabilityOut]
    #: Las capacidades críticas para el modelo sin stock (§16) que siguen sin
    #: respuesta. Vacío no significa «compatible»: significa que ya no faltan
    #: respuestas.
    unanswered_capabilities: list[str]
    risk: list[RiskOut]


class SourcingRunOut(BaseModel):
    correlation_id: str
    quotes: list[SupplierQuoteOut]


class SupplierCreate(BaseModel):
    """Alta manual de un proveedor real (Milestone 39).

    Es la razón de ser del milestone: un proveedor negociado es un dato que solo
    puede entrar a mano, y este camino se sostiene permanentemente.
    """

    name: str
    region: str | None = None
    country: str | None = None
    city: str | None = None
    website: str | None = None
    contact_info: dict | None = None
    #: Por defecto, lo que dice el propio proveedor. Subirlo a
    #: `third_party_verified` exige nombrar al verificador.
    verification: str = SupplierFactProvenance.SUPPLIER_CLAIM.value
    verified_by: str | None = None
    reliability: float | None = Field(default=None, ge=0.0, le=1.0)
    reliability_provenance: str | None = None


class QuoteCreate(BaseModel):
    """Alta manual de una cotización. Todo opcional menos el producto: lo que
    el proveedor no haya dicho se queda sin decir."""

    product_id: str
    provenance: str = SupplierFactProvenance.SUPPLIER_CLAIM.value
    source: str | None = None
    unit_price: float | None = Field(default=None, ge=0.0)
    currency: str | None = None
    quoted_unit: str | None = None
    quoted_quantity: int | None = Field(default=None, ge=1)
    moq: int | None = Field(default=None, ge=1)
    lead_time_days: int | None = Field(default=None, ge=0)
    transit_days: int | None = Field(default=None, ge=0)
    transport_mode: str | None = None
    incoterm: str | None = None
    payment_terms: str | None = None
    destination_market: str | None = None
    logistics_cost_per_unit: float | None = Field(default=None, ge=0.0)
    valid_from: datetime.datetime | None = None
    valid_until: datetime.datetime | None = None


class CapabilityCreate(BaseModel):
    """Declaración de una de las ocho capacidades del §16."""

    capability: SupplyCapability
    supported: bool
    provenance: str = SupplierFactProvenance.SUPPLIER_CLAIM.value
    product_id: str | None = None
    source: str | None = None
    note: str | None = None


def _detail(quote: SupplierQuoteModel, db: Session) -> SupplierQuoteDetailOut:
    service = SourcingService(db)
    supplier = db.get(SupplierModel, quote.supplier_id)
    declarations = service.capability_declarations(
        quote.supplier_id, product_id=quote.product_id
    )
    answers = profile(declarations, product_id=quote.product_id)
    risk = service.risk_profile(quote)
    return SupplierQuoteDetailOut(
        **SupplierQuoteOut.model_validate(quote).model_dump(),
        supplier=SupplierOut.model_validate(supplier) if supplier else None,
        capabilities=[
            CapabilityOut(
                capability=a.capability.value,
                supported=a.supported,
                provenance=a.provenance.value,
                source=a.source,
                note=a.note,
                observed_at=a.observed_at,
                product_specific=a.product_specific,
            )
            for a in answers
        ],
        unanswered_capabilities=[
            c.value for c in unanswered(declarations, product_id=quote.product_id)
        ],
        risk=[
            RiskOut(
                dimension=a.dimension.value,
                level=a.level.value,
                rationale=a.rationale,
                provenance=a.provenance.value,
                basis=list(a.basis),
            )
            for a in (risk.of(dimension) for dimension in RiskDimension)
        ],
    )


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


@router.get("/api/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)) -> list[SupplierModel]:
    return db.query(SupplierModel).order_by(SupplierModel.name.asc()).all()


@router.get("/api/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: str, db: Session = Depends(get_db)) -> SupplierModel:
    supplier = db.get(SupplierModel, supplier_id)
    if supplier is None:
        raise NotFoundError(f"supplier {supplier_id} not found")
    return supplier


@router.post("/api/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.SUPPLIER_WRITE)),
) -> SupplierModel:
    return SourcingService(db).record_supplier(
        name=payload.name,
        actor=actor.audit_name,
        correlation_id=new_correlation_id(),
        region=payload.region,
        country=payload.country,
        city=payload.city,
        website=payload.website,
        contact_info=payload.contact_info,
        verification=payload.verification,
        verified_by=payload.verified_by,
        reliability=payload.reliability,
        reliability_provenance=payload.reliability_provenance,
    )


@router.post(
    "/api/suppliers/{supplier_id}/quotes", response_model=SupplierQuoteOut, status_code=201
)
def create_supplier_quote(
    supplier_id: str,
    payload: QuoteCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.SUPPLIER_WRITE)),
) -> SupplierQuoteModel:
    return SourcingService(db).record_quote(
        supplier_id=supplier_id,
        actor=actor.audit_name,
        correlation_id=new_correlation_id(),
        **payload.model_dump(),
    )


@router.post("/api/suppliers/{supplier_id}/capabilities", status_code=201)
def declare_supplier_capability(
    supplier_id: str,
    payload: CapabilityCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.SUPPLIER_WRITE)),
) -> CapabilityOut:
    row = SourcingService(db).declare_capability(
        supplier_id=supplier_id,
        capability=payload.capability.value,
        supported=payload.supported,
        provenance=payload.provenance,
        product_id=payload.product_id,
        source=payload.source,
        note=payload.note,
        actor=actor.audit_name,
        correlation_id=new_correlation_id(),
    )
    return CapabilityOut(
        capability=row.capability,
        supported=row.supported,
        provenance=row.provenance,
        source=row.source,
        note=row.note,
        observed_at=row.observed_at,
        product_specific=row.product_id is not None,
    )


@router.get("/api/products/{product_id}/suppliers", response_model=list[SupplierQuoteDetailOut])
def list_product_suppliers(
    product_id: str, db: Session = Depends(get_db)
) -> list[SupplierQuoteDetailOut]:
    """Las cotizaciones de un producto, con proveedor, capacidades y riesgo.

    Ordenadas por coste de aterrizaje, y **las que no lo tienen van al final**:
    no se pueden ordenar por un número que no existe, y tratarlas como cero las
    pondría las primeras, que es lo contrario de lo que significan.
    """
    quotes = db.query(SupplierQuoteModel).filter_by(product_id=product_id).all()
    quotes.sort(
        key=lambda q: (
            q.total_landed_cost_per_unit is None,
            q.total_landed_cost_per_unit or 0.0,
        )
    )
    return [_detail(q, db) for q in quotes]
