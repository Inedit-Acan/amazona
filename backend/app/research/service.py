from sqlalchemy.orm import Session

from app.agents.product_research import ProductResearchAgent
from app.db.models.audit import AuditLog
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis

RESEARCH_AGENT_ACTOR = "agent-product-research-1"


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
    ) -> list[Product]:
        result = self._agent.run(
            {"category": category, "keywords": keywords or [], "max_results": max_results}
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
            products.append(product)

        self._db.add(
            AuditLog(
                actor=RESEARCH_AGENT_ACTOR,
                action="research.run",
                resource=f"research:{correlation_id}",
                before=None,
                after={"category": category, "candidate_count": len(products)},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return products
