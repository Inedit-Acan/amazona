"""Requisitos regulatorios declarados, su comprobación y la evidencia de
cumplimiento (Milestone 41, ADR 0019).

Escribir aquí es **declarar un juicio jurídico** —«esta norma se aplica a esta
clase de producto»— y por eso es `REGULATORY_WRITE`: OWNER y ADMIN. Leer lo
declarado es dato de negocio, como el resto de Legal.
"""

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.errors import NotFoundError
from app.costs.service import ApiBudgetExceededError
from app.db.models.compliance_evidence import ComplianceEvidence
from app.db.models.product import Product
from app.db.models.regulatory_anchor import RegulatoryAnchor
from app.db.models.regulatory_requirement import RegulatoryRequirement
from app.db.session import get_db
from app.integrations.regulatory.eur_lex import AnchorUnavailableError
from app.legal.regulatory import RegulatoryService, SourceNotConfiguredError, anchor_state_of
from app.legal.requirements import existence_of
from app.permissions.policies import ApiAction

router = APIRouter(tags=["regulatory"])


class RequirementIn(BaseModel):
    product_scope: str = Field(min_length=1, max_length=128)
    jurisdiction: str = "eu"
    celex: str
    regulation: str = Field(min_length=1, max_length=255)
    requirement: str = Field(min_length=1)
    kind: str = "obligation"
    reference: str | None = None
    #: Quién sostiene la aplicabilidad. Nunca la fuente: solo `declared` o
    #: `third_party_verified` (con emisor).
    applicability_provenance: str = "declared"
    applicability_source: str | None = None
    transposition_reference: str | None = None
    transposition_provenance: str | None = None
    transposition_source: str | None = None
    note: str | None = None


class AnchorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    celex: str
    provider: str
    provenance: str
    verified_at: datetime.datetime
    recheck_after: datetime.datetime
    found: bool
    in_force: bool | None
    act_type: str
    act_type_code: str | None
    eli: str | None
    document_date: str | None
    source_effective_from: list | None
    source_effective_to: str | None
    source_url: str


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_scope: str
    jurisdiction: str
    celex: str
    regulation: str
    reference: str | None
    requirement: str
    kind: str
    applicability_provenance: str
    applicability_source: str | None
    declared_by: str
    transposition_reference: str | None
    transposition_provenance: str | None
    transposition_source: str | None
    note: str | None
    created_at: datetime.datetime
    #: Lo que la fuente dijo la última vez, o `null` si nunca se comprobó.
    anchor: AnchorOut | None = None
    #: La situación de la comprobación **ahora**: `never_checked`, `stale`,
    #: `verified_in_force`… Es independiente de la aplicabilidad.
    existence: str = "never_checked"


class EvidenceIn(BaseModel):
    requirement_id: str
    provenance: str = "declared"
    source: str | None = None
    reference: str | None = None
    valid_until: datetime.date | None = None
    note: str | None = None


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    requirement_id: str
    provenance: str
    source: str | None
    reference: str | None
    valid_until: datetime.date | None
    declared_by: str
    note: str | None
    created_at: datetime.datetime


def _out(row: RegulatoryRequirement, service: RegulatoryService) -> RequirementOut:
    anchor = service.latest_anchor(row.celex)
    out = RequirementOut.model_validate(row)
    if anchor is not None:
        out.anchor = AnchorOut.model_validate(anchor)
        out.existence = existence_of(
            anchor_state_of(anchor), datetime.datetime.now(datetime.UTC)
        ).value
    return out


@router.get("/api/regulatory-requirements", response_model=list[RequirementOut])
def list_requirements(db: Session = Depends(get_db)) -> list[RequirementOut]:
    """Los requisitos activos. Los sustituidos y retirados no salen aquí, pero
    siguen en la base de datos y en la auditoría."""
    service = RegulatoryService(db)
    return [_out(row, service) for row in service.list_active()]


@router.post("/api/regulatory-requirements", response_model=RequirementOut, status_code=201)
def declare_requirement(
    payload: RequirementIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
) -> RequirementOut:
    service = RegulatoryService(db)
    row = service.declare(actor=actor.audit_name, **payload.model_dump())
    return _out(row, service)


@router.post(
    "/api/regulatory-requirements/{requirement_id}/supersede",
    response_model=RequirementOut,
    status_code=201,
)
def supersede_requirement(
    requirement_id: str,
    payload: RequirementIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
) -> RequirementOut:
    """Modificar un requisito es sustituirlo: el anterior queda marcado y la
    evidencia que tenía **no** se traslada."""
    service = RegulatoryService(db)
    row = service.supersede(requirement_id, actor=actor.audit_name, **payload.model_dump())
    return _out(row, service)


@router.post("/api/regulatory-requirements/{requirement_id}/withdraw", response_model=RequirementOut)
def withdraw_requirement(
    requirement_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
) -> RequirementOut:
    service = RegulatoryService(db)
    row = service.withdraw(requirement_id, actor=actor.audit_name)
    return _out(row, service)


@router.post("/api/regulatory-requirements/{requirement_id}/verify", response_model=AnchorOut)
def verify_requirement(
    requirement_id: str,
    db: Session = Depends(get_db),
    _actor: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
) -> RegulatoryAnchor:
    """Pregunta a la fuente por la norma de este requisito. Es una llamada
    externa: pasa por el contador de coste y por la matriz de derechos."""
    service = RegulatoryService(db)
    row = db.get(RegulatoryRequirement, requirement_id)
    if row is None:
        raise NotFoundError(f"regulatory requirement {requirement_id} not found")
    try:
        return service.verify(row.celex)
    except SourceNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApiBudgetExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AnchorUnavailableError as exc:
        # 502: la fuente no contestó bien. No se guarda nada: un fallo no puede
        # leerse después como «la fuente dijo que no existe».
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/products/{product_id}/compliance-evidence", response_model=list[EvidenceOut])
def list_evidence(product_id: str, db: Session = Depends(get_db)) -> list[ComplianceEvidence]:
    if db.get(Product, product_id) is None:
        raise NotFoundError(f"product {product_id} not found")
    return (
        db.query(ComplianceEvidence)
        .filter_by(product_id=product_id)
        .order_by(ComplianceEvidence.created_at.desc())
        .all()
    )


@router.post(
    "/api/products/{product_id}/compliance-evidence", response_model=EvidenceOut, status_code=201
)
def declare_evidence(
    product_id: str,
    payload: EvidenceIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
) -> ComplianceEvidence:
    return RegulatoryService(db).add_evidence(
        actor=actor.audit_name, product_id=product_id, **payload.model_dump()
    )
