"""Declarar requisitos, comprobarlos contra la fuente y aportar evidencia
(Milestone 41, ADR 0019). La parte con base de datos; las reglas viven en
`app.legal.requirements`.

Nada de aquí lo hace «el sistema por iniciativa propia»: declarar aplicabilidad,
sustituirla, retirarla y aportar evidencia son actos de una persona con permiso
(`ApiAction.REGULATORY_WRITE`, solo OWNER y ADMIN), y cada uno deja su fila de
auditoría. Lo único que hace el sistema solo es **preguntar a la fuente** por una
norma que alguien ya nombró.
"""

import datetime
import logging
from typing import cast

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AmazonaError, NotFoundError, ValidationError
from app.core.ids import new_correlation_id
from app.core.text import fold
from app.costs.service import ApiBudgetExceededError, CostMeter
from app.db.models.audit import AuditLog
from app.db.models.compliance_evidence import ComplianceEvidence
from app.db.models.product import Product
from app.db.models.regulatory_anchor import RegulatoryAnchor
from app.db.models.regulatory_requirement import RegulatoryRequirement
from app.integrations.ports import IntegrationDomain, ProviderKind, RegulatoryAnchorSource, SourceAnchor
from app.integrations.registry import ProviderRegistry
from app.integrations.regulatory.eur_lex import AnchorUnavailableError, validate_celex
from app.integrations.usage_rights import UsageRight, permits
from app.legal.requirements import (
    SUPPORTED_JURISDICTION,
    ActType,
    AnchorState,
    ComplianceEvidenceItem,
    DeclaredRequirement,
    RequirementKind,
)
from app.sourcing.provenance import SupplierFactProvenance

logger = logging.getLogger(__name__)

#: Códigos de tipo de acto de la fuente que son directamente aplicables o requieren
#: transposición. Un código que no está aquí es `OTHER`: no se sabe, y no se supone.
_REGULATION_CODES = frozenset({"REG", "REG_IMPL", "REG_DEL", "REG_FINANC"})
_DIRECTIVE_CODES = frozenset({"DIR", "DIR_IMPL", "DIR_DEL", "DIR_FINANC"})


def act_type_for(code: str | None) -> ActType:
    if code is None:
        return ActType.UNKNOWN
    if code in _REGULATION_CODES:
        return ActType.REGULATION
    if code in _DIRECTIVE_CODES:
        return ActType.DIRECTIVE
    return ActType.OTHER


class SourceNotConfiguredError(AmazonaError):
    """No hay una fuente real de normativa configurada. En desarrollo el
    proveedor por defecto es el mock, que no ancla nada."""


def anchor_state_of(row: RegulatoryAnchor) -> AnchorState:
    return AnchorState(
        found=row.found,
        in_force=row.in_force,
        act_type=ActType(row.act_type),
        verified_at=_aware(row.verified_at),
        recheck_after=_aware(row.recheck_after),
        source=row.provider,
        eli=row.eli,
        source_effective_from=tuple(row.source_effective_from or ()),
        source_effective_to=row.source_effective_to,
    )


def _aware(value: datetime.datetime) -> datetime.datetime:
    """SQLite devuelve fechas sin zona; todo lo que se guarda es UTC."""
    return value if value.tzinfo else value.replace(tzinfo=datetime.UTC)


def requirement_of(row: RegulatoryRequirement) -> DeclaredRequirement:
    return DeclaredRequirement(
        id=row.id,
        product_scope=row.product_scope,
        jurisdiction=row.jurisdiction,
        celex=row.celex,
        regulation=row.regulation,
        requirement=row.requirement,
        kind=RequirementKind(row.kind),
        applicability_provenance=SupplierFactProvenance(row.applicability_provenance),
        declared_by=row.declared_by,
        reference=row.reference,
        applicability_source=row.applicability_source,
        transposition_reference=row.transposition_reference,
        transposition_provenance=(
            SupplierFactProvenance(row.transposition_provenance)
            if row.transposition_provenance
            else None
        ),
        transposition_source=row.transposition_source,
    )


def evidence_item_of(row: ComplianceEvidence) -> ComplianceEvidenceItem:
    return ComplianceEvidenceItem(
        provenance=SupplierFactProvenance(row.provenance),
        declared_by=row.declared_by,
        source=row.source,
        reference=row.reference,
        valid_until=row.valid_until,
    )


