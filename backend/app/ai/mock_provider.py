from app.ai.gateway import AILimits, AIResult

_COST_PER_TOKEN = 0.00001


class MockProvider:
    """Deterministic V1 provider: no live model call, no network access.

    Estimates tokens/cost from the prompt so the gateway's limit
    enforcement can be exercised without a real AI backend.
    """

    name = "mock"

    def execute(self, task_type: str, prompt: str, schema: dict, limits: AILimits) -> AIResult:
        estimated_tokens = max(1, len(prompt.split()))
        estimated_cost = round(estimated_tokens * _COST_PER_TOKEN, 6)

        return AIResult(
            output={"task_type": task_type, "prompt_echo": prompt[:200]},
            estimated_tokens=estimated_tokens,
            estimated_cost=estimated_cost,
            provider=self.name,
        )
