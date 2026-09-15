import pytest

from app.agents.base import AgentDescriptor, AgentStatus
from app.agents.registry import AgentRegistry
from app.core.errors import NotFoundError


def make_descriptor(**overrides) -> AgentDescriptor:
    defaults = dict(
        id="agent-product-1",
        name="Product Research Agent",
        role="product",
        version="1.0.0",
        capabilities=["market_validation"],
        regions=["EU"],
    )
    defaults.update(overrides)
    return AgentDescriptor(**defaults)


@pytest.fixture()
def registry() -> AgentRegistry:
    return AgentRegistry()


def test_register_stores_the_descriptor(registry: AgentRegistry):
    descriptor = make_descriptor()

    registry.register(descriptor)

    assert registry.get_health(descriptor.id).status == AgentStatus.AVAILABLE


def test_list_all_returns_every_registered_descriptor(registry: AgentRegistry):
    registry.register(make_descriptor(id="agent-a"))
    registry.register(make_descriptor(id="agent-b"))

    assert {a.id for a in registry.list_all()} == {"agent-a", "agent-b"}


def test_find_by_capability_returns_matching_agents(registry: AgentRegistry):
    product_agent = make_descriptor(id="agent-product-1", capabilities=["market_validation"])
    legal_agent = make_descriptor(id="agent-legal-1", capabilities=["legal_validation"])
    registry.register(product_agent)
    registry.register(legal_agent)

    matches = registry.find_by_capability("market_validation")

    assert [a.id for a in matches] == ["agent-product-1"]


def test_find_by_capability_can_filter_by_region(registry: AgentRegistry):
    eu_agent = make_descriptor(id="agent-eu", capabilities=["market_validation"], regions=["EU"])
    us_agent = make_descriptor(id="agent-us", capabilities=["market_validation"], regions=["US"])
    registry.register(eu_agent)
    registry.register(us_agent)

    matches = registry.find_by_capability("market_validation", region="US")

    assert [a.id for a in matches] == ["agent-us"]


def test_disabled_agents_are_excluded_from_capability_routing(registry: AgentRegistry):
    descriptor = make_descriptor()
    registry.register(descriptor)

    registry.set_status(descriptor.id, AgentStatus.DISABLED)

    assert registry.find_by_capability("market_validation") == []


def test_set_status_updates_health(registry: AgentRegistry):
    descriptor = make_descriptor()
    registry.register(descriptor)

    registry.set_status(descriptor.id, AgentStatus.DEGRADED)

    assert registry.get_health(descriptor.id).status == AgentStatus.DEGRADED


def test_get_health_raises_for_unknown_agent(registry: AgentRegistry):
    with pytest.raises(NotFoundError):
        registry.get_health("does-not-exist")
