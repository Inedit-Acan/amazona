from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.cfo.service import CFOService
from app.core.errors import PipelineDisabledError
from app.core.ids import new_correlation_id
from app.db.models.audit import AuditLog
from app.db.models.pipeline_review import PipelineReview
from app.db.models.pipeline_run import PipelineRun
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier_quote import SupplierQuote
from app.ecommerce.service import EcommerceStorefrontService
from app.economics.service import EconomicAnalysisService
from app.legal.service import LegalComplianceService
from app.marketing.service import MarketingCampaignService
from app.marketplace.service import MarketplaceListingService
from app.operations.service import OperationsService
from app.pipeline.kill_switch import PipelineKillSwitchService
from app.pipeline.review import assess_pipeline_run
from app.research.service import ResearchService
from app.sourcing.service import SourcingService

PIPELINE_ACTOR = "pipeline-orchestrator-1"


@dataclass
class PipelineRequest:
    category: str
    sale_price: float
    destination_region: str
    market: str = "us"
    marketplace_platform: str = "amazon"
    marketing_platform: str = "meta"
    daily_budget: float = 20.0
    monthly_fixed_costs: float = 500.0
    certification_available: bool = False
    max_results: int = 5


def pick_best_candidate(products: list[Product], score_by_product_id: dict[str, float]) -> Product:
    """Same ranking ResearchService/ProductResearchAgent already apply
    internally (opportunity_score descending) — the pipeline just needs
    to pick one instead of a human eyeballing the list."""
    return max(products, key=lambda p: score_by_product_id.get(p.id, 0.0))


def pick_best_quote(quotes: list[SupplierQuote]) -> SupplierQuote:
    """Same ranking SupplierSourcingAgent/`/suppliers` endpoint already
    apply internally (total_landed_cost_per_unit ascending)."""
    return min(quotes, key=lambda q: q.total_landed_cost_per_unit)


