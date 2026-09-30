import datetime

from sqlalchemy.orm import Session

from app.agents.legal_compliance import LegalComplianceAgent
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.integrations.ports import IntegrationDomain, ProviderKind
from app.integrations.registry import ProviderRegistry
from app.legal.national import ATTRIBUTION, NOTICE, official_url
from app.legal.regulatory import (
    RegulatoryService,
    anchor_state_of,
    evidence_item_of,
    requirement_of,
)
from app.legal.requirements import (
    LEGAL_CONFIDENCE_CEILING,
    LegalStatus,
    RequirementAssessment,
    ScopeAssessment,
    assess_requirement,
    assess_scope,
)
from app.sourcing.service import supplier_identity_verified

LEGAL_AGENT_ACTOR = "agent-legal-compliance-1"

#: Lo que acompaña a **cualquier** resultado de Legal, se llame como se llame el
#: estado. Ninguna respuesta del análisis real puede leerse como «producto legal».
DISCLAIMER = (
    "Legal detects and structures requirements; it does not replace professional legal review. "
    "PASS only means that, within the declared scope and the declared, checked requirements, no "
    "blocker was found. Requirements nobody declared have not been looked at."
)


class LegalComplianceService:
    """Resolves a Product to its real category (and, when a supplier has
    already been sourced for it, the most recent SupplierQuote's origin
    region/verification), runs the Legal Compliance agent, and persists
    the report — same reconstructability standard as
    ResearchService/SourcingService/EconomicAnalysisService. Unlike the
    Agent 3 flow, a prior SupplierQuote is optional: a product can be
    screened for legal/compliance requirements before sourcing exists.

    Con `REGULATORY_PROVIDER=real` (Milestone 41, ADR 0019) el análisis ya no lo
    hace el agente sobre un directorio: se evalúan los requisitos que una persona
    **declaró** para el alcance del producto, anclados contra la fuente. El mock
    sigue por el camino de siempre y con las mismas cifras.
    """

    def __init__(
        self,
        db: Session,
        agent: LegalComplianceAgent | None = None,
        regulatory: RegulatoryService | None = None,
    ) -> None:
        self._db = db
        self._agent_override = agent
        self._regulatory = regulatory

    def run_analysis(
        self,
        *,
        product_id: str,
        market: str,
        correlation_id: str,
        certification_available: bool = False,
    ) -> LegalAnalysis:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

        quote = (
            self._db.query(SupplierQuote)
            .filter_by(product_id=product_id)
            .order_by(SupplierQuote.created_at.desc())
            .first()
        )

        if self._agent_override is None and self._uses_real_source():
            analysis = self._real_analysis(
                product=product,
                quote=quote,
                market=market,
                correlation_id=correlation_id,
                certification_available=certification_available,
            )
        else:
            analysis = self._mock_analysis(
                product=product,
                quote=quote,
                market=market,
                correlation_id=correlation_id,
                certification_available=certification_available,
            )

        self._db.add(analysis)
        self._db.add(
            AuditLog(
                actor=LEGAL_AGENT_ACTOR,
                action="legal.run",
                resource=f"legal:{correlation_id}",
                before=None,
                after={"product_id": product_id, "market": market},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return analysis

    @staticmethod
    def _uses_real_source() -> bool:
        kind = ProviderRegistry(get_settings()).kind_for(IntegrationDomain.REGULATORY)
        return kind is ProviderKind.REAL

    # --- Camino simulado: exactamente como hasta el Milestone 40 ------------

    def _mock_analysis(
        self,
        *,
        product: Product,
        quote: SupplierQuote | None,
        market: str,
        correlation_id: str,
        certification_available: bool,
    ) -> LegalAnalysis:
        agent = self._agent_override or LegalComplianceAgent()
        supplier = self._db.get(Supplier, quote.supplier_id) if quote else None
        result = agent.run(
            {
                "category": product.category,
                "market": market,
                "product_name": product.name,
                "certification_available": certification_available,
                "supplier_verified": (
                    supplier_identity_verified(self._db, quote) if quote else None
                ),
                "origin_region": supplier.region if supplier else None,
            }
        )
        return LegalAnalysis(
            product_id=product.id,
            supplier_quote_id=quote.id if quote else None,
            market=market,
            restricted=result.data.get("restricted"),
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={**result.data, "risks": result.risks, "evidence": result.evidence},
            correlation_id=correlation_id,
        )

    # --- Camino real: requisitos declarados, anclados en la fuente ----------

    def _real_analysis(
        self,
        *,
        product: Product,
        quote: SupplierQuote | None,
        market: str,
        correlation_id: str,
        certification_available: bool,
    ) -> LegalAnalysis:
        regulatory = self._regulatory or RegulatoryService(self._db)
        now = datetime.datetime.now(datetime.UTC)

        assessments: list[RequirementAssessment] = []
        source_errors: dict[str, str] = {}
        source_down = False
        national_down = False
        for row in regulatory.active_for(scope=product.category, jurisdiction=market):
            if source_down:
                # Una vez que la fuente ha fallado en este análisis no se insiste
                # con cada requisito: un trabajo tiene un arriendo de 60 s (ADR
                # 0009) y varios timeouts seguidos lo agotarían. Se usa lo que ya
                # hubiera guardado, que quedará marcado como vencido o sin comprobar.
                anchor_row = regulatory.latest_anchor(row.celex)
                source_errors[row.celex] = "not asked: the source already failed in this analysis"
            else:
                anchor_row, failure = regulatory.ensure_fresh(
                    row.celex, correlation_id=correlation_id
                )
                if failure:
                    source_errors[row.celex] = failure
                    source_down = True
            evidence = [evidence_item_of(e) for e in regulatory.evidence_for(product.id, row.id)]

            # Transposiciones nacionales declaradas (Milestone 43): igual que con
            # EUR-Lex, si el BOE falla una vez no se insiste con cada norma.
            transpositions = []
            for transposition in regulatory.active_transpositions(row.id):
                if national_down:
                    national_row = regulatory.latest_national_anchor(transposition.national_id)
                    source_errors[transposition.national_id] = (
                        "not asked: the source already failed in this analysis"
                    )
                else:
                    national_row, failure = regulatory.ensure_fresh_national(
                        transposition.national_id, correlation_id=correlation_id
                    )
                    if failure:
                        source_errors[transposition.national_id] = failure
                        national_down = True
                transpositions.append(
                    regulatory.assess_transposition_row(transposition, row.celex, national_row)
                )

            assessments.append(
                assess_requirement(
                    requirement_of(row),
                    anchor_state_of(anchor_row) if anchor_row else None,
                    evidence,
                    now=now,
                    transpositions=transpositions,
                )
            )

        scope = assess_scope(jurisdiction=market, scope=product.category, assessments=assessments)
        return LegalAnalysis(
            product_id=product.id,
            supplier_quote_id=quote.id if quote else None,
            market=market,
            # Solo se afirma «restringido» cuando hay un bloqueo. No se afirma lo
            # contrario: que nadie haya declarado una restricción no es que no
            # exista ninguna.
            restricted=True if scope.status is LegalStatus.BLOCKED else None,
            recommendation=scope.recommendation,
            confidence=scope.confidence,
            data=_real_data(
                scope,
                product_scope=product.category,
                jurisdiction=market,
                source_errors=source_errors,
                certification_flag_ignored=certification_available,
            ),
            correlation_id=correlation_id,
        )


def _real_data(
    scope: ScopeAssessment,
    *,
    product_scope: str,
    jurisdiction: str,
    source_errors: dict[str, str],
    certification_flag_ignored: bool,
) -> dict:
    """La salida real de Legal. Las tres cuestiones —aplicabilidad, existencia,
    evidencia— salen **separadas** en cada requisito."""
    return {
        "legal_status": scope.status.value,
        "basis": "declared_requirements_anchored_to_source",
        "product_scope": product_scope,
        "jurisdiction": jurisdiction,
        "reasons": list(scope.reasons),
        "requirements": [_requirement_data(a) for a in scope.requirements],
        "source_errors": source_errors,
        "disclaimer": DISCLAIMER,
        "confidence_rule": (
            "internal rule, not calibrated: the result's confidence is the ceiling of its weakest "
            "link. Ceilings by provenance: "
            + ", ".join(f"{p.value}={c}" for p, c in LEGAL_CONFIDENCE_CEILING.items())
        ),
        # Lo que el flag heredado ya no significa: un booleano no es evidencia de
        # ningún requisito concreto. Se dice, en vez de ignorarlo en silencio.
        "certification_flag_ignored": certification_flag_ignored,
        "risks": list(scope.reasons),
        "evidence": [
            f"{a.requirement.regulation} ({a.requirement.celex}): existence={a.existence.value}, "
            f"compliance={a.compliance.value}"
            for a in scope.requirements
        ],
    }


def _requirement_data(a: RequirementAssessment) -> dict:
    r = a.requirement
    anchor = a.anchor
    return {
        "requirement_id": r.id,
        "celex": r.celex,
        "regulation": r.regulation,
        "reference": r.reference,
        "requirement": r.requirement,
        "kind": r.kind.value,
        "status": a.status.value,
        "reasons": list(a.reasons),
        "confidence": a.confidence,
        "weakest_link": a.weakest_link.value,
        # 1. Aplicabilidad: la declara una persona.
        "applicability": {
            "provenance": r.applicability_provenance.value,
            "source": r.applicability_source,
            "declared_by": r.declared_by,
        },
        # 2. Existencia y vigencia: la comprueba la fuente.
        "existence": {
            "state": a.existence.value,
            "provider": anchor.source if anchor else None,
            "verified_at": anchor.verified_at.isoformat() if anchor else None,
            "recheck_after": anchor.recheck_after.isoformat() if anchor else None,
            "in_force": anchor.in_force if anchor else None,
            "act_type": anchor.act_type.value if anchor else None,
            "eli": anchor.eli if anchor else None,
            "source_effective_from": list(anchor.source_effective_from) if anchor else [],
            "source_effective_to": anchor.source_effective_to if anchor else None,
        },
        # 3. Evidencia de cumplimiento del producto.
        "compliance": {"state": a.compliance.value},
        # Lo que una persona escribió en texto libre (M41): declaración humana y pista
        # de auditoría. No basta para `PASS`.
        "transposition": {
            "reference": r.transposition_reference,
            "provenance": r.transposition_provenance.value if r.transposition_provenance else None,
        },
        # Transposiciones nacionales estructuradas (M43). Cada una separa las capas:
        # norma declarada, estado según la fuente, publicación oficial, relación con
        # la norma UE. **Consolidación y análisis son meramente informativos.**
        "national": [_national_data(t) for t in a.national],
    }


def _national_data(t) -> dict:  # type: ignore[no-untyped-def]
    anchor = t.anchor
    metadata = anchor.metadata if anchor else {}
    return {
        "national_id": t.national_id,
        "state": t.state.value,
        "ok": t.ok,
        "reasons": list(t.reasons),
        "declared": {"provenance": "declared"},
        "source_status": {
            "consolidated": anchor.consolidated if anchor else None,
            "title": metadata.get("titulo"),
            "fecha_publicacion": metadata.get("fecha_publicacion"),
            "fecha_vigencia": metadata.get("fecha_vigencia"),
            "estatus_derogacion": metadata.get("estatus_derogacion"),
            "fecha_derogacion": metadata.get("fecha_derogacion"),
            "estatus_anulacion": metadata.get("estatus_anulacion"),
            "vigencia_agotada": metadata.get("vigencia_agotada"),
            "estado_consolidacion": metadata.get("estado_consolidacion"),
            "fecha_actualizacion": metadata.get("fecha_actualizacion"),
            "url_eli": metadata.get("url_eli"),
            "verified_at": anchor.verified_at.isoformat() if anchor else None,
            "recheck_after": anchor.recheck_after.isoformat() if anchor else None,
        },
        "publication": {
            "state": anchor.publication_state if anchor else None,
            "official_url": official_url(t.national_id),
        },
        "eu_relation": {
            "corroboration": t.corroboration.value,
            "reason": t.corroboration_reason,
            "matching_relations": list(t.matching_relations),
            "flagged_relations": list(t.flagged_relations),
        },
        "informational": True,
        "notice": NOTICE,
        "attribution": ATTRIBUTION,
    }
