import pytest

from app.ai.gateway import AIGateway, CostLimitExceededError
from app.ai.mock_provider import MockProvider


class FakeAlternativeProvider:
    """A second provider implementing the same protocol as MockProvider,
    used to prove the gateway does not depend on a concrete provider."""

    name = "fake-alternative"

    def execute(self, task_type, prompt, schema, limits):
        from app.ai.gateway import AIResult

        return AIResult(
            output={"task_type": task_type, "provider": self.name},
            estimated_tokens=10,
            estimated_cost=0.001,
            provider=self.name,
        )


def test_gateway_executes_through_the_mock_provider_by_default():
    gateway = AIGateway(provider=MockProvider())

    result = gateway.execute(
        task_type="market_validation",
        prompt="Assess demand for wireless earbuds",
        schema={"type": "object"},
        limits={"max_cost": 1.0, "timeout_seconds": 5.0},
    )

    assert result.provider == "mock"
    assert result.estimated_tokens > 0
    assert result.estimated_cost >= 0


def test_gateway_is_provider_independent():
    gateway = AIGateway(provider=FakeAlternativeProvider())

    result = gateway.execute(
        task_type="market_validation",
        prompt="Assess demand",
        schema={"type": "object"},
        limits={"max_cost": 1.0, "timeout_seconds": 5.0},
    )

    assert result.provider == "fake-alternative"
    assert result.output["task_type"] == "market_validation"


def test_gateway_rejects_execution_over_the_cost_ceiling():
    gateway = AIGateway(provider=MockProvider())

    with pytest.raises(CostLimitExceededError):
        gateway.execute(
            task_type="market_validation",
            prompt="Assess demand for wireless earbuds " * 50,
            schema={"type": "object"},
            limits={"max_cost": 0.0, "timeout_seconds": 5.0},
        )


def test_gateway_result_carries_cost_metadata_within_the_ceiling():
    gateway = AIGateway(provider=MockProvider())

    result = gateway.execute(
        task_type="market_validation",
        prompt="short prompt",
        schema={"type": "object"},
        limits={"max_cost": 10.0, "timeout_seconds": 5.0},
    )

    assert result.estimated_cost <= 10.0
