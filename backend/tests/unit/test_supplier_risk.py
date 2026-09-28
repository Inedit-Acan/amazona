"""El riesgo por dimensiones del plan maestro §11 (Milestone 39).

Lo que más se comprueba aquí no es que los niveles sean los correctos —eso es
discutible y está escrito para poder discutirse— sino dos cosas que no lo son:
que **no hay puntuación total** y que **lo no evaluado no vale «bajo»**.
"""

from app.sourcing.capabilities import CapabilityAnswer, SupplyCapability
from app.sourcing.provenance import SupplierFactProvenance
from app.sourcing.risk import (
    RiskDimension,
    RiskLevel,
    SupplierRiskFacts,
    SupplierRiskProfile,
    assess,
)

AUDIT = SupplierFactProvenance.THIRD_PARTY_VERIFIED
CLAIM = SupplierFactProvenance.SUPPLIER_CLAIM


def answer(capability, supported, provenance=CLAIM):
    return CapabilityAnswer(capability=capability, supported=supported, provenance=provenance)


def test_the_eight_dimensions_of_the_plan_are_all_there():
    assert {d.value for d in RiskDimension} == {
        "identity",
        "financial",
        "quality",
        "delivery",
        "legal",
        "fraud",
        "dependency",
        "geopolitical_logistics",
    }


def test_there_is_no_overall_score_and_that_is_deliberate():
    """§11: «No convertirlo inicialmente en un único score opaco»."""
    profile = assess(SupplierRiskFacts())

    assert not hasattr(profile, "score")
    assert not hasattr(profile, "overall")
    assert not hasattr(profile, "total")
    assert isinstance(profile, SupplierRiskProfile)


def test_knowing_nothing_produces_eight_unknowns_not_eight_lows():
    """Un riesgo de fraude «bajo» porque nadie miró es una compra a ciegas que
    parece hecha con los ojos abiertos."""
    profile = assess(SupplierRiskFacts())

    assert len(profile.assessments) == len(RiskDimension)
    assert set(profile.unassessed) == set(RiskDimension)
    assert profile.at(RiskLevel.LOW) == ()


def test_every_assessment_explains_itself():
    profile = assess(SupplierRiskFacts(country="PL", verification=AUDIT))

    for assessment in profile.assessments:
        assert assessment.rationale.strip()


def test_an_assessment_that_has_a_level_is_an_amazona_estimate():
    """No hay fuente externa de riesgo de proveedor, y no se finge que la haya."""
    profile = assess(SupplierRiskFacts(country="PL", verification=AUDIT))

    identity = profile.of(RiskDimension.IDENTITY)
    assert identity.level is RiskLevel.LOW
    assert identity.provenance is SupplierFactProvenance.AMAZONA_ESTIMATE
    assert identity.basis


def test_identity_verified_by_a_third_party_is_low_risk():
    profile = assess(SupplierRiskFacts(country="PL", website="https://x.example", verification=AUDIT))

    assert profile.of(RiskDimension.IDENTITY).level is RiskLevel.LOW


def test_identity_backed_only_by_the_supplier_is_medium():
    profile = assess(SupplierRiskFacts(country="PL", verification=CLAIM))

    assert profile.of(RiskDimension.IDENTITY).level is RiskLevel.MEDIUM


def test_fixture_data_is_high_fraud_risk_because_the_company_does_not_exist():
    profile = assess(SupplierRiskFacts(verification=SupplierFactProvenance.SIMULATED))

    fraud = profile.of(RiskDimension.FRAUD)
    assert fraud.level is RiskLevel.HIGH
    assert "no existe" in fraud.rationale


def test_prepaying_an_unverified_supplier_is_high_financial_risk():
    profile = assess(
        SupplierRiskFacts(payment_terms="30 % anticipo, 70 % contra BL", verification=CLAIM)
    )

    assert profile.of(RiskDimension.FINANCIAL).level is RiskLevel.HIGH


def test_prepaying_an_audited_supplier_is_only_medium():
    profile = assess(
        SupplierRiskFacts(payment_terms="30 % anticipo, 70 % contra BL", verification=AUDIT)
    )

    assert profile.of(RiskDimension.FINANCIAL).level is RiskLevel.MEDIUM


def test_unknown_payment_terms_are_unknown_not_low():
    assert profile_level(SupplierRiskFacts(), RiskDimension.FINANCIAL) is RiskLevel.UNKNOWN


