from typing import Protocol

from pydantic import BaseModel

from app.core.errors import AmazonaError


class CostLimitExceededError(AmazonaError):
    """Raised when a provider's estimated cost exceeds the caller's ceiling."""


class AILimits(BaseModel):
    max_cost: float = 0.0
    timeout_seconds: float = 30.0


class AIResult(BaseModel):
    output: dict
    estimated_tokens: int
    estimated_cost: float
    provider: str


class AIProvider(Protocol):
    def execute(self, task_type: str, prompt: str, schema: dict, limits: AILimits) -> AIResult: ...


class AIGateway:
    """Model-agnostic entry point for agent AI calls.

    Agents depend on this gateway, never on a provider SDK directly, so
    the underlying model/provider can change without touching agent code.
    """

    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider

    def execute(self, task_type: str, prompt: str, schema: dict, limits: dict | AILimits) -> AIResult:
        limits_obj = limits if isinstance(limits, AILimits) else AILimits(**limits)

        result = self._provider.execute(task_type, prompt, schema, limits_obj)

        if result.estimated_cost > limits_obj.max_cost:
            raise CostLimitExceededError(
                f"estimated cost {result.estimated_cost} exceeds ceiling {limits_obj.max_cost}"
            )

        return result
