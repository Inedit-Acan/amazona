from sqlalchemy.orm import Session

from app.agents.ecommerce_storefront import EcommerceStorefrontAgent
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.storefront import Storefront
from app.db.models.supplier_quote import SupplierQuote

ECOMMERCE_AGENT_ACTOR = "agent-ecommerce-storefront-1"


class EcommerceStorefrontService:
    """Resolves a Product to the real, already-persisted output of all
    four prior agents — research (competition_level), sourcing
    (lead_time_days), economic analysis (sale_price/margin/
    recommendation), and legal analysis for the requested market
    (restricted/recommendation) — runs the Ecommerce Storefront agent,
    and persists the draft. A legal analysis for a different market is
    never used: launch readiness is market-specific."""

    def __init__(self, db: Session, agent: EcommerceStorefrontAgent | None = None) -> None:
        self._db = db
        self._agent = agent or EcommerceStorefrontAgent()

    def run_generation(self, *, product_id: str, market: str, correlation_id: str) -> Storefront:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

        research = (
            self._db.query(ProductAnalysis)
            .filter_by(product_id=product_id, analysis_type="research")
            .order_by(ProductAnalysis.created_at.desc())
            .first()
        )
        competition_level = (research.data or {}).get("competition_level") if research else None

        quote = (
            self._db.query(SupplierQuote)
            .filter_by(product_id=product_id)
            .order_by(SupplierQuote.created_at.desc())
            .first()
        )

        economic_analysis = (
            self._db.query(EconomicAnalysis)
            .filter_by(product_id=product_id)
            .order_by(EconomicAnalysis.created_at.desc())
            .first()
        )

        legal_analysis = (
            self._db.query(LegalAnalysis)
            .filter_by(product_id=product_id, market=market)
            .order_by(LegalAnalysis.created_at.desc())
            .first()
        )

        result = self._agent.run(
            {
                "product_id": product.id,
                "product_name": product.name,
                "category": product.category,
                "market": market,
                "sale_price": economic_analysis.sale_price if economic_analysis else None,
                "margin_percent": economic_analysis.margin_percent if economic_analysis else None,
                "economic_recommendation": economic_analysis.recommendation if economic_analysis else None,
                "legal_recommendation": legal_analysis.recommendation if legal_analysis else None,
                "restricted": legal_analysis.restricted if legal_analysis else None,
                "lead_time_days": quote.lead_time_days if quote else None,
                "competition_level": competition_level,
            }
        )

        storefront = Storefront(
            product_id=product_id,
            market=market,
            store_slug=result.data["store_slug"],
            launch_status=result.data["launch_status"],
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={**result.data, "risks": result.risks, "evidence": result.evidence},
            correlation_id=correlation_id,
        )
        self._db.add(storefront)

        self._db.add(
            AuditLog(
                actor=ECOMMERCE_AGENT_ACTOR,
                action="ecommerce.run",
                resource=f"ecommerce:{correlation_id}",
                before=None,
                after={"product_id": product_id, "market": market},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return storefront
