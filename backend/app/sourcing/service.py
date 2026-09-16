from sqlalchemy.orm import Session

from app.agents.supplier_sourcing import SupplierSourcingAgent
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote

SOURCING_AGENT_ACTOR = "agent-supplier-sourcing-1"


class SourcingService:
    """Runs the Supplier Sourcing agent for an already-existing Product and
    persists every candidate as a SupplierQuote, reusing a Supplier row
    when one already exists for the same (name, region) instead of
    duplicating it on every run — a run is reconstructable from the
    database, exactly like ResearchService."""

    def __init__(self, db: Session, agent: SupplierSourcingAgent | None = None) -> None:
        self._db = db
        self._agent = agent or SupplierSourcingAgent()

    def run_sourcing(
        self,
        *,
        product_id: str,
        category: str,
        destination_region: str,
        max_results: int,
        correlation_id: str,
    ) -> list[SupplierQuote]:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

        result = self._agent.run(
            {"category": category, "destination_region": destination_region, "max_results": max_results}
        )

        quotes: list[SupplierQuote] = []
        for candidate in result.data["candidates"]:
            supplier = (
                self._db.query(Supplier)
                .filter_by(name=candidate["name"], region=candidate["region"])
                .first()
            )
            if supplier is None:
                supplier = Supplier(
                    name=candidate["name"],
                    region=candidate["region"],
                    verified=candidate["verified"],
                    reliability_score=candidate["reliability_score"],
                )
                self._db.add(supplier)
                self._db.flush()

            quote = SupplierQuote(
                product_id=product.id,
                supplier_id=supplier.id,
                unit_price=candidate["unit_price"],
                moq=candidate["moq"],
                lead_time_days=candidate["lead_time_days"],
                verified=candidate["verified"],
                reliability_score=candidate["reliability_score"],
                logistics_cost_per_unit=candidate["logistics_cost_per_unit"],
                total_landed_cost_per_unit=candidate["total_landed_cost_per_unit"],
                data=candidate,
                correlation_id=correlation_id,
            )
            self._db.add(quote)
            quotes.append(quote)

        self._db.add(
            AuditLog(
                actor=SOURCING_AGENT_ACTOR,
                action="sourcing.run",
                resource=f"sourcing:{correlation_id}",
                before=None,
                after={"product_id": product_id, "quote_count": len(quotes)},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return quotes