class PipelineOrchestrator:
    """Chains the 9 Fase 3 steps (research through CFO) in one invocation
    (Milestone 12, ADR 0005), replacing the manual "click through 9
    Control Center pages copying IDs" flow documented as pending in
    Milestone 9's Fase 3 close-out. Reuses the 9 existing services
    exactly as they are — no agent logic is duplicated here, this is
    pure sequencing plus best-candidate/best-quote selection.

    Never modifies planner.py/decision_engine.py/CEOOrchestrator — this
    is a separate, parallel orchestration path for catalog discovery,
    not the Milestone-1 objective validation graph (ADR 0004).

    No step halts the chain on a NO_GO/BLOCKED outcome — every step's
    status is recorded in `steps` regardless. The pipeline only stops
    early (status PARTIAL) when a step genuinely cannot produce a
    result to hand to the next one (e.g. research finds no candidates)."""

    def __init__(self, db: Session, kill_switch: PipelineKillSwitchService | None = None) -> None:
        self._db = db
        self._kill_switch = kill_switch or PipelineKillSwitchService(db)

    def run_pipeline(self, request: PipelineRequest) -> PipelineRun:
        if not self._kill_switch.is_enabled():
            raise PipelineDisabledError("pipeline runs are currently disabled by an operator")

        correlation_id = new_correlation_id()
        steps: dict[str, dict] = {}

        research_correlation_id = new_correlation_id()
        products = ResearchService(self._db).run_research(
            category=request.category,
            keywords=None,
            max_results=request.max_results,
            correlation_id=research_correlation_id,
        )
        if not products:
            steps["research"] = {"correlation_id": research_correlation_id, "candidate_count": 0}
            return self._persist(request, correlation_id, None, "PARTIAL", "research", steps)

        analyses = (
            self._db.query(ProductAnalysis)
            .filter(
                ProductAnalysis.product_id.in_([p.id for p in products]),
                ProductAnalysis.correlation_id == research_correlation_id,
            )
            .all()
        )
        score_by_product_id = {a.product_id: (a.opportunity_score or 0.0) for a in analyses}
        product = pick_best_candidate(products, score_by_product_id)
        steps["research"] = {
            "correlation_id": research_correlation_id,
            "entity_id": product.id,
            "candidate_count": len(products),
        }

        sourcing_correlation_id = new_correlation_id()
        quotes = SourcingService(self._db).run_sourcing(
            product_id=product.id,
            category=request.category,
            destination_region=request.destination_region,
            max_results=request.max_results,
            correlation_id=sourcing_correlation_id,
        )
        if not quotes:
            steps["sourcing"] = {"correlation_id": sourcing_correlation_id, "candidate_count": 0}
            return self._persist(request, correlation_id, product.id, "PARTIAL", "sourcing", steps)

        quote = pick_best_quote(quotes)
        steps["sourcing"] = {
            "correlation_id": sourcing_correlation_id,
            "entity_id": quote.id,
            "candidate_count": len(quotes),
        }

        economics_correlation_id = new_correlation_id()
        economic_analysis = EconomicAnalysisService(self._db).run_analysis(
            product_id=product.id,
            supplier_quote_id=quote.id,
            sale_price=request.sale_price,
            monthly_fixed_costs=request.monthly_fixed_costs,
            correlation_id=economics_correlation_id,
        )
        steps["economics"] = {
            "correlation_id": economics_correlation_id,
            "entity_id": economic_analysis.id,
            "recommendation": economic_analysis.recommendation,
        }

        legal_correlation_id = new_correlation_id()
        legal_analysis = LegalComplianceService(self._db).run_analysis(
            product_id=product.id,
            market=request.market,
            certification_available=request.certification_available,
            correlation_id=legal_correlation_id,
        )
        steps["legal"] = {
            "correlation_id": legal_correlation_id,
            "entity_id": legal_analysis.id,
            "recommendation": legal_analysis.recommendation,
        }

        ecommerce_correlation_id = new_correlation_id()
        storefront = EcommerceStorefrontService(self._db).run_generation(
            product_id=product.id, market=request.market, correlation_id=ecommerce_correlation_id
        )
        steps["ecommerce"] = {
            "correlation_id": ecommerce_correlation_id,
            "entity_id": storefront.id,
            "status": storefront.launch_status,
        }

        marketplace_correlation_id = new_correlation_id()
        listing = MarketplaceListingService(self._db).run_generation(
            product_id=product.id,
            market=request.market,
            platform=request.marketplace_platform,
            correlation_id=marketplace_correlation_id,
        )
        steps["marketplace"] = {
            "correlation_id": marketplace_correlation_id,
            "entity_id": listing.id,
            "status": listing.listing_status,
        }

        marketing_correlation_id = new_correlation_id()
        campaign = MarketingCampaignService(self._db).run_generation(
            product_id=product.id,
            market=request.market,
            platform=request.marketing_platform,
            daily_budget=request.daily_budget,
            correlation_id=marketing_correlation_id,
        )
        steps["marketing"] = {
            "correlation_id": marketing_correlation_id,
            "entity_id": campaign.id,
            "status": campaign.campaign_status,
        }

        operations_correlation_id = new_correlation_id()
        operations_record = OperationsService(self._db).run_generation(
            product_id=product.id, market=request.market, correlation_id=operations_correlation_id
        )
        steps["operations"] = {
            "correlation_id": operations_correlation_id,
            "entity_id": operations_record.id,
            "status": operations_record.operations_status,
        }

        cfo_correlation_id = new_correlation_id()
        cfo_report = CFOService(self._db).run_generation(correlation_id=cfo_correlation_id)
        steps["cfo"] = {
            "correlation_id": cfo_correlation_id,
            "entity_id": cfo_report.id,
            "status": cfo_report.financial_health_status,
        }

        return self._persist(request, correlation_id, product.id, "COMPLETED", None, steps)

    def _persist(
        self,
        request: PipelineRequest,
        correlation_id: str,
        product_id: str | None,
        status: str,
        failed_step: str | None,
        steps: dict[str, dict],
    ) -> PipelineRun:
        assessment = assess_pipeline_run(status=status, steps=steps)

        run = PipelineRun(
            product_id=product_id,
            category=request.category,
            market=request.market,
            status=status,
            failed_step=failed_step,
            steps=steps,
            needs_review=assessment.needs_review,
            correlation_id=correlation_id,
        )
        self._db.add(run)
        self._db.flush()

        if assessment.needs_review:
            self._db.add(
                PipelineReview(
                    pipeline_run_id=run.id,
                    reasons=assessment.reasons,
                    status="PENDING",
                    correlation_id=correlation_id,
                )
            )

        self._db.add(
            AuditLog(
                actor=PIPELINE_ACTOR,
                action="pipeline.run",
                resource=f"pipeline:{correlation_id}",
                before=None,
                after={
                    "category": request.category,
                    "status": status,
                    "steps": list(steps.keys()),
                    "needs_review": assessment.needs_review,
                },
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return run
