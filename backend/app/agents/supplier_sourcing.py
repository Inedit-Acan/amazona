from typing import cast

from pydantic import BaseModel, Field

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.integrations.ports import IntegrationDomain, SupplierDirectory
from app.integrations.registry import ProviderRegistry
from app.sourcing.logistics import estimate_logistics_cost


class SupplierSourcingInput(BaseModel):
    category: str
    destination_region: str
    max_results: int = Field(default=5, ge=1, le=20)


class SupplierSourcingAgent(Agent):
    """Fase 3, Agente 2: discovers and ranks *multiple* candidate suppliers
    for a product category (unlike SupplierAgent, which validates a single
    already-chosen supplier's quote). See ADR 0004. V1: MockSupplierDirectory
    + a deterministic logistics estimator only, no live directory/carrier
    APIs."""

    capability = "supplier_sourcing_research"
    input_schema = SupplierSourcingInput

    def __init__(self, directory: SupplierDirectory | None = None) -> None:
        self._directory: SupplierDirectory = directory or cast(
            SupplierDirectory, ProviderRegistry().resolve(IntegrationDomain.SUPPLIERS)
        )

    def run(self, task_input: dict) -> AgentResult:
        params = SupplierSourcingInput.model_validate(task_input)
        raw_suppliers = self._directory.get_suppliers(
            category=params.category, max_results=params.max_results
        )

        if not raw_suppliers:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[f"no supplier data available for category {params.category!r}"],
                assumptions=[],
                data={"candidates": []},
            )

        candidates = []
        for supplier in raw_suppliers:
            logistics = estimate_logistics_cost(
                origin_region=supplier["region"],
                destination_region=params.destination_region,
                unit_cost=supplier["unit_price"],
                moq=supplier["moq"],
            )
            logistics_cost_per_unit = round(logistics.estimated_total_logistics_cost / supplier["moq"], 4)
            candidates.append(
                {
                    "name": supplier["name"],
                    "region": supplier["region"],
                    "unit_price": supplier["unit_price"],
                    "moq": supplier["moq"],
                    "lead_time_days": supplier["lead_time_days"],
                    "verified": supplier["verified"],
                    "reliability_score": supplier["reliability_score"],
                    "logistics_cost_per_unit": logistics_cost_per_unit,
                    "total_landed_cost_per_unit": round(supplier["unit_price"] + logistics_cost_per_unit, 4),
                    "notes": logistics.notes,
                }
            )

        ranked = sorted(candidates, key=lambda c: c["total_landed_cost_per_unit"])

        risks = [f"{c['name']}: supplier not verified" for c in ranked if not c["verified"]]

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation="GO" if ranked[0]["verified"] else "REVIEW",
            confidence=0.85 if len(ranked) >= 2 else 0.5,
            evidence=[
                f"{c['name']}: total landed cost {c['total_landed_cost_per_unit']}/unit" for c in ranked
            ],
            risks=risks,
            assumptions=["logistics costs are simulated estimates, not real carrier/customs quotes"],
            data={"candidates": ranked},
        )
