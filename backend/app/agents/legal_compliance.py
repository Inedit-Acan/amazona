from pydantic import BaseModel

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.ai.mock_regulatory_directory import MockRegulatoryDirectory
from app.legal.terms_template import generate_terms_and_conditions


class LegalComplianceInput(BaseModel):
    category: str
    market: str
    product_name: str
    certification_available: bool = False
    supplier_verified: bool | None = None
    origin_region: str | None = None


class LegalComplianceAgent(Agent):
    """Fase 3, Agente 4: analyzes regulatory requirements/certifications,
    known legal risks, and recent regulatory changes for a product
    category in a target market, and drafts a T&C template — unlike
    LegalAgent, which validates a single already-given
    restricted/certification flag set within an objective's task graph.
    See ADR 0004. Consumes real product/sourcing data resolved by
    LegalComplianceService; it never touches the DB itself."""

    capability = "legal_compliance_analysis"
    input_schema = LegalComplianceInput

    def __init__(self, directory: MockRegulatoryDirectory | None = None) -> None:
        self._directory = directory or MockRegulatoryDirectory()

    def run(self, task_input: dict) -> AgentResult:
        params = LegalComplianceInput.model_validate(task_input)
        requirements = self._directory.get_requirements(category=params.category, market=params.market)

        if requirements is None:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[
                    f"insufficient regulatory data for category {params.category!r} in market {params.market!r}"
                ],
                assumptions=[],
                data={"restricted": None},
            )

        restricted = requirements["restricted"]
        required_certifications = requirements["required_certifications"]
        known_risks = list(requirements["known_risks"])
        recent_changes = requirements["recent_changes"]
        requires_certification = bool(required_certifications)

        blocked = restricted and requires_certification and not params.certification_available

        if blocked:
            status = AgentResultStatus.BLOCKED
            recommendation = "NO_GO"
            confidence = 0.95
        elif requires_certification and not params.certification_available:
            status = AgentResultStatus.COMPLETED
            recommendation = "REVIEW"
            confidence = 0.85
        else:
            status = AgentResultStatus.COMPLETED
            recommendation = "GO"
            confidence = 0.85

        risks = list(known_risks)
        if params.supplier_verified is False and params.origin_region:
            risks.append(
                f"cross-border compliance risk: unverified supplier sourced from {params.origin_region}"
            )
        if recent_changes:
            descriptions = "; ".join(c["description"] for c in recent_changes)
            risks.append(f"recent regulatory change(s) may affect compliance: {descriptions}")

        terms_and_conditions = generate_terms_and_conditions(
            category=params.category, market=params.market, product_name=params.product_name
        )

        return AgentResult(
            status=status,
            recommendation=recommendation,
            confidence=confidence,
            evidence=[
                f"category {params.category} in market {params.market}: "
                f"{'restricted' if restricted else 'not restricted'}",
                f"required certifications: {', '.join(required_certifications) or 'none'}",
            ],
            risks=risks,
            assumptions=[
                "regulatory dataset and terms-and-conditions template are simulated placeholders, "
                "not real legal research or advice"
            ],
            data={
                "restricted": restricted,
                "required_certifications": required_certifications,
                "known_risks": known_risks,
                "recent_changes": recent_changes,
                "terms_and_conditions": terms_and_conditions,
            },
        )
