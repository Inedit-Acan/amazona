"""El análisis económico, por canal y con la moneda resuelta (Milestone 40).

Resuelve un Product y una SupplierQuote a sus datos reales ya persistidos,
**lleva todos los importes a una sola moneda con una conversión trazable**,
construye el desglose de costes del canal pedido, calcula la cadena unidad →
pedido → adquisición, ejecuta el agente y persiste el informe.

## Tres cosas que este servicio NO hace

1. **No decide.** Emite una recomendación económica; vender o no vender es de la
   capa posterior. Un análisis no evaluable sale como `REVIEW` —una duda— y
   **nunca** como `NO_GO`, porque «no se puede saber» no es «va mal» y el
   ActionGate veta los `NO_GO` que gastan (ADR 0011).
2. **No exige un proveedor verificado.** Calcula igual con una cotización que
   solo sostiene el proveedor, y **dice con qué procedencia calculó**. La
   identidad viaja aparte, en su propio bloque, sin tocar la aritmética.
3. **No inventa un tipo de cambio.** Sin tasa aplicable el análisis es no
   evaluable, con `exchange_rate` en la lista de lo que falta. Nunca 1:1.
"""

import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.agents.base import AgentResult, AgentResultStatus
from app.agents.economic_analysis import EconomicAnalysisAgent
from app.ai.mock_channel_costs import SOURCE as CHANNEL_COST_FIXTURES
from app.ai.mock_channel_costs import MockChannelCostDirectory
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.models.audit import AuditLog
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.economics.channel_costs import ChannelFee, QuoteCosts, build_breakdown
from app.economics.components import CostBreakdown
from app.economics.scenarios import estimate_monthly_unit_sales
from app.economics.unit_economics import (
    DeclaredQuantity,
    Evaluability,
    UnitEconomicsInput,
    UnitEconomicsResult,
    evaluate,
)
from app.integrations.channels import ChannelKind, channel_for
from app.integrations.ports import IntegrationDomain
from app.integrations.registry import ProviderRegistry
from app.money.money import Money
from app.money.rates import Conversion, NoRateAvailableError, convert
from app.money.resolver import exchange_rates_for
from app.money.serialization import conversion_to_json, decimal_to_json, money_to_json
from app.sourcing.provenance import SupplierFactProvenance, parse
from app.sourcing.service import supplier_identity_verified
from app.sourcing.trade_terms import ACCOUNTING_CURRENCY

ECONOMICS_AGENT_ACTOR = "agent-economic-analysis-1"

#: El canal por defecto cuando quien llama no dice ninguno: la web propia, que
#: es el canal prioritario del proyecto. Se **declara** en el análisis, no se
#: deja en blanco: un margen sin canal no se puede comparar con otro.
DEFAULT_CHANNEL = "own_web"