def profile_level(facts, dimension):
    return assess(facts).of(dimension).level


def test_a_reliability_nobody_audited_never_reaches_low_quality_risk():
    facts = SupplierRiskFacts(reliability=0.99, reliability_provenance=CLAIM)

    assert profile_level(facts, RiskDimension.QUALITY) is RiskLevel.MEDIUM


def test_an_unknown_reliability_is_not_a_zero_reliability():
    facts = SupplierRiskFacts(reliability=None)

    assert profile_level(facts, RiskDimension.QUALITY) is RiskLevel.UNKNOWN


def test_delivery_is_low_only_with_sla_tracking_and_a_short_lead():
    facts = SupplierRiskFacts(
        lead_time_days=5,
        transit_days=4,
        capabilities=(
            answer(SupplyCapability.SLA, True),
            answer(SupplyCapability.TRACKING, True),
        ),
    )

    assert profile_level(facts, RiskDimension.DELIVERY) is RiskLevel.LOW


def test_a_long_total_lead_time_is_high_delivery_risk():
    facts = SupplierRiskFacts(lead_time_days=25, transit_days=20)

    assert profile_level(facts, RiskDimension.DELIVERY) is RiskLevel.HIGH


def test_returns_without_an_eu_address_is_not_the_same_as_returns_with_one():
    with_address = SupplierRiskFacts(
        capabilities=(
            answer(SupplyCapability.RETURNS, True),
            answer(SupplyCapability.EU_RETURN_ADDRESS, True),
        )
    )
    without = SupplierRiskFacts(
        capabilities=(
            answer(SupplyCapability.RETURNS, True),
            answer(SupplyCapability.EU_RETURN_ADDRESS, False),
        )
    )

    assert profile_level(with_address, RiskDimension.LEGAL) is RiskLevel.LOW
    assert profile_level(without, RiskDimension.LEGAL) is RiskLevel.HIGH


def test_a_single_supplier_for_a_product_is_high_dependency_risk():
    assert profile_level(
        SupplierRiskFacts(alternatives_for_product=1), RiskDimension.DEPENDENCY
    ) is RiskLevel.HIGH


def test_not_having_counted_the_alternatives_is_not_the_same_as_having_one():
    assert profile_level(
        SupplierRiskFacts(alternatives_for_product=None), RiskDimension.DEPENDENCY
    ) is RiskLevel.UNKNOWN


def test_same_market_origin_and_destination_is_low_geopolitical_risk():
    facts = SupplierRiskFacts(region="eu", destination_market="eu")

    assert profile_level(facts, RiskDimension.GEOPOLITICAL_LOGISTICS) is RiskLevel.LOW


def test_a_border_crossing_without_ddp_is_high_geopolitical_risk():
    facts = SupplierRiskFacts(region="cn", destination_market="eu", incoterm="FOB")

    assert profile_level(facts, RiskDimension.GEOPOLITICAL_LOGISTICS) is RiskLevel.HIGH


def test_a_country_and_a_market_are_not_comparable_without_a_catalogue():
    """Decir «cruza una frontera» porque `es` no es la misma cadena que `eu`
    sería inventarse una aduana entre Valencia y la Unión Europea."""
    facts = SupplierRiskFacts(country="es", destination_market="eu")

    assert profile_level(facts, RiskDimension.GEOPOLITICAL_LOGISTICS) is RiskLevel.UNKNOWN


def test_ddp_softens_a_border_crossing_without_erasing_it():
    facts = SupplierRiskFacts(region="cn", destination_market="eu", incoterm="DDP")

    assert profile_level(facts, RiskDimension.GEOPOLITICAL_LOGISTICS) is RiskLevel.MEDIUM


def test_filtering_by_level_is_not_scoring():
    facts = SupplierRiskFacts(
        region="cn",
        destination_market="eu",
        incoterm="FOB",
        verification=SupplierFactProvenance.SIMULATED,
    )

    profile = assess(facts)

    highs = profile.at(RiskLevel.HIGH)
    assert {a.dimension for a in highs} >= {
        RiskDimension.FRAUD,
        RiskDimension.GEOPOLITICAL_LOGISTICS,
    }
    # Sigue habiendo ocho respuestas: filtrar no reduce nada.
    assert len(profile.assessments) == len(RiskDimension)

