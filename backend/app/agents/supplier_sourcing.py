from typing import cast

from pydantic import BaseModel, Field

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.integrations.ports import IntegrationDomain, SupplierDirectory, SupplierOffer
from app.integrations.registry import ProviderRegistry
from app.sourcing.logistics import estimate_logistics_cost
from app.sourcing.provenance import SupplierFactProvenance


class SupplierSourcingInput(BaseModel):
    category: str
    destination_region: str
    max_results: int = Field(default=5, ge=1, le=20)


class SupplierSourcingAgent(Agent):
    """Fase 3, Agente 2: descubre y ordena **varios** proveedores candidatos
    para una categoría (a diferencia de SupplierAgent, que valida la cotización
    de uno ya elegido). Ver ADR 0004.

    Desde el Milestone 39 (ADR 0017) trabaja sobre `SupplierOffer`, que lleva
    procedencia, en vez de sobre diccionarios sueltos. Dos consecuencias que se
    notan:

    - **Lo que no se sabe no se calcula.** Sin precio o sin MOQ no hay coste
      logístico ni coste de aterrizaje: queda `None`. Antes el contrato obligaba
      a que hubiera un número, así que siempre había uno.
    - **Un fixture no justifica un GO.** Mientras algún candidato venga de datos
      simulados la recomendación es `REVIEW`, diga lo que diga el precio. Un
      proveedor inventado no puede sostener una decisión de compra, y hasta aquí
      podía: el mock decía `verified: True` y eso bastaba.
    """

    capability = "supplier_sourcing_research"
    input_schema = SupplierSourcingInput

    def __init__(self, directory: SupplierDirectory | None = None) -> None:
        self._directory: SupplierDirectory = directory or cast(
            SupplierDirectory, ProviderRegistry().resolve(IntegrationDomain.SUPPLIERS)
        )

    def run(self, task_input: dict) -> AgentResult:
        params = SupplierSourcingInput.model_validate(task_input)
        offers = self._directory.find_suppliers(
            category=params.category,
            destination_market=params.destination_region,
            max_results=params.max_results,
        )

        if not offers:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[f"no supplier data available for category {params.category!r}"],
                assumptions=[],
                data={"candidates": []},
            )

        candidates = [self._cost(offer, params.destination_region) for offer in offers]

        # Los que no tienen coste de aterrizaje van al final: no se pueden
        # ordenar por un número que no existe, y meterlos al principio con un
        # cero los haría parecer los más baratos.
        ranked = sorted(
            candidates,
            key=lambda c: (
                c["total_landed_cost_per_unit"] is None,
                c["total_landed_cost_per_unit"] or 0.0,
            ),
        )

        simulated = [c for c in ranked if c["provenance"] == SupplierFactProvenance.SIMULATED]
        unverified = [
            c
            for c in ranked
            if c["verification"] != SupplierFactProvenance.THIRD_PARTY_VERIFIED
        ]
        priceless = [c for c in ranked if c["total_landed_cost_per_unit"] is None]

        risks = []
        if simulated:
            risks.append(
                f"{len(simulated)} of {len(ranked)} candidates come from fixture data: "
                "they are not real companies and cannot support a purchase decision"
            )
        risks += [
            f"{c['name']}: identity not verified by an independent third party"
            for c in unverified
            if c not in simulated
        ]
        risks += [
            f"{c['name']}: no landed cost — {c['landed_cost_missing']}" for c in priceless
        ]

        best = ranked[0]
        if simulated:
            recommendation = "REVIEW"
        elif best["verification"] == SupplierFactProvenance.THIRD_PARTY_VERIFIED:
            recommendation = "GO"
        else:
            recommendation = "REVIEW"

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=0.85 if len(ranked) >= 2 else 0.5,
            evidence=[
                f"{c['name']}: total landed cost {c['total_landed_cost_per_unit']}"
                f" {c['currency'] or '(sin moneda)'}/unit"
                if c["total_landed_cost_per_unit"] is not None
                else f"{c['name']}: landed cost unknown"
                for c in ranked
            ],
            risks=risks,
            assumptions=[
                "logistics costs are simulated estimates, not real carrier/customs quotes",
                "the logistics estimate is expressed in the quote's own currency: "
                "there is no exchange-rate source and none is invented",
            ],
            data={"candidates": ranked},
        )

    def _cost(self, offer: SupplierOffer, destination_region: str) -> dict:
        """Una oferta con lo que se pueda calcular encima, y un motivo cuando no.

        El coste logístico necesita precio y MOQ. Faltando cualquiera de los
        dos queda `None` **con el motivo escrito**: «no hay coste» y «el coste
        es cero» se parecen demasiado en una tabla como para no distinguirlos.
        """
        logistics_cost_per_unit: float | None = None
        landed: float | None = None
        missing: str | None = None
        notes: str | None = None

        if offer.unit_price is None:
            missing = "the source did not publish a price"
        elif offer.moq is None:
            missing = "the source did not publish a minimum order quantity"
        elif offer.region is None:
            missing = "the source did not say where the supplier ships from"
        else:
            logistics = estimate_logistics_cost(
                origin_region=offer.region,
                destination_region=destination_region,
                unit_cost=offer.unit_price,
                moq=offer.moq,
            )
            logistics_cost_per_unit = round(
                logistics.estimated_total_logistics_cost / offer.moq, 4
            )
            landed = round(offer.unit_price + logistics_cost_per_unit, 4)
            notes = logistics.notes

        return {
            "name": offer.name,
            "region": offer.region,
            "country": offer.country,
            "city": offer.city,
            "website": offer.website,
            "unit_price": offer.unit_price,
            "currency": offer.currency,
            "quoted_unit": offer.quoted_unit,
            "quoted_quantity": offer.quoted_quantity,
            "moq": offer.moq,
            "lead_time_days": offer.lead_time_days,
            "transit_days": offer.transit_days,
            "transport_mode": offer.transport_mode,
            "incoterm": offer.incoterm,
            "payment_terms": offer.payment_terms,
            "destination_market": offer.destination_market or destination_region,
            "reliability": offer.reliability,
            "provenance": offer.provenance.value,
            "verification": offer.verification.value if offer.verification else None,
            "verified_by": offer.verified_by,
            "source": offer.source,
            "logistics_cost_per_unit": logistics_cost_per_unit,
            # Lo calcula un estimador nuestro con factores inventados, así que
            # lo sostiene AMAZONA y no el proveedor. Va aparte del precio a
            # propósito: presentarlos con la misma procedencia mentiría sobre
            # la mitad de la suma.
            "logistics_provenance": (
                SupplierFactProvenance.AMAZONA_ESTIMATE.value
                if logistics_cost_per_unit is not None
                else None
            ),
            "total_landed_cost_per_unit": landed,
            "landed_cost_missing": missing,
            "notes": notes,
        }
