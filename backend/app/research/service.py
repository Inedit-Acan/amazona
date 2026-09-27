import datetime

from sqlalchemy.orm import Session

from app.agents.product_research import ProductResearchAgent
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.product_signal import ProductSignal
from app.db.models.product_signal_observation import ProductSignalObservation

RESEARCH_AGENT_ACTOR = "agent-product-research-1"


def _parse_observed_at(value: str | None) -> datetime.datetime:
    """La marca de tiempo de la señal, o ahora si el proveedor no la puso. No
    se inventa hacia atrás: una señal sin fecha es una señal de este momento."""
    if not value:
        return datetime.datetime.now(datetime.UTC)
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return datetime.datetime.now(datetime.UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


class ResearchService:
    """Runs the Product Research agent and persists every candidate as a
    first-class Product + ProductAnalysis, so a research run is
    reconstructable from the database, exactly like the rest of the
    system — not just an ephemeral agent call."""

    def __init__(self, db: Session, agent: ProductResearchAgent | None = None) -> None:
        self._db = db
        self._agent = agent or ProductResearchAgent()

    def run_research(
        self,
        *,
        category: str,
        keywords: list[str] | None,
        max_results: int,
        correlation_id: str,
        market: str = "us",
    ) -> list[Product]:
        result = self._agent.run(
            {
                "category": category,
                "keywords": keywords or [],
                "max_results": max_results,
                "market": market,
            }
        )

        products: list[Product] = []
        for candidate in result.data["candidates"]:
            product = Product(
                name=candidate["name"],
                category=candidate["category"],
                created_by=RESEARCH_AGENT_ACTOR,
                source="research",
                status="CANDIDATE",
            )
            self._db.add(product)
            self._db.flush()

            self._db.add(
                ProductAnalysis(
                    product_id=product.id,
                    analysis_type="research",
                    opportunity_score=candidate["opportunity_score"],
                    confidence=result.confidence,
                    data=candidate,
                    correlation_id=correlation_id,
                )
            )
            # Cada número, con de dónde salió (Milestone 34, plan maestro §8).
            # Sin esto, un valor medido y uno inventado son la misma fila.
            for signal in candidate.get("signals", []):
                row = ProductSignal(
                    product_id=product.id,
                    kind=signal["kind"],
                    value=signal["value"],
                    confidence=signal["confidence"],
                    provider=signal["provider"],
                    source=signal["source"],
                    query=signal["query"],
                    market=signal["market"],
                    observed_at=_parse_observed_at(signal.get("observed_at")),
                    method=signal["method"],
                    raw_reference=signal.get("raw_reference"),
                    simulated=bool(signal["simulated"]),
                    correlation_id=correlation_id,
                )
                self._db.add(row)
                self._db.flush()
                # La evidencia detrás del número, si la fuente la dio
                # (Milestone 35). Una señal sin observaciones no es una señal
                # con cero: es una que no se midió así.
                for observation in signal.get("observations") or []:
                    self._db.add(
                        ProductSignalObservation(
                            signal_id=row.id,
                            period=observation["period"],
                            value=observation["value"],
                        )
                    )
            products.append(product)

        self._db.add(
            AuditLog(
                actor=RESEARCH_AGENT_ACTOR,
                action="research.run",
                resource=f"research:{correlation_id}",
                before=None,
                after={
                    "category": category,
                    "candidate_count": len(products),
                    # Qué parte de lo que se acaba de guardar es real.
                    "provenance": sorted(
                        {c.get("provenance", "unknown") for c in result.data["candidates"]}
                    ),
                },
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return products
