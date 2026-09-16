from sqlalchemy.orm import Session

from app.agents.legal_compliance import LegalComplianceAgent
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.legal_analysis import LegalAnalysis
from app.db.models.product import Product
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote

LEGAL_AGENT_ACTOR = "agent-legal-compliance-1"


class LegalComplianceService:
    """Resolves a Product to its real category (and, when a supplier has
    already been sourced for it, the most recent SupplierQuote's origin
    region/verification), runs the Legal Compliance agent, and persists
    the report — same reconstructability standard as
    ResearchService/SourcingService/EconomicAnalysisService. Unlike the
    Agent 3 flow, a prior SupplierQuote is optional: a product can be
    screened for legal/compliance requirements before sourcing exists."""

    def __init__(self, db: Session, agent: LegalComplianceAgent | None = None) -> None:
        self._db = db
        self._agent = agent or LegalComplianceAgent()

    def run_analysis(
        self,
        *,
        product_id: str,
        market: str,
        correlation_id: str,
        certification_available: bool = False,
    ) -> LegalAnalysis:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

        quote = (
            self._db.query(SupplierQuote)
            .filter_by(product_id=product_id)
            .order_by(SupplierQuote.created_at.desc())
            .first()
        )
        supplier = self._db.get(Supplier, quote.supplier_id) if quote else None

        result = self._agent.run(
            {
                "category": product.category,
                "market": market,
                "product_name": product.name,
                "certification_available": certification_available,
                "supplier_verified": quote.verified if quote else None,
                "origin_region": supplier.region if supplier else None,
            }
        )

        analysis = LegalAnalysis(
            product_id=product_id,
            supplier_quote_id=quote.id if quote else None,
            market=market,
            restricted=result.data.get("restricted"),
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={**result.data, "risks": result.risks, "evidence": result.evidence},
            correlation_id=correlation_id,
        )
        self._db.add(analysis)

        self._db.add(
            AuditLog(
                actor=LEGAL_AGENT_ACTOR,
                action="legal.run",
                resource=f"legal:{correlation_id}",
                before=None,
                after={"product_id": product_id, "market": market},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return analysis
