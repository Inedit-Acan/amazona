from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.cfo import CFOAgent
from app.db.models.audit import AuditLog
from app.db.models.budget import Budget, BudgetAllocation
from app.db.models.cfo_report import CFOReport
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.marketing_campaign import MarketingCampaign

CFO_AGENT_ACTOR = "agent-cfo-1"


class CFOService:
    """Consolidates the real, already-persisted output of EconomicAnalysis
    (Agente 3) and MarketingCampaign (Agente 7) across the whole catalog,
    plus BudgetEngine's reservations (Budget/BudgetAllocation), into one
    aggregate financial-health report. Unlike every other Fase 3 service,
    this is catalog-wide — there is no single product to resolve."""

    def __init__(self, db: Session, agent: CFOAgent | None = None) -> None:
        self._db = db
        self._agent = agent or CFOAgent()

    def run_generation(self, *, correlation_id: str) -> CFOReport:
        economic_analyses = self._latest_economic_analyses()
        campaigns = self._latest_marketing_campaigns()
        budgets = self._db.query(Budget).all()
        allocations = self._db.query(BudgetAllocation).all()

        go_count = sum(1 for a in economic_analyses if a.recommendation == "GO")
        review_count = sum(1 for a in economic_analyses if a.recommendation == "REVIEW")
        no_go_count = sum(1 for a in economic_analyses if a.recommendation == "NO_GO")

        active_campaigns = [c for c in campaigns if c.campaign_status == "READY"]
        total_daily_budget = sum(c.daily_budget for c in active_campaigns)

        result = self._agent.run(
            {
                "total_products_analyzed": len(economic_analyses),
                "go_count": go_count,
                "review_count": review_count,
                "no_go_count": no_go_count,
                "total_campaigns": len(campaigns),
                "active_campaigns": len(active_campaigns),
                "total_daily_budget": total_daily_budget,
                "total_budget_hard_limit": sum(b.hard_limit for b in budgets),
                "total_reserved": sum(a.reserved for a in allocations),
                "total_committed": sum(a.committed for a in allocations),
                "total_spent": sum(a.spent for a in allocations),
            }
        )

        record = CFOReport(
            financial_health_status=result.data["financial_health_status"],
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={
                **result.data,
                "risks": result.risks,
                "evidence": result.evidence,
                "included_economic_analysis_ids": [a.id for a in economic_analyses],
                "included_marketing_campaign_ids": [c.id for c in campaigns],
            },
            correlation_id=correlation_id,
        )
        self._db.add(record)

        self._db.add(
            AuditLog(
                actor=CFO_AGENT_ACTOR,
                action="cfo.run",
                resource=f"cfo:{correlation_id}",
                before=None,
                after={"products_analyzed": len(economic_analyses), "campaigns": len(campaigns)},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return record

    def _latest_economic_analyses(self) -> list[EconomicAnalysis]:
        """The most recent EconomicAnalysis per product, computed in SQL
        (MAX(created_at) grouped by product_id + join) instead of loading
        every historical row and deduping in Python — cost scales with
        the number of distinct products, not with total history."""
        latest_per_product = (
            self._db.query(
                EconomicAnalysis.product_id,
                func.max(EconomicAnalysis.created_at).label("latest_created_at"),
            )
            .group_by(EconomicAnalysis.product_id)
            .subquery()
        )
        return (
            self._db.query(EconomicAnalysis)
            .join(
                latest_per_product,
                (EconomicAnalysis.product_id == latest_per_product.c.product_id)
                & (EconomicAnalysis.created_at == latest_per_product.c.latest_created_at),
            )
            .all()
        )

    def _latest_marketing_campaigns(self) -> list[MarketingCampaign]:
        """Same approach as `_latest_economic_analyses`, grouped by
        (product_id, market) since a product can run a distinct campaign
        per market."""
        latest_per_campaign = (
            self._db.query(
                MarketingCampaign.product_id,
                MarketingCampaign.market,
                func.max(MarketingCampaign.created_at).label("latest_created_at"),
            )
            .group_by(MarketingCampaign.product_id, MarketingCampaign.market)
            .subquery()
        )
        return (
            self._db.query(MarketingCampaign)
            .join(
                latest_per_campaign,
                (MarketingCampaign.product_id == latest_per_campaign.c.product_id)
                & (MarketingCampaign.market == latest_per_campaign.c.market)
                & (MarketingCampaign.created_at == latest_per_campaign.c.latest_created_at),
            )
            .all()
        )
