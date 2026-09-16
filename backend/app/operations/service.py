from sqlalchemy.orm import Session

from app.agents.operations import OperationsAgent
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.marketing_campaign import MarketingCampaign
from app.db.models.operations_record import OperationsRecord
from app.db.models.product import Product
from app.db.models.supplier_quote import SupplierQuote

OPERATIONS_AGENT_ACTOR = "agent-operations-1"


class OperationsService:
    """Resolves a Product to the real, already-persisted output of all
    seven prior agents — sourcing (lead time/verification), economic
    analysis (price/recommendation), legal analysis scoped to the
    requested market (recommendation/restriction), and the marketing
    campaign generated for that same market (linked for traceability) —
    runs the Operations agent, and persists the report. Legal/campaign
    data from a different market is never used: operations readiness is
    market-specific."""

    def __init__(self, db: Session, agent: OperationsAgent | None = None) -> None:
        self._db = db
        self._agent = agent or OperationsAgent()

    def run_generation(self, *, product_id: str, market: str, correlation_id: str) -> OperationsRecord:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

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

        marketing_campaign = (
            self._db.query(MarketingCampaign)
            .filter_by(product_id=product_id, market=market)
            .order_by(MarketingCampaign.created_at.desc())
            .first()
        )

        result = self._agent.run(
            {
                "product_name": product.name,
                "category": product.category,
                "market": market,
                "sale_price": economic_analysis.sale_price if economic_analysis else None,
                "lead_time_days": quote.lead_time_days if quote else None,
                "supplier_verified": quote.verified if quote else None,
                "economic_recommendation": economic_analysis.recommendation if economic_analysis else None,
                "legal_recommendation": legal_analysis.recommendation if legal_analysis else None,
                "restricted": legal_analysis.restricted if legal_analysis else None,
            }
        )

        record = OperationsRecord(
            product_id=product_id,
            marketing_campaign_id=marketing_campaign.id if marketing_campaign else None,
            market=market,
            operations_status=result.data["operations_status"],
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={**result.data, "risks": result.risks, "evidence": result.evidence},
            correlation_id=correlation_id,
        )
        self._db.add(record)

        self._db.add(
            AuditLog(
                actor=OPERATIONS_AGENT_ACTOR,
                action="operations.run",
                resource=f"operations:{correlation_id}",
                before=None,
                after={"product_id": product_id, "market": market},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return record
