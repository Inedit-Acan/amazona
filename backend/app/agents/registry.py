from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.base import AgentDescriptor, AgentStatus
from app.core.errors import NotFoundError

if TYPE_CHECKING:
    from app.agents.manager import AgentManager

_EXCLUDED_FROM_ROUTING = {AgentStatus.DISABLED, AgentStatus.FAILED}


class AgentRegistry:
    """Holds known agent descriptors so the CEO can route by capability
    instead of hardcoding a concrete agent implementation."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDescriptor] = {}

    def register(self, descriptor: AgentDescriptor) -> None:
        self._agents[descriptor.id] = descriptor

    def find_by_capability(self, capability: str, region: str | None = None) -> list[AgentDescriptor]:
        return [
            agent
            for agent in self._agents.values()
            if capability in agent.capabilities
            and agent.status not in _EXCLUDED_FROM_ROUTING
            and (region is None or not agent.regions or region in agent.regions)
        ]

    def set_status(self, agent_id: str, status: AgentStatus) -> None:
        self._get(agent_id).status = status

    def get_health(self, agent_id: str) -> AgentDescriptor:
        return self._get(agent_id)

    def list_all(self) -> list[AgentDescriptor]:
        return list(self._agents.values())

    def _get(self, agent_id: str) -> AgentDescriptor:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise NotFoundError(f"agent {agent_id} not found")
        return agent


def build_default_agent_manager() -> tuple[AgentRegistry, AgentManager]:
    """Wire up and register the Milestone 1 specialist agents plus Fase 3's
    first agent (Product Research/discovery)."""
    from app.agents.ecommerce_storefront import EcommerceStorefrontAgent
    from app.agents.economic_analysis import EconomicAnalysisAgent
    from app.agents.finance import FinanceAgent
    from app.agents.legal import LegalAgent
    from app.agents.legal_compliance import LegalComplianceAgent
    from app.agents.manager import AgentManager
    from app.agents.marketplace_listing import MarketplaceListingAgent
    from app.agents.product import ProductAgent
    from app.agents.product_research import ProductResearchAgent
    from app.agents.supplier import SupplierAgent
    from app.agents.supplier_sourcing import SupplierSourcingAgent

    registry = AgentRegistry()
    manager = AgentManager(registry)

    specialists = [
        ("agent-product-1", "Product Validation Agent", "product", ProductAgent()),
        ("agent-supplier-1", "Supplier Sourcing Agent", "supplier", SupplierAgent()),
        ("agent-finance-1", "Finance Validation Agent", "finance", FinanceAgent()),
        ("agent-legal-1", "Legal Validation Agent", "legal", LegalAgent()),
        ("agent-product-research-1", "Product Research Agent", "research", ProductResearchAgent()),
        (
            "agent-supplier-sourcing-1",
            "Supplier Sourcing Research Agent",
            "sourcing",
            SupplierSourcingAgent(),
        ),
        (
            "agent-economic-analysis-1",
            "Economic Analysis and Risk Agent",
            "economics",
            EconomicAnalysisAgent(),
        ),
        (
            "agent-legal-compliance-1",
            "Legal Compliance Analysis Agent",
            "legal_compliance",
            LegalComplianceAgent(),
        ),
        (
            "agent-ecommerce-storefront-1",
            "Ecommerce Storefront Generation Agent",
            "ecommerce",
            EcommerceStorefrontAgent(),
        ),
        (
            "agent-marketplace-listing-1",
            "Marketplace Listing Optimization Agent",
            "marketplace",
            MarketplaceListingAgent(),
        ),
    ]

    for agent_id, name, role, executor in specialists:
        registry.register(
            AgentDescriptor(
                id=agent_id,
                name=name,
                role=role,
                version="1.0.0",
                capabilities=[executor.capability],
                reliability_score=1.0,
                cost_profile={"simulated_cost_per_task": 0.0},
            )
        )
        manager.register_executor(agent_id, executor)

    return registry, manager
