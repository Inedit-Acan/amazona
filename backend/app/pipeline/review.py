from dataclasses import dataclass, field

_NO_GO_STEPS = ("economics", "legal")
_BLOCKED_STEPS = ("ecommerce", "marketplace", "marketing", "operations")
_AT_RISK_CFO_STATUSES = {"AT_RISK", "CRITICAL"}


@dataclass
class PipelineAssessment:
    needs_review: bool
    reasons: list[str] = field(default_factory=list)


def assess_pipeline_run(*, status: str, steps: dict[str, dict]) -> PipelineAssessment:
    """Pure, deterministic risk assessment (Milestone 14, ADR 0006) — kept
    separate from PipelineOrchestrator's execution loop, mirroring how
    decision_engine.py is kept separate from orchestrator.py (ADR 0001).
    Does not decide whether the pipeline should have run differently —
    only whether a human should look at what it produced."""
    reasons: list[str] = []

    if status == "PARTIAL":
        reasons.append("pipeline run did not complete (PARTIAL)")

    for step_name in _NO_GO_STEPS:
        step = steps.get(step_name)
        if step and step.get("recommendation") == "NO_GO":
            reasons.append(f"{step_name} recommendation is NO_GO")

    for step_name in _BLOCKED_STEPS:
        step = steps.get(step_name)
        if step and step.get("status") == "BLOCKED":
            reasons.append(f"{step_name} status is BLOCKED")

    cfo_step = steps.get("cfo")
    if cfo_step and cfo_step.get("status") in _AT_RISK_CFO_STATUSES:
        reasons.append(f"cfo financial health status is {cfo_step['status']}")

    return PipelineAssessment(needs_review=bool(reasons), reasons=reasons)
