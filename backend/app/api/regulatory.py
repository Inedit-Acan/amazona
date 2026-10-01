"""Requisitos regulatorios declarados, su comprobación y la evidencia de
cumplimiento (Milestone 41, ADR 0019).

Escribir aquí es **declarar un juicio jurídico** —«esta norma se aplica a esta
clase de producto»— y por eso es `REGULATORY_WRITE`: OWNER y ADMIN. Leer lo
declarado es dato de negocio, como el resto de Legal.
"""

import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.actor import Actor
from app.auth.dependencies import authorize
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.costs.service import ApiBudgetExceededError
from app.db.models.compliance_evidence import ComplianceEvidence
from app.db.models.national_anchor import NationalAnchor
from app.db.models.national_transposition import NationalTransposition
from app.db.models.product import Product
from app.db.models.regulatory_anchor import RegulatoryAnchor
from app.db.models.regulatory_requirement import RegulatoryRequirement
from app.db.session import get_db
from app.idempotency.service import IdempotencyKeyHeader, run_idempotent
from app.integrations.regulatory.boe import NationalSourceUnavailableError
from app.integrations.regulatory.eur_lex import AnchorUnavailableError
from app.legal.national import ATTRIBUTION, NOTICE, TranspositionAssessment, official_url
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


class TranspositionIn(BaseModel):
    """Una persona declara qué norma española traspone la directiva del requisito.
    El sistema no la propone ni la busca."""

    national_id: str = Field(min_length=1, max_length=32)
    note: str | None = None


class NationalAnchorOut(BaseModel):
    """Lo que el BOE dijo, tal como lo entregó. **Informativo**: la consolidación y
    el análisis no tienen valor oficial."""

    model_config = ConfigDict(from_attributes=True)

    national_id: str
    provider: str
    provenance: str
    verified_at: datetime.datetime
    recheck_after: datetime.datetime
    consolidated: bool
    informational: bool
    notice: str
    attribution: str
    source_metadata: dict | None
    source_updated_at: str | None
    relations: dict | None
    publication_state: str
    publication_detail: str | None
    publication_url: str | None
    source_urls: list | None


class AssessmentOut(BaseModel):
    """La evaluación **ahora**. Cada capa por separado."""

    state: str
    corroboration: str
    corroboration_reason: str
    ok: bool
    reasons: list[str]
    matching_relations: list[dict]
    flagged_relations: list[dict]


class TranspositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    requirement_id: str
    national_id: str
    #: Siempre `declared`: la relación la sostiene quien la declara.
    provenance: str
    declared_by: str
    note: str | None
    created_at: datetime.datetime
    #: Enlace oficial estable a la disposición, construido del identificador.
    official_url: str = ""
    #: Lo que la fuente exige mostrar junto a sus datos.
    notice: str = NOTICE
    attribution: str = ATTRIBUTION
    anchor: NationalAnchorOut | None = None
    assessment: AssessmentOut | None = None


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
    #: Las transposiciones nacionales estructuradas (Milestone 43). El texto libre
    #: `transposition_reference` de arriba sigue siendo la declaración humana.
    national_transpositions: list[TranspositionOut] = []


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


def _assessment_out(item: TranspositionAssessment) -> AssessmentOut:
    return AssessmentOut(
        state=item.state.value,
        corroboration=item.corroboration.value,
        corroboration_reason=item.corroboration_reason,
        ok=item.ok,
        reasons=list(item.reasons),
        matching_relations=[dict(r) for r in item.matching_relations],
        flagged_relations=[dict(r) for r in item.flagged_relations],
    )


def _transposition_out(
    row: NationalTransposition, celex: str, service: RegulatoryService
) -> TranspositionOut:
    anchor: NationalAnchor | None = service.latest_national_anchor(row.national_id)
    out = TranspositionOut.model_validate(row)
    out.official_url = official_url(row.national_id)
    if anchor is not None:
        out.anchor = NationalAnchorOut.model_validate(anchor)
    out.assessment = _assessment_out(service.assess_transposition_row(row, celex, anchor))
    return out


def _out(row: RegulatoryRequirement, service: RegulatoryService) -> RequirementOut:
    anchor = service.latest_anchor(row.celex)
    out = RequirementOut.model_validate(row)
    out.national_transpositions = [
        _transposition_out(t, row.celex, service) for t in service.active_transpositions(row.id)
    ]
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
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> RegulatoryAnchor:
    """Pregunta a la fuente por la norma de este requisito. Es una llamada
    externa: pasa por el contador de coste y por la matriz de derechos. Con
    `Idempotency-Key`, un reintento no vuelve a salir a la fuente (ni a gastar de su cuota)."""

    def work() -> RegulatoryAnchor:
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

    return run_idempotent(
        db,
        scope="regulatory.verify",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"requirement_id": requirement_id},
        response=response,
        status_code=200,
        response_model=AnchorOut,
        work=work,
    )


@router.post(
    "/api/regulatory-requirements/{requirement_id}/national-transpositions",
    response_model=TranspositionOut,
    status_code=201,
)
def declare_transposition(
    requirement_id: str,
    payload: TranspositionIn,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
) -> TranspositionOut:
    """Una persona declara qué norma española traspone la directiva del requisito
    (Milestone 43, ADR 0021). El sistema no la propone: la verificará contra el BOE."""
    service = RegulatoryService(db)
    row = service.declare_transposition(
        actor=actor.audit_name, requirement_id=requirement_id, **payload.model_dump()
    )
    requirement = db.get(RegulatoryRequirement, requirement_id)
    assert requirement is not None
    return _transposition_out(row, requirement.celex, service)


@router.post("/api/national-transpositions/{transposition_id}/verify", response_model=TranspositionOut)
def verify_transposition(
    transposition_id: str,
    response: Response,
    db: Session = Depends(get_db),
    identity: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
    settings: Settings = Depends(get_settings),
    idempotency_key: IdempotencyKeyHeader = None,
) -> TranspositionOut:
    """Pregunta al BOE por la norma declarada. Es una llamada externa: pasa por el
    contador de coste y por la matriz de derechos. Un fallo no guarda nada. Con
    `Idempotency-Key`, un reintento no vuelve a salir a la fuente."""

    def work() -> TranspositionOut:
        service = RegulatoryService(db)
        row = service.get_transposition(transposition_id)
        requirement = db.get(RegulatoryRequirement, row.requirement_id)
        assert requirement is not None
        try:
            service.verify_national(row.national_id)
        except SourceNotConfiguredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ApiBudgetExceededError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        except NationalSourceUnavailableError as exc:
            # 502: la fuente no contestó bien. No se guarda nada: un fallo no puede
            # leerse después como «la fuente dice que no».
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _transposition_out(row, requirement.celex, service)

    return run_idempotent(
        db,
        scope="national.verify",
        identity=identity,
        client_key=idempotency_key,
        settings=settings,
        payload={"transposition_id": transposition_id},
        response=response,
        status_code=200,
        response_model=TranspositionOut,
        work=work,
    )


@router.post("/api/national-transpositions/{transposition_id}/withdraw", response_model=TranspositionOut)
def withdraw_transposition(
    transposition_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(authorize(ApiAction.REGULATORY_WRITE)),
) -> TranspositionOut:
    service = RegulatoryService(db)
    row = service.withdraw_transposition(transposition_id, actor=actor.audit_name)
    requirement = db.get(RegulatoryRequirement, row.requirement_id)
    assert requirement is not None
    return _transposition_out(row, requirement.celex, service)


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
