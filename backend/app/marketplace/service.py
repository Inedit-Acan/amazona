from sqlalchemy.orm import Session

from app.agents.marketplace_listing import MarketplaceListingAgent
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.marketplace_listing import MarketplaceListing
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.storefront import Storefront
from app.db.models.supplier_quote import SupplierQuote

MARKETPLACE_AGENT_ACTOR = "agent-marketplace-listing-1"


class MarketplaceListingService:
    """Resolves a Product to the real, already-persisted output of all
    five prior agents — research (competition_level), economic analysis
    (sale_price/unit_landed_cost/recommendation), legal analysis for the
    requested market (recommendation), and the storefront generated for
    that same market (linked for traceability) — runs the Marketplace
    Listing agent, and persists the draft. Legal/storefront data from a
    different market is never used: listing readiness is
    market-specific."""

    def __init__(self, db: Session, agent: MarketplaceListingAgent | None = None) -> None:
        self._db = db
        self._agent = agent or MarketplaceListingAgent()

    def run_generation(
        self, *, product_id: str, market: str, correlation_id: str, platform: str = "amazon"
    ) -> MarketplaceListing:
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

        storefront = (
            self._db.query(Storefront)
            .filter_by(product_id=product_id, market=market)
            .order_by(Storefront.created_at.desc())
            .first()
        )

        unit_landed_cost = None
        if economic_analysis is not None:
            # Read the real landed cost from its source (SupplierQuote) rather
            # than re-deriving it algebraically from a persisted, already-
            # rounded margin_percent — one economic source of truth (see
            # docs/design/AMAZONA_cambio_arquitectura_eliminacion_modulo_mercado.md).
            quote = self._db.get(SupplierQuote, economic_analysis.supplier_quote_id)
            if quote is not None:
                unit_landed_cost = quote.total_landed_cost_per_unit

        result = self._agent.run(
            {
                "product_name": product.name,
                "category": product.category,
                "market": market,
                "platform": platform,
                "sale_price": economic_analysis.sale_price if economic_analysis else None,
                "unit_landed_cost": unit_landed_cost,
                "economic_recommendation": economic_analysis.recommendation if economic_analysis else None,
                "legal_recommendation": legal_analysis.recommendation if legal_analysis else None,
                "competition_level": competition_level,
            }
        )

        listing = MarketplaceListing(
            product_id=product_id,
            storefront_id=storefront.id if storefront else None,
            market=market,
            platform=platform,
            listing_status=result.data["listing_status"],
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={**result.data, "risks": result.risks, "evidence": result.evidence},
            correlation_id=correlation_id,
        )
        self._db.add(listing)

        self._db.add(
            AuditLog(
                actor=MARKETPLACE_AGENT_ACTOR,
                action="marketplace.run",
                resource=f"marketplace:{correlation_id}",
                before=None,
                after={"product_id": product_id, "market": market, "platform": platform},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return listing