class EconomicAnalysisService:
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
        channel: str = DEFAULT_CHANNEL,
        currency: str = ACCOUNTING_CURRENCY,
        units_per_order: int | None = None,
        payment_cost_per_unit: float | None = None,
        other_variable_cost_per_unit: float | None = None,
        actor: str = ECONOMICS_AGENT_ACTOR,
        on: datetime.date | None = None,
    ) -> EconomicAnalysis:
        product = self._db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"product {product_id} not found")

        quote = self._db.get(SupplierQuote, supplier_quote_id)
        if quote is None or quote.product_id != product_id:
            raise NotFoundError(
                f"supplier quote {supplier_quote_id} not found for product {product_id}"
            )

        research = (
            self._db.query(ProductAnalysis)
            .filter_by(product_id=product_id, analysis_type="research")
            .order_by(ProductAnalysis.created_at.desc())
            .first()
        )
        channel_key = channel_for(channel).key
        price = Money.from_legacy_float(sale_price, currency)
        fixed_costs = Money.from_legacy_float(monthly_fixed_costs, currency)
        today = on or datetime.datetime.now(datetime.UTC).date()

        # --- 1. Todo a una sola moneda, con la conversión registrada -------
        costs, conversions, fx_missing = self._quote_costs_in(quote, currency=currency, on=today)

        # --- 2. El desglose del canal --------------------------------------
        payment = self._payment_cost(
            channel_key, price, declared=payment_cost_per_unit, currency=currency, actor=actor
        )
        breakdown = build_breakdown(
            channel_key=channel_key,
            sale_price=price,
            quote=costs,
            channel_fee=self._channel_fee(channel_key, product.category, currency),
            payment_cost=payment[0],
            payment_provenance=payment[1],
            payment_source=payment[2],
            other_variable_cost=(
                Money.from_legacy_float(other_variable_cost_per_unit, currency)
                if other_variable_cost_per_unit is not None
                else None
            ),
            other_provenance=SupplierFactProvenance.DECLARED,
            other_source=f"manual:{actor}",
        )

        # --- 3. Unidad -> pedido -> adquisición ----------------------------
        units = (
            DeclaredQuantity.declared(units_per_order, source=f"manual:{actor}")
            if units_per_order is not None
            else DeclaredQuantity.unknown()
        )
        unit_economics = evaluate(
            UnitEconomicsInput(
                sale_price=price,
                breakdown=breakdown,
                units_per_order=units,
                expected_monthly_orders=self._expected_monthly_orders(
                    monthly_unit_sales_base, units, research=research
                ),
                monthly_fixed_costs=fixed_costs,
            )
        )

        missing = list(unit_economics.missing_inputs)
        if fx_missing:
            missing.insert(0, "exchange_rate")
        evaluable = (
            unit_economics.margin_evaluability is Evaluability.EVALUABLE and not fx_missing
        )

        # --- 4. El agente, con lo que el desglose ya sabe -------------------
        result = self._run_agent(
            research=research,
            quote=quote,
            sale_price=sale_price,
            monthly_fixed_costs=monthly_fixed_costs,
            monthly_unit_sales_base=monthly_unit_sales_base,
            unit_economics=unit_economics,
            evaluable=evaluable,
        )

        risks = list(result.risks)
        if not evaluable:
            risks.append(
                "not evaluable: "
                + ", ".join(missing)
                + " - this is the absence of a result, not a negative one"
            )

        analysis = EconomicAnalysis(
            product_id=product_id,
            supplier_quote_id=supplier_quote_id,
            sale_price=sale_price,
            monthly_fixed_costs=monthly_fixed_costs,
            margin_percent=(
                float(unit_economics.contribution_margin_percent)
                if evaluable and unit_economics.contribution_margin_percent is not None
                else None
            ),
            recommendation=result.recommendation,
            confidence=result.confidence,
            channel=channel_key,
            currency=currency,
            units_per_order=int(units.value) if units.known and units.value else None,
            units_per_order_provenance=units.provenance.value if units.known else None,
            margin_evaluability=(
                unit_economics.margin_evaluability.value
                if evaluable
                else Evaluability.NOT_EVALUABLE.value
            ),
            cac_evaluability=(
                unit_economics.cac_evaluability.value
                if evaluable
                else Evaluability.NOT_EVALUABLE.value
            ),
            missing_inputs=missing or None,
            contribution_margin_per_unit=self._amount_or_none(
                unit_economics.contribution_margin_per_unit, evaluable
            ),
            contribution_margin_per_order=self._amount_or_none(
                unit_economics.contribution_margin_per_order, evaluable
            ),
            allocated_fixed_cost_per_order=self._amount_or_none(
                unit_economics.allocated_fixed_cost_per_order, evaluable
            ),
            max_breakeven_cac=self._amount_or_none(unit_economics.max_breakeven_cac, evaluable),
            fx_conversions=[conversion_to_json(c) for c in conversions] or None,
            data={
                **result.data,
                "risks": risks,
                "evidence": result.evidence,
                "unit_economics": self._unit_economics_json(unit_economics, breakdown),
                # La identidad viaja **aparte** del resultado económico: es un
                # riesgo del proveedor, no un término del margen.
                "supplier_identity": self._identity_json(quote),
            },
            correlation_id=correlation_id,
        )
        self._db.add(analysis)
        self._db.add(
            AuditLog(
                actor=ECONOMICS_AGENT_ACTOR,
                action="economics.run",
                resource=f"economics:{correlation_id}",
                before=None,
                after={
                    "product_id": product_id,
                    "supplier_quote_id": supplier_quote_id,
                    "channel": channel_key,
                    "margin_evaluability": analysis.margin_evaluability,
                },
                correlation_id=correlation_id,
            )
        )
        self._db.commit()
        return analysis

    # ------------------------------------------------------------------ apoyo

    @staticmethod
    def _amount_or_none(amount: Money | None, evaluable: bool) -> Decimal | None:
        return None if amount is None or not evaluable else amount.amount

    def _quote_costs_in(
        self, quote: SupplierQuote, *, currency: str, on: datetime.date
    ) -> tuple[QuoteCosts, list[Conversion], bool]:
        """Los costes de la cotización, en la moneda del análisis.

        Devuelve además **todas** las conversiones aplicadas —el precio y la
        logística se convierten por separado— y si faltó la tasa. Sin tasa no se
        convierte nada: los importes se quedan fuera y el análisis será no
        evaluable.
        """
        supplier = self._db.get(Supplier, quote.supplier_id)
        quote_currency = quote.currency
        rates = exchange_rates_for(self._db)
        conversions: list[Conversion] = []
        missing_rate = False

        def to_analysis(value: float | None) -> Money | None:
            nonlocal missing_rate
            if value is None or quote_currency is None:
                return None
            amount = Money.from_legacy_float(value, quote_currency)
            if amount.currency == currency:
                return amount
            rate = rates.rate_for(base=amount.currency, quote=currency, on=on)
            if rate is None:
                missing_rate = True
                return None
            try:
                applied = convert(amount, to=currency, rate=rate, on=on)
            except NoRateAvailableError:
                # Incluye la tasa caducada: una tasa vieja tiene aspecto de dato
                # y no lo es, así que se trata como si no hubiera ninguna.
                missing_rate = True
                return None
            conversions.append(applied)
            return applied.converted

        product_cost = to_analysis(quote.unit_price)
        logistics_cost = to_analysis(quote.logistics_cost_per_unit)

        # Una cifra de logística sin procedencia propia la sostiene quien
        # sostiene la cotización: es el criterio con el que el Milestone 39 la
        # escribe. Si tampoco la cotización dice quién la sostiene, el importe
        # **no se usa**: un número que nadie respalda es lo que ese milestone
        # quitó de en medio, y usarlo aquí lo devolvería por la ventana.
        quote_provenance = parse(quote.provenance)
        logistics_provenance = parse(quote.logistics_provenance)
        if logistics_provenance is SupplierFactProvenance.UNKNOWN:
            logistics_provenance = quote_provenance
        if logistics_provenance is SupplierFactProvenance.UNKNOWN:
            logistics_cost = None
        if quote_provenance is SupplierFactProvenance.UNKNOWN:
            product_cost = None

        origin = (supplier.region if supplier else None) or ""
        destination = quote.destination_market or ""
        same_market = bool(origin) and origin.strip().lower() == destination.strip().lower()

        return (
            QuoteCosts(
                product=product_cost,
                product_provenance=quote_provenance,
                product_source=quote.source,
                logistics=logistics_cost,
                logistics_provenance=logistics_provenance,
                logistics_source=quote.source,
                incoterm=quote.incoterm,
                same_market=same_market,
            ),
            conversions,
            missing_rate,
        )

    def _channel_fee(self, channel_key: str, category: str, currency: str) -> ChannelFee | None:
        """Lo que cobra el canal, cuando hay de dónde sacarlo.

        En una web propia no se pregunta: no hay intermediario. En un
        marketplace se usa **la misma fuente** que ya usaba el agente de
        listings, para que no haya dos comisiones distintas del mismo canal —
        que es una de las dos formas de contar un coste dos veces.
        """
        channel = channel_for(channel_key)
        if channel.kind is not ChannelKind.MARKETPLACE:
            return None
        platform = channel.key.split(":", 1)[1] if ":" in channel.key else channel.key
        directory = ProviderRegistry().resolve(IntegrationDomain.MARKETPLACES)
        getter = getattr(directory, "get_marketplace_data", None)
        data = getter(category=category, platform=platform) if getter else None
        if not data:
            return None
        commission = data["commission"]
        return ChannelFee(
            referral_fee_percent=Decimal(str(commission["referral_fee_percent"])),
            fulfillment_fee_per_unit=Money.from_legacy_float(
                commission["fulfillment_fee_per_unit"], currency
            ),
            # Las comisiones de hoy son fixtures, así que el margen que producen
            # es un margen simulado, y el resultado lo dirá.
            provenance=SupplierFactProvenance.SIMULATED,
            source="fixtures:mock-marketplace-directory",
        )

    @staticmethod
    def _payment_cost(
        channel_key: str,
        sale_price: Money,
        *,
        declared: float | None,
        currency: str,
        actor: str,
    ) -> tuple[Money | None, SupplierFactProvenance, str | None]:
        """Lo que cuesta cobrar, y quién lo sostiene.

        Lo declarado manda siempre. Si no hay nada declarado, la tarifa de
        fixture — **y solo donde la ADR 0008 admite datos simulados**. En un
        entorno que no los admite, el coste de pasarela se queda sin declarar y
        el análisis será no evaluable, que es lo correcto: un 2,9 % del precio
        es una séptima parte de un margen del 20 %.
        """
        if declared is not None:
            return (
                Money.from_legacy_float(declared, currency),
                SupplierFactProvenance.DECLARED,
                f"manual:{actor}",
            )
        if not get_settings().allows_simulated_providers:
            return (None, SupplierFactProvenance.UNKNOWN, None)
        fee = MockChannelCostDirectory().payment_fee_for(
            channel_kind=channel_for(channel_key).kind.value
        )
        if fee is None:
            return (None, SupplierFactProvenance.UNKNOWN, None)
        amount = sale_price * fee.percent_of_price + Money(
            amount=fee.fixed_per_transaction, currency=currency
        )
        return (amount, SupplierFactProvenance.SIMULATED, CHANNEL_COST_FIXTURES)

    @staticmethod
    def _expected_monthly_orders(
        monthly_unit_sales_base: float | None,
        units: DeclaredQuantity,
        *,
        research: ProductAnalysis | None = None,
    ) -> DeclaredQuantity:
        """Pedidos al mes = unidades al mes / unidades por pedido.

        Hasta el Milestone 40 estas dos cifras eran la misma con dos nombres.
        Faltando cualquiera de las dos **no hay pedidos esperados**: no se supone
        que una unidad sea un pedido.

        Cuando nadie declara las unidades mensuales se derivan de la señal de
        demanda con el mismo estimador que usa el agente — y esa derivación es
        un **marcador de posición documentado** (`scenarios.py`), así que el
        número sale marcado como simulado y arrastra su procedencia hasta el
        techo de CAC.
        """
        if not units.known or units.value is None:
            return DeclaredQuantity.unknown()

        provenance = units.provenance
        source = "derived: monthly units / units per order"
        monthly_units = monthly_unit_sales_base
        if monthly_units is None:
            demand = (research.data or {}).get("demand_signal") if research else None
            if demand is None:
                return DeclaredQuantity.unknown()
            monthly_units = estimate_monthly_unit_sales(float(demand))
            provenance = SupplierFactProvenance.SIMULATED
            source = "derived: simulated demand-to-sales conversion (app/economics/scenarios.py)"

        orders = Decimal(str(monthly_units)) / units.value
        if orders <= 0:
            return DeclaredQuantity.unknown()
        return DeclaredQuantity(value=orders, provenance=provenance, source=source)

    def _run_agent(
        self,
        *,
        research: ProductAnalysis | None,
        quote: SupplierQuote,
        sale_price: float,
        monthly_fixed_costs: float,
        monthly_unit_sales_base: float | None,
        unit_economics: UnitEconomicsResult,
        evaluable: bool,
    ) -> AgentResult:
        if not evaluable:
            # Una duda, no un veredicto: el ActionGate veta los `NO_GO` que
            # gastan, y «no se puede saber» no puede parar el sistema como si
            # fuera «va mal».
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[],
                assumptions=["the analysis could not be evaluated with the data available"],
                data={"scenarios": {}},
            )

        margin = unit_economics.contribution_margin_per_unit
        assert margin is not None
        unit_landed_cost = float(
            (Money.from_legacy_float(sale_price, margin.currency) - margin).rounded().amount
        )
        return self._agent.run(
            {
                "unit_landed_cost": unit_landed_cost,
                "sale_price": sale_price,
                "demand_signal": (research.data or {}).get("demand_signal") if research else None,
                "monthly_unit_sales_base": monthly_unit_sales_base,
                "monthly_fixed_costs": monthly_fixed_costs,
                "supplier_verified": supplier_identity_verified(self._db, quote),
                "lead_time_days": quote.lead_time_days,
                "competition_level": (
                    (research.data or {}).get("competition_level") if research else None
                ),
            }
        )

    @staticmethod
    def _unit_economics_json(result: UnitEconomicsResult, breakdown: CostBreakdown) -> dict:
        """El resultado y **de qué está hecho**, componente a componente.

        Los importes salen como cadena (`app.money.serialization`): esta columna
        es JSON, `json.dumps` no sabe serializar un `Decimal`, y convertirlo a
        `float` para que pase tiraría la exactitud recién ganada.
        """
        return {
            "currency": result.currency,
            "contribution_margin_per_unit": money_to_json(result.contribution_margin_per_unit),
            "contribution_margin_percent": decimal_to_json(result.contribution_margin_percent),
            "contribution_margin_per_order": money_to_json(result.contribution_margin_per_order),
            "breakeven_cac_before_fixed_costs": money_to_json(
                result.breakeven_cac_before_fixed_costs
            ),
            "allocated_fixed_cost_per_order": money_to_json(result.allocated_fixed_cost_per_order),
            "max_breakeven_cac": money_to_json(result.max_breakeven_cac),
            "margin_evaluability": result.margin_evaluability.value,
            "cac_evaluability": result.cac_evaluability.value,
            "missing_inputs": list(result.missing_inputs),
            "omitted_costs": list(result.omitted_costs),
            "weakest_provenance": result.weakest_provenance.value,
            "orders_per_acquisition": str(result.orders_per_acquisition),
            "components": [
                {
                    "concept": c.concept.value,
                    "status": c.status.value,
                    "amount": money_to_json(c.amount),
                    "provenance": c.provenance.value,
                    "source": c.source,
                    "included_in": c.included_in.value if c.included_in else None,
                    "reason": c.reason,
                }
                for c in breakdown.components
            ],
        }

    def _identity_json(self, quote: SupplierQuote) -> dict:
        """Los tres ejes, separados y sin tocar la aritmética.

        Que un proveedor no esté verificado **no impide** calcular su margen: lo
        que hace es acompañarlo. Mezclarlos convertiría un riesgo en un error de
        cálculo.
        """
        supplier = self._db.get(Supplier, quote.supplier_id)
        return {
            "identity_verified": supplier_identity_verified(self._db, quote),
            "identity_provenance": parse(supplier.verification).value if supplier else "unknown",
            "commercial_reliability": (
                float(supplier.reliability_score)
                if supplier and supplier.reliability_score is not None
                else None
            ),
            "commercial_reliability_provenance": (
                parse(supplier.reliability_provenance).value if supplier else "unknown"
            ),
            "quote_provenance": parse(quote.provenance).value,
            "note": (
                "identity, commercial reliability and quote provenance are three separate "
                "facts; none of them is a term of the margin"
            ),
        }
