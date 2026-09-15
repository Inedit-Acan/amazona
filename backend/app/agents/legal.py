from app.agents.base import Agent, AgentResult


class LegalAgent(Agent):
    """V1: deterministic legal/compliance screening from structured input
    fixtures. Informational only; not a substitute for legal advice."""

    capability = "legal_validation"

    def run(self, task_input: dict) -> AgentResult:
        restricted = bool(task_input.get("restricted_category", False))
        requires_certification = bool(task_input.get("requires_certification", False))
        certification_available = bool(task_input.get("certification_available", True))

        blocked = restricted and not certification_available
        if blocked:
            return AgentResult(
                status="BLOCKED",
                recommendation="NO_GO",
                confidence=0.95,
                evidence=["category requires certification not currently held"],
                risks=["regulatory non-compliance"],
                assumptions=[],
                data={"legal_status": "BLOCKED"},
            )

        recommendation = "REVIEW" if requires_certification and not certification_available else "GO"

        return AgentResult(
            status="COMPLETED",
            recommendation=recommendation,
            confidence=0.85,
            evidence=["no blocking regulatory restrictions found"],
            risks=[],
            assumptions=["informational screening only, not legal advice"],
            data={"legal_status": "CLEAR"},
        )
