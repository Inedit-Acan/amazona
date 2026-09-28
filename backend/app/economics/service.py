from sqlalchemy.orm import Session

from app.agents.economic_analysis import EconomicAnalysisAgent
from app.core.errors import NotFoundError, ValidationError
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier_quote import SupplierQuote
from app.sourcing.service import supplier_identity_verified
from app.sourcing.trade_terms import ACCOUNTING_CURRENCY, comparable

ECONOMICS_AGENT_ACTOR = "agent-economic-analysis-1"


class EconomicAnalysisService:
    """Resolves a Product + SupplierQuote to their real, already-persisted
    research/sourcing data, runs the Economic Analysis agent, and
    persists the report — same reconstructability standard as
    ResearchService/SourcingService. Never mixes data across products:
    a supplier_quote_id that belongs to a different product is treated
    as not found, not silently accepted."""

    def __init__(self, db: Session, agent: EconomicAnalysisAgent | None = None) -> None:
        self._db = db
        self._agent = agent or EconomicAnalysisAgent()

    def run_analysis(
        self,
        *,
        product_id: str,
        supplier_quote_id: str,
        sale_price: float,
        correlation_id: str,
        monthly_fixed_costs: float = 500.0,
        monthly_unit_sales_base: float | None = None,
    ) -> EconomicAnalysis:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

        quote = self._db.get(SupplierQuote, supplier_quote_id)
        if quote is None or quote.product_id != product_id:
            raise NotFoundError(f"supplier quote {supplier_quote_id} not found for product {product_id}")

        # Desde el Milestone 39 un coste de aterrizaje puede faltar: el proveedor
        # no publicó precio, o nadie ha estimado el transporte. Calcular un
        # margen sobre eso exigiría tratar «no se sabe» como cero, que es
        # exactamente lo que la ADR 0017 quita de en medio — y el margen es la
        # cifra sobre la que después se calcula el techo de CAC.
        if quote.total_landed_cost_per_unit is None:
            raise ValidationError(
                f"supplier quote {supplier_quote_id} has no landed cost: "
                "a margin cannot be computed on an unknown cost"
            )

        research = (
            self._db.query(ProductAnalysis)
            .filter_by(product_id=product_id, analysis_type="research")
            .order_by(ProductAnalysis.created_at.desc())
            .first()
        )
        demand_signal = (research.data or {}).get("demand_signal") if research else None
        competition_level = (research.data or {}).get("competition_level") if research else None

        result = self._agent.run(
            {
                "unit_landed_cost": quote.total_landed_cost_per_unit,
                "sale_price": sale_price,
                "demand_signal": demand_signal,
                "monthly_unit_sales_base": monthly_unit_sales_base,
                "monthly_fixed_costs": monthly_fixed_costs,
                "supplier_verified": supplier_identity_verified(self._db, quote),
                "lead_time_days": quote.lead_time_days,
                "competition_level": competition_level,
            }
        )

        # El precio de venta se razona en la moneda contable; el coste viene en
        # la del proveedor. **No se convierte**: no hay fuente de tipos de
        # cambio y usar uno inventado metería un error del 5 % en el margen sin
        # que nadie lo viera. Se dice, que es lo único honesto que se puede
        # hacer hoy (ADR 0017).
        risks = list(result.risks)
        if not comparable(quote.currency, ACCOUNTING_CURRENCY):
            risks.append(
                f"landed cost is in {quote.currency or 'an undeclared currency'} and the "
                f"sale price in {ACCOUNTING_CURRENCY}: the margin mixes currencies and no "
                "exchange rate has been applied"
            )

        base_scenario = result.data["scenarios"].get("base", {})
        analysis = EconomicAnalysis(
            product_id=product_id,
            supplier_quote_id=supplier_quote_id,
            sale_price=sale_price,
            monthly_fixed_costs=monthly_fixed_costs,
            margin_percent=base_scenario.get("margin_percent", 0.0),
            recommendation=result.recommendation,
            confidence=result.confidence,
            data={**result.data, "risks": risks, "evidence": result.evidence},
            correlation_id=correlation_id,
        )
        self._db.add(analysis)

        self._db.add(
            AuditLog(
                actor=ECONOMICS_AGENT_ACTOR,
                action="economics.run",
                resource=f"economics:{correlation_id}",
                before=None,
                after={"product_id": product_id, "supplier_quote_id": supplier_quote_id},
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return analysis