class RegulatoryService:
    def __init__(
        self,
        db: Session,
        *,
        source: RegulatoryAnchorSource | None = None,
        settings: Settings | None = None,
        now: datetime.datetime | None = None,
    ) -> None:
        self._db = db
        self._source = source
        self._settings = settings or get_settings()
        self._now = now

    def _clock(self) -> datetime.datetime:
        return self._now or datetime.datetime.now(datetime.UTC)

    # --- Requisitos: los declara una persona --------------------------------

    def declare(
        self,
        *,
        actor: str,
        product_scope: str,
        jurisdiction: str,
        celex: str,
        regulation: str,
        requirement: str,
        kind: str,
        reference: str | None = None,
        applicability_provenance: str = "declared",
        applicability_source: str | None = None,
        transposition_reference: str | None = None,
        transposition_provenance: str | None = None,
        transposition_source: str | None = None,
        note: str | None = None,
    ) -> RegulatoryRequirement:
        row = self._build(
            actor=actor,
            product_scope=product_scope,
            jurisdiction=jurisdiction,
            celex=celex,
            regulation=regulation,
            requirement=requirement,
            kind=kind,
            reference=reference,
            applicability_provenance=applicability_provenance,
            applicability_source=applicability_source,
            transposition_reference=transposition_reference,
            transposition_provenance=transposition_provenance,
            transposition_source=transposition_source,
            note=note,
        )
        self._db.add(row)
        self._db.flush()
        self._audit(actor, "regulatory_requirement.declare", row, before=None)
        self._db.commit()
        return row

    def supersede(self, requirement_id: str, *, actor: str, **fields: object) -> RegulatoryRequirement:
        """Modificar es **sustituir**: la fila anterior se conserva marcada, y la
        nueva la reemplaza. Lo que Legal concluyó con la anterior sigue siendo
        reconstruible."""
        old = self._get_active(requirement_id)
        new = self._build(actor=actor, **cast(dict, fields))
        self._db.add(new)
        self._db.flush()
        old.superseded_by_id = new.id
        self._audit(
            actor, "regulatory_requirement.supersede", new, before={"superseded_id": old.id}
        )
        self._db.commit()
        return new

    def withdraw(self, requirement_id: str, *, actor: str) -> RegulatoryRequirement:
        row = self._get_active(requirement_id)
        row.withdrawn_at = self._clock()
        self._audit(actor, "regulatory_requirement.withdraw", row, before={"withdrawn": False})
        self._db.commit()
        return row

    def _build(self, *, actor: str, **f: object) -> RegulatoryRequirement:
        jurisdiction = str(f["jurisdiction"]).strip().lower()
        if jurisdiction != SUPPORTED_JURISDICTION:
            raise ValidationError(
                f"only jurisdiction {SUPPORTED_JURISDICTION!r} can be anchored: EUR-Lex publishes "
                "EU law and this milestone has no national source"
            )
        celex = validate_celex(str(f["celex"]))
        transposition_ref = str(f["transposition_reference"]).strip() if f.get("transposition_reference") else None
        # Construir el objeto del dominio antes de guardarlo es lo que rechaza un
        # `third_party_verified` sin emisor, una procedencia que no puede tener un
        # hecho legal y un requisito sin alcance ni declarante.
        domain = DeclaredRequirement(
            id="pending",
            product_scope=str(f["product_scope"]),
            jurisdiction=jurisdiction,
            celex=celex,
            regulation=str(f["regulation"]),
            requirement=str(f["requirement"]),
            kind=_enum(RequirementKind, f["kind"], "kind"),
            applicability_provenance=_enum(
                SupplierFactProvenance, f.get("applicability_provenance") or "declared", "provenance"
            ),
            declared_by=actor,
            reference=_clean(f.get("reference")),
            applicability_source=_clean(f.get("applicability_source")),
            transposition_reference=transposition_ref,
            transposition_provenance=(
                _enum(SupplierFactProvenance, f["transposition_provenance"], "provenance")
                if transposition_ref and f.get("transposition_provenance")
                else (SupplierFactProvenance.DECLARED if transposition_ref else None)
            ),
            transposition_source=_clean(f.get("transposition_source")),
        )
        if not domain.requirement.strip() or not domain.regulation.strip():
            raise ValidationError("a requirement needs its regulation name and its text")
        return RegulatoryRequirement(
            product_scope=domain.product_scope.strip(),
            scope_key=fold(domain.product_scope),
            jurisdiction=domain.jurisdiction,
            celex=domain.celex,
            regulation=domain.regulation.strip(),
            reference=domain.reference,
            requirement=domain.requirement.strip(),
            kind=domain.kind.value,
            applicability_provenance=domain.applicability_provenance.value,
            applicability_source=domain.applicability_source,
            declared_by=domain.declared_by,
            transposition_reference=domain.transposition_reference,
            transposition_provenance=(
                domain.transposition_provenance.value if domain.transposition_provenance else None
            ),
            transposition_source=domain.transposition_source,
            note=_clean(f.get("note")),
        )

    def _get_active(self, requirement_id: str) -> RegulatoryRequirement:
        row = self._db.get(RegulatoryRequirement, requirement_id)
        if row is None:
            raise NotFoundError(f"regulatory requirement {requirement_id} not found")
        if row.withdrawn_at is not None or row.superseded_by_id is not None:
            raise ValidationError(
                f"regulatory requirement {requirement_id} is no longer active: it was withdrawn "
                "or superseded"
            )
        return row

    def list_active(self) -> list[RegulatoryRequirement]:
        return (
            self._db.query(RegulatoryRequirement)
            .filter(
                RegulatoryRequirement.withdrawn_at.is_(None),
                RegulatoryRequirement.superseded_by_id.is_(None),
            )
            .order_by(RegulatoryRequirement.created_at.desc())
            .all()
        )

    def active_for(self, *, scope: str, jurisdiction: str) -> list[RegulatoryRequirement]:
        """Emparejamiento por clave determinista: dos alcances son el mismo o no."""
        return (
            self._db.query(RegulatoryRequirement)
            .filter(
                RegulatoryRequirement.scope_key == fold(scope),
                RegulatoryRequirement.jurisdiction == jurisdiction.strip().lower(),
                RegulatoryRequirement.withdrawn_at.is_(None),
                RegulatoryRequirement.superseded_by_id.is_(None),
            )
            .order_by(RegulatoryRequirement.created_at)
            .all()
        )

    # --- Evidencia de cumplimiento -----------------------------------------

    def add_evidence(
        self,
        *,
        actor: str,
        product_id: str,
        requirement_id: str,
        provenance: str = "declared",
        source: str | None = None,
        reference: str | None = None,
        valid_until: datetime.date | None = None,
        note: str | None = None,
    ) -> ComplianceEvidence:
        if self._db.get(Product, product_id) is None:
            raise NotFoundError(f"product {product_id} not found")
        self._get_active(requirement_id)
        # El objeto del dominio valida procedencia y emisor.
        ComplianceEvidenceItem(
            provenance=_enum(SupplierFactProvenance, provenance, "provenance"),
            declared_by=actor,
            source=_clean(source),
            reference=_clean(reference),
            valid_until=valid_until,
        )
        row = ComplianceEvidence(
            product_id=product_id,
            requirement_id=requirement_id,
            provenance=provenance,
            source=_clean(source),
            reference=_clean(reference),
            valid_until=valid_until,
            declared_by=actor,
            note=_clean(note),
        )
        self._db.add(row)
        self._db.add(
            AuditLog(
                actor=actor,
                action="compliance_evidence.declare",
                resource=f"compliance_evidence:{product_id}:{requirement_id}",
                before=None,
                after={"provenance": provenance, "source": row.source, "reference": row.reference},
                correlation_id=new_correlation_id(),
            )
        )
        self._db.commit()
        return row

    # --- Anclas: lo único que hace el sistema por su cuenta ------------------

    def latest_anchor(self, celex: str) -> RegulatoryAnchor | None:
        return (
            self._db.query(RegulatoryAnchor)
            .filter_by(celex=celex)
            .order_by(RegulatoryAnchor.verified_at.desc())
            .first()
        )

    def _resolve_source(self, correlation_id: str) -> RegulatoryAnchorSource:
        if self._source is not None:
            return self._source
        registry = ProviderRegistry(self._settings)
        if registry.kind_for(IntegrationDomain.REGULATORY) is not ProviderKind.REAL:
            raise SourceNotConfiguredError(
                "no real regulatory source is configured (REGULATORY_PROVIDER is not 'real'): "
                "nothing can be anchored, and nothing is assumed"
            )
        meter = CostMeter(
            self._db, correlation_id=correlation_id, limits=self._settings.spend_limits
        )
        return cast(
            RegulatoryAnchorSource, registry.resolve(IntegrationDomain.REGULATORY, meter=meter)
        )

    def verify(self, celex: str, *, correlation_id: str | None = None) -> RegulatoryAnchor:
        """Pregunta a la fuente por una norma **ya declarada** y guarda lo que
        dijo. Falla en voz alta si no pudo preguntar: no guarda nada, para que un
        fallo no se lea después como «la fuente dijo que no».

        Lanza `AnchorUnavailableError`, `ApiBudgetExceededError` o
        `SourceNotConfiguredError`."""
        celex = validate_celex(celex)
        correlation_id = correlation_id or new_correlation_id()
        source = self._resolve_source(correlation_id)
        provider = getattr(source, "name", "eur-lex-cellar")
        # «Tener el dato no es tener permiso» (ADR 0015): sin derecho a guardarlo
        # no se guarda ni se pregunta.
        if not permits(provider, UsageRight.STORAGE):
            raise SourceNotConfiguredError(
                f"the usage rights of {provider} do not allow storing what it returns"
            )
        anchor = source.lookup(celex)
        row = self._store(anchor)
        self._db.add(
            AuditLog(
                actor=f"system:{provider}",
                action="regulatory_anchor.verify",
                resource=f"regulatory_anchor:{celex}",
                before=None,
                after={"found": row.found, "in_force": row.in_force, "verified_at": row.verified_at.isoformat()},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return row

    def _store(self, anchor: SourceAnchor) -> RegulatoryAnchor:
        verified_at = anchor.retrieved_at
        row = RegulatoryAnchor(
            celex=anchor.celex,
            provider=anchor.provider,
            provenance=SupplierFactProvenance.THIRD_PARTY_VERIFIED.value,
            verified_at=verified_at,
            recheck_after=verified_at + datetime.timedelta(days=self._settings.legal_anchor_recheck_days),
            found=anchor.found,
            in_force=anchor.in_force,
            act_type=act_type_for(anchor.act_type_code).value,
            act_type_code=anchor.act_type_code,
            eli=anchor.eli,
            document_date=anchor.document_date,
            source_effective_from=list(anchor.entry_into_force) or None,
            source_effective_to=anchor.end_of_validity,
            source_url=anchor.source_url,
            evidence=anchor.raw or None,
        )
        self._db.add(row)
        self._db.flush()
        return row

    def ensure_fresh(
        self, celex: str, *, correlation_id: str
    ) -> tuple[RegulatoryAnchor | None, str | None]:
        """El ancla vigente de una norma, recomprobándola si ha vencido la
        política. Devuelve `(ancla, motivo_del_fallo)`.

        Si no se puede preguntar, se conserva el ancla anterior —que seguirá
        marcada como vencida— y se devuelve el motivo: el análisis pedirá revisión,
        no concluirá nada.
        """
        current = self.latest_anchor(celex)
        now = self._clock()
        if current is not None and now <= _aware(current.recheck_after):
            return current, None
        try:
            return self.verify(celex, correlation_id=correlation_id), None
        except (AnchorUnavailableError, ApiBudgetExceededError, SourceNotConfiguredError) as exc:
            logger.warning("could not check %s: %s", celex, exc)
            return current, str(exc)

    def evidence_for(self, product_id: str, requirement_id: str) -> list[ComplianceEvidence]:
        return (
            self._db.query(ComplianceEvidence)
            .filter_by(product_id=product_id, requirement_id=requirement_id)
            .order_by(ComplianceEvidence.created_at)
            .all()
        )

    def _audit(self, actor: str, action: str, row: RegulatoryRequirement, *, before: dict | None) -> None:
        self._db.add(
            AuditLog(
                actor=actor,
                action=action,
                resource=f"regulatory_requirement:{row.id}",
                before=before,
                after={
                    "product_scope": row.product_scope,
                    "jurisdiction": row.jurisdiction,
                    "celex": row.celex,
                    "kind": row.kind,
                    "applicability_provenance": row.applicability_provenance,
                },
                correlation_id=new_correlation_id(),
            )
        )


def _enum(cls, value: object, field: str):
    """Un valor que no está en el catálogo cerrado es un 422, no un 500."""
    try:
        return cls(str(value))
    except ValueError as exc:
        allowed = ", ".join(m.value for m in cls)
        raise ValidationError(f"{field} {value!r} is not one of: {allowed}") from exc


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
