"""Economía por canal, divisas y techo de CAC, sobre la base de datos
(Milestone 40, ADR 0018)."""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.exchange_rate import ExchangeRate as ExchangeRateRow
from app.db.models.product import Product
from app.db.models.product_analysis import ProductAnalysis
from app.db.models.supplier import Supplier
from app.db.models.supplier_quote import SupplierQuote
from app.economics.service import EconomicAnalysisService
from app.money.rates import MAX_RATE_AGE_DAYS

TODAY = datetime.date(2026, 9, 29)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def product(db_session: Session) -> Product:
    product = Product(name="Wireless earbuds", category="electronics", created_by="owner")
    db_session.add(product)
    db_session.commit()
    db_session.add(
        ProductAnalysis(
            product_id=product.id,
            analysis_type="research",
            opportunity_score=0.6,
            confidence=0.85,
            data={"demand_signal": 0.6, "competition_level": "low"},
            correlation_id="corr-research",
        )
    )
    db_session.commit()
    return product


def make_quote(db_session: Session, product: Product, **overrides) -> SupplierQuote:
    supplier = Supplier(
        name=overrides.pop("supplier_name", "Fábrica Real S.L."),
        verification=overrides.pop("verification", "supplier_claim"),
        verified_by=overrides.pop("verified_by", None),
        region=overrides.pop("region", "eu"),
    )
    db_session.add(supplier)
    db_session.commit()
    fields = {
        "unit_price": 4.0,
        "currency": "EUR",
        "provenance": "supplier_claim",
        "source": "manual:owner",
        "logistics_cost_per_unit": 1.0,
        "logistics_provenance": "supplier_claim",
        "incoterm": "DDP",
        "destination_market": "eu",
        "moq": 10,
        "lead_time_days": 7,
    }
    fields.update(overrides)
    quote = SupplierQuote(
        product_id=product.id, supplier_id=supplier.id, correlation_id="corr-sourcing", **fields
    )
    db_session.add(quote)
    db_session.commit()
    return quote


def run(db_session: Session, product: Product, quote: SupplierQuote, **overrides):
    payload = {
        "product_id": product.id,
        "supplier_quote_id": quote.id,
        "sale_price": 20.0,
        "monthly_fixed_costs": 500.0,
        "monthly_unit_sales_base": 300.0,
        "units_per_order": 1,
        "payment_cost_per_unit": 0.83,
        "correlation_id": "corr-econ",
        "on": TODAY,
    }
    payload.update(overrides)
    return EconomicAnalysisService(db_session).run_analysis(**payload)


# --- canal -------------------------------------------------------------------


def test_own_web_has_no_marketplace_commission(db_session, product):
    quote = make_quote(db_session, product)

    analysis = run(db_session, product, quote, channel="own_web")

    channel = next(
        c for c in analysis.data["unit_economics"]["components"] if c["concept"] == "channel"
    )
    assert channel["status"] == "not_applicable"
    assert channel["amount"] is None
    assert "comisión" in channel["reason"]


def test_a_marketplace_charges_a_commission_and_own_web_does_not(db_session, product):
    """La comparación que justifica todo el milestone: el mismo producto deja
    menos margen en un marketplace, y hasta aquí Economía no lo sabía."""
    quote = make_quote(db_session, product)

    own_web = run(db_session, product, quote, channel="own_web", correlation_id="c-web")
    amazon = run(
        db_session,
        product,
        quote,
        channel="marketplace:amazon",
        # En un marketplace el cobro va dentro de la comisión: no se declara
        # aparte, y el desglose lo dirá.
        payment_cost_per_unit=None,
        correlation_id="c-amazon",
    )

    assert own_web.channel == "own_web"
    assert amazon.channel == "marketplace:amazon"
    assert own_web.contribution_margin_per_unit > amazon.contribution_margin_per_unit
    assert own_web.max_breakeven_cac > amazon.max_breakeven_cac


def test_in_a_marketplace_the_payment_cost_is_inside_the_commission(db_session, product):
    """La tercera instancia del mecanismo contra la doble contabilización: no
    es cero y no es desconocido, está dentro de otra cosa."""
    quote = make_quote(db_session, product)

    analysis = run(
        db_session, product, quote, channel="marketplace:amazon", payment_cost_per_unit=None
    )

    payment = next(
        c for c in analysis.data["unit_economics"]["components"] if c["concept"] == "payment"
    )
    assert payment["status"] == "included_in_another"
    assert payment["included_in"] == "channel"
    assert payment["amount"] is None


