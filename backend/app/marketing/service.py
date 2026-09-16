from sqlalchemy.orm import Session

from app.agents.marketing_campaign import MarketingCampaignAgent
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.marketing_campaign import MarketingCampaign
from app.db.models.marketplace_listing import MarketplaceListing
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier_quote import SupplierQuote

MARKETING_AGENT_ACTOR = "agent-marketing-campaign-1"


class MarketingCampaignService:
    """Resolves a Product to the real, already-persisted output of all
    six prior agents — research (competition_level), sourcing (lead
    time), economic analysis (price/recommendation), legal analysis
    scoped to the requested market (recommendation), and the marketplace
    listing generated for that same market (linked for traceability) —
    runs the Marketing Campaign agent, and persists the proposal. Legal/
    listing data from a different market is never used: campaign
    readiness is market-specific."""

    def __init__(self, db: Session, agent: MarketingCampaignAgent | None = None) -> None:
        self._db = db
        self._agent = agent or MarketingCampaignAgent()

    def run_generation(
        self,
        *,
        product_id: str,
        market: str,
        correlation_id: str,
        platform: str = "meta",
        daily_budget: float = 20.0,
    ) -> MarketingCampaign:
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

        marketplace_listing = (
            self._db.query(MarketplaceListing)
            .filter_by(product_id=product_id, market=market)
            .order_by(MarketplaceListing.created_at.desc())
            .first()
        )

        result = self._agent.run(
            {
                "product_name": product.name,
                "category": product.category,
                "market": market,
                "platform": platform,
                "daily_budget": daily_budget,
                "sale_price": economic_analysis.sale_price if economic_analysis else None,
                "economic_recommendation": economic_analysis.recommendation if economic_analysis else None,
                "legal_recommendation": legal_analysis.recommendation if legal_analysis else None,
                "marketplace_listing_status": marketplace_listing.listing_status
                if marketplace_listing
                else None,
                "lead_time_days": quote.lead_time_days if quote else None,
                "competition_level": competition_level,
            }
        )

        campaign = MarketingCampaign(
            product_id=product_id,
            marketplace_listing_id=marketplace_listing.id if marketplace_listing else None,
            market=market,
            platform=platform,
            daily_budget=daily_budget,
            campaign_status=result.data["campaign_status"],
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={**result.data, "risks": result.risks, "evidence": result.evidence},
            correlation_id=correlation_id,
        )
        self._db.add(campaign)

        self._db.add(
            AuditLog(
                actor=MARKETING_AGENT_ACTOR,
                action="marketing.run",
                resource=f"marketing:{correlation_id}",
                before=None,
                after={"product_id": product_id, "market": market, "platform": platform},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return campaign