def test_a_non_transactional_channel_has_no_unit_economics(db_session, product):
    """En una superficie de búsqueda se descubre, no se cobra."""
    quote = make_quote(db_session, product)

    with pytest.raises(ValueError, match="not a transactional channel"):
        run(db_session, product, quote, channel="search:google")


def test_an_undeclared_channel_fails(db_session, product):
    quote = make_quote(db_session, product)

    with pytest.raises(ValueError):
        run(db_session, product, quote, channel="marketplace:inventado")


# --- doble contabilización ---------------------------------------------------


def test_ddp_puts_the_duties_inside_the_product_price(db_session, product):
    quote = make_quote(db_session, product, incoterm="DDP")

    analysis = run(db_session, product, quote)

    duties = next(
        c for c in analysis.data["unit_economics"]["components"] if c["concept"] == "import"
    )
    assert duties["status"] == "included_in_another"
    assert duties["included_in"] == "product"


def test_our_logistics_estimate_already_contains_the_duties(db_session, product):
    """`estimate_logistics_cost` aplica un factor de aduana: restar el arancel
    aparte lo contaría dos veces."""
    quote = make_quote(
        db_session,
        product,
        region="china",
        destination_market="eu",
        incoterm=None,
        logistics_provenance="amazona_estimate",
    )

    analysis = run(db_session, product, quote)

    duties = next(
        c for c in analysis.data["unit_economics"]["components"] if c["concept"] == "import"
    )
    assert duties["status"] == "included_in_another"
    assert duties["included_in"] == "logistics"


def test_same_market_means_there_is_no_import_at_all(db_session, product):
    quote = make_quote(
        db_session, product, region="eu", destination_market="eu", incoterm="FOB"
    )

    analysis = run(db_session, product, quote)

    duties = next(
        c for c in analysis.data["unit_economics"]["components"] if c["concept"] == "import"
    )
    assert duties["status"] == "not_applicable"


def test_an_unclaimed_supplier_logistics_leaves_the_duties_unknown(db_session, product):
    """Una cifra de transporte que dice el proveedor no dice nada del arancel,
    y suponerlo sería inventarlo."""
    quote = make_quote(
        db_session,
        product,
        region="china",
        destination_market="eu",
        incoterm="FOB",
        logistics_provenance="supplier_claim",
    )

    analysis = run(db_session, product, quote)

    assert analysis.margin_evaluability == "not_evaluable"
    assert "import" in analysis.missing_inputs


def test_the_margin_adds_each_cost_exactly_once(db_session, product):
    quote = make_quote(db_session, product)

    analysis = run(db_session, product, quote)

    # 20 − 4,00 producto − 1,00 logística − 0,83 pasarela = 14,17
    assert analysis.contribution_margin_per_unit == Decimal("14.1700")
    concepts = [c["concept"] for c in analysis.data["unit_economics"]["components"]]
    assert len(concepts) == len(set(concepts))


# --- divisas -----------------------------------------------------------------


def declare_rate(db_session: Session, *, effective_date: datetime.date, rate="0.92"):
    db_session.add(
        ExchangeRateRow(
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal(rate),
            effective_date=effective_date,
            source="manual:owner",
            provenance="declared",
        )
    )
    db_session.commit()


def test_a_declared_rate_converts_and_the_conversion_is_stored(db_session, product):
    quote = make_quote(db_session, product, currency="USD", unit_price=4.0)
    declare_rate(db_session, effective_date=TODAY)

    analysis = run(db_session, product, quote)

    # Dos conversiones: el precio y la logística se convierten por separado, y
    # guardar solo la última dejaría la otra sin rastro.
    assert len(analysis.fx_conversions) == 2
    assert all(c["pair"] == "USD/EUR" for c in analysis.fx_conversions)
    assert all(c["provenance"] == "declared" for c in analysis.fx_conversions)
    assert all(c["source"] == "manual:owner" for c in analysis.fx_conversions)
    assert {c["source_amount"] for c in analysis.fx_conversions} == {"4.0000", "1.0000"}
    assert analysis.currency == "EUR"
    assert analysis.margin_evaluability == "evaluable"


def test_a_declared_rate_wins_over_the_fixture_one(db_session, product):
    """Lo que una persona ha declarado es un dato del mundo; el fixture no."""
    quote = make_quote(db_session, product, currency="USD")
    declare_rate(db_session, effective_date=TODAY, rate="0.80")

    analysis = run(db_session, product, quote)

    assert analysis.fx_conversions[0]["rate"] == "0.80000000"
    assert analysis.fx_conversions[0]["provenance"] == "declared"


def test_a_stale_rate_is_treated_as_no_rate_at_all(db_session, product, monkeypatch):
    """Una tasa de hace meses tiene aspecto de dato y no lo es."""
    monkeypatch.setattr(
        "app.money.resolver.get_settings", lambda: _no_simulated_providers()
    )
    quote = make_quote(db_session, product, currency="USD")
    declare_rate(
        db_session, effective_date=TODAY - datetime.timedelta(days=MAX_RATE_AGE_DAYS + 5)
    )

    analysis = run(db_session, product, quote)

    assert analysis.margin_evaluability == "not_evaluable"
    assert "exchange_rate" in analysis.missing_inputs
    assert analysis.fx_conversions is None


def test_without_a_rate_the_analysis_is_not_evaluable_and_never_one_to_one(
    db_session, product, monkeypatch
):
    monkeypatch.setattr(
        "app.money.resolver.get_settings", lambda: _no_simulated_providers()
    )
    quote = make_quote(db_session, product, currency="USD", unit_price=4.0)

    analysis = run(db_session, product, quote)

    assert analysis.margin_evaluability == "not_evaluable"
    assert "exchange_rate" in analysis.missing_inputs
    assert analysis.margin_percent is None
    assert analysis.contribution_margin_per_unit is None
    # Y sobre todo: no ha salido un margen calculado como si 1 USD fuese 1 EUR.
    assert analysis.recommendation != "NO_GO"


class _NoSimulatedProviders:
    """Un entorno que no admite fixtures: allí no hay tasa de demostración, y
    una cotización en otra moneda se queda sin convertir (ADR 0008)."""

    allows_simulated_providers = False


def _no_simulated_providers() -> _NoSimulatedProviders:
    return _NoSimulatedProviders()


# --- no evaluable no es un resultado negativo -------------------------------


def test_not_evaluable_is_a_doubt_and_never_a_veto(db_session, product, monkeypatch):
    """El ActionGate veta los `NO_GO` que gastan. «No se puede saber» no puede
    parar el sistema como si fuera «va mal» (ADR 0011)."""
    monkeypatch.setattr("app.money.resolver.get_settings", lambda: _no_simulated_providers())
    quote = make_quote(db_session, product, currency="USD")

    analysis = run(db_session, product, quote)

    assert analysis.recommendation == "REVIEW"

    from app.gates.action_gate import (
        GateInput,
        GateOutcome,
        SideEffectAction,
        evaluate_action,
    )

    decision = evaluate_action(
        GateInput(
            # Una acción que gasta dinero: es donde un `NO_GO` sería un veto.
            action=SideEffectAction.SPEND_MONEY,
            kill_switch_enabled=True,
            economics_recommendation=analysis.recommendation,
        )
    )
    assert decision.outcome is not GateOutcome.DENY


# --- los tres ejes, separados ------------------------------------------------


def test_an_unverified_supplier_still_produces_a_margin(db_session, product):
    """La identidad no es una puerta para calcular: lo que hace es acompañar."""
    quote = make_quote(db_session, product, verification="supplier_claim")

    analysis = run(db_session, product, quote)

    assert analysis.margin_evaluability == "evaluable"
    assert analysis.contribution_margin_per_unit is not None
    identity = analysis.data["supplier_identity"]
    assert identity["identity_verified"] is False
    assert identity["quote_provenance"] == "supplier_claim"


def test_the_three_axes_are_stored_separately(db_session, product):
    quote = make_quote(
        db_session,
        product,
        verification="third_party_verified",
        verified_by="Bureau of Test",
        provenance="supplier_claim",
    )
    supplier = db_session.get(Supplier, quote.supplier_id)
    supplier.reliability_score = 0.4
    supplier.reliability_provenance = "supplier_claim"
    db_session.commit()

    identity = run(db_session, product, quote).data["supplier_identity"]

    # Verificado, poco fiable, y con un precio que solo sostiene el proveedor:
    # tres hechos distintos que no se mezclan.
    assert identity["identity_verified"] is True
    assert identity["commercial_reliability"] == 0.4
    assert identity["quote_provenance"] == "supplier_claim"
