"""El contrato de Product Intelligence y el adaptador de fixtures (Milestone 34).

Dos cosas que probar aquí. Una: que el mock sigue diciendo **exactamente** lo
mismo que decía antes —este milestone cambia de dónde viene el dato, no el dato—.
Otra: que ahora cada número sale con los nueve campos de procedencia del plan
maestro §8, y marcado como simulado.
"""

import datetime

import pytest

from app.agents.product_research import ProductResearchAgent, provenance_of
from app.integrations.ports import CandidateSignals, Signal, SignalBasis, SignalKind
from app.integrations.product_intelligence.mock import (
    COMPETITION_VALUE,
    MockProductSignalProvider,
    competition_level,
)


@pytest.fixture()
def provider() -> MockProductSignalProvider:
    return MockProductSignalProvider()


def test_the_fixture_provider_knows_all_five_signals(provider):
    assert provider.supports() == frozenset(SignalKind)


def test_every_signal_carries_the_nine_provenance_fields(provider):
    """§8: «nunca almacenar solo un número final sin procedencia»."""
    candidates = provider.discover(category="home", keywords=[], market="us", max_results=3)

    assert candidates
    for candidate in candidates:
        assert candidate.signals
        for signal in candidate.signals:
            assert signal.provider == "fixtures"
            assert signal.source.endswith("mock_trends_provider.py")
            assert signal.query == candidate.name
            assert signal.market == "us"
            assert isinstance(signal.observed_at, datetime.datetime)
            assert signal.observed_at.tzinfo is not None
            assert 0.0 <= signal.value <= 1.0
            assert 0.0 <= signal.confidence <= 1.0
            assert signal.method
            assert signal.raw_reference


def test_fixture_signals_say_they_are_fixtures(provider):
    """Lo importante de todo el milestone: un valor inventado y uno medido
    dejan de ser indistinguibles."""
    candidates = provider.discover(category="home", keywords=[], market="us", max_results=2)

    for candidate in candidates:
        assert all(signal.simulated for signal in candidate.signals)
        assert all("not a measurement" in signal.method for signal in candidate.signals)


def test_a_fixture_is_not_confident_just_because_it_is_deterministic(provider):
    candidates = provider.discover(category="home", keywords=[], market="us", max_results=1)

    assert all(signal.confidence <= 0.3 for signal in candidates[0].signals)


def test_the_competition_label_survives_the_round_trip(provider):
    """La etiqueta que se enseña y el número que se guarda no pueden
    contradecirse: una traducción, en un sitio, en los dos sentidos."""
    for label, value in COMPETITION_VALUE.items():
        assert competition_level(value) == label


def test_the_same_numbers_as_before_reach_the_agent():
    """Regresión del dataset: el Milestone 34 cambia el camino, no el dato."""
    result = ProductResearchAgent(MockProductSignalProvider()).run(
        {"category": "electronics", "max_results": 4}
    )

    by_name = {c["name"]: c for c in result.data["candidates"]}
    # Las mismas cifras del fixture de Fase 3.
    assert by_name["Wireless earbuds pro"]["demand_signal"] == 0.82
    assert by_name["Wireless earbuds pro"]["competition_level"] == "medium"
    assert by_name["Smart water bottle"]["opportunity_score"] == 0.65
    # Y el mismo ganador de siempre: 0,65 × 1,0 bate a 0,82 × 0,6.
    assert result.data["candidates"][0]["name"] == "Smart water bottle"


def test_the_score_formula_did_not_change():
    """Plan maestro §9: primero fuentes reales, después el score. Aquí no se
    toca."""
    result = ProductResearchAgent(MockProductSignalProvider()).run(
        {"category": "home", "max_results": 5}
    )

    for candidate in result.data["candidates"]:
        factor = {"low": 1.0, "medium": 0.6, "high": 0.3}[candidate["competition_level"]]
        assert candidate["opportunity_score"] == round(candidate["demand_signal"] * factor, 4)


# --- Procedencia -----------------------------------------------------------


#: Un fixture no declara la misma confianza que una medición: el techo por base
#: lo impide, y este 0,3 es el que emite el mock de verdad (Milestone 37).
_DEFAULT_CONFIDENCE = {
    SignalBasis.MEASURED: 0.5,
    SignalBasis.ESTIMATED: 0.5,
    SignalBasis.SIMULATED: 0.3,
}

#: Proveedores con permiso de puntuar en la matriz de derechos, para que estas
#: pruebas midan la procedencia y no los derechos de uso (ADR 0015).
_PROVIDER_FOR = {
    SignalBasis.MEASURED: "wikimedia-pageviews",
    SignalBasis.ESTIMATED: "wikimedia-pageviews",
    SignalBasis.SIMULATED: "fixtures",
}


def signal(kind: SignalKind, *, basis: SignalBasis, confidence: float | None = None) -> Signal:
    return Signal(
        kind=kind,
        value=0.5,
        confidence=_DEFAULT_CONFIDENCE[basis] if confidence is None else confidence,
        provider=_PROVIDER_FOR[basis],
        source="somewhere",
        query="term",
        market="us",
        observed_at=datetime.datetime.now(datetime.UTC),
        method="…",
        basis=basis,
    )


SCORING = (SignalKind.DEMAND, SignalKind.COMPETITION)


def test_all_measured_is_real():
    candidate = CandidateSignals(
        name="x",
        category="home",
        signals=[
            signal(SignalKind.DEMAND, basis=SignalBasis.MEASURED),
            signal(SignalKind.COMPETITION, basis=SignalBasis.MEASURED),
        ],
    )

    assert provenance_of(candidate, SCORING) == "real"


def test_half_measured_is_mixed_and_says_so():
    """El caso peligroso: sin esta etiqueta, un número medio inventado se lee
    como medido."""
    candidate = CandidateSignals(
        name="x",
        category="home",
        signals=[
            signal(SignalKind.DEMAND, basis=SignalBasis.MEASURED),
            signal(SignalKind.COMPETITION, basis=SignalBasis.SIMULATED),
        ],
    )

    assert provenance_of(candidate, SCORING) == "mixed"


def test_nothing_measured_is_simulated():
    candidate = CandidateSignals(
        name="x",
        category="home",
        signals=[
            signal(SignalKind.DEMAND, basis=SignalBasis.SIMULATED),
            signal(SignalKind.COMPETITION, basis=SignalBasis.SIMULATED),
        ],
    )

    assert provenance_of(candidate, SCORING) == "simulated"


def test_nothing_at_all_is_unknown():
    assert provenance_of(CandidateSignals(name="x", category="home"), SCORING) == "unknown"


def test_a_real_signal_wins_over_a_filler_of_the_same_kind():
    candidate = CandidateSignals(
        name="x",
        category="home",
        signals=[
            signal(SignalKind.DEMAND, basis=SignalBasis.SIMULATED),
            signal(SignalKind.DEMAND, basis=SignalBasis.MEASURED),
        ],
    )

    chosen = candidate.signal(SignalKind.DEMAND)
    assert chosen is not None and chosen.simulated is False


def test_a_mixed_candidate_lowers_the_agents_confidence():
    """Un número medio real no merece la misma fe que uno medido."""

    class HalfReal:
        name = "half-real"

        def supports(self):
            return frozenset({SignalKind.DEMAND, SignalKind.COMPETITION})

        def discover(self, *, category, keywords, market, max_results):
            return [
                CandidateSignals(
                    name=f"candidate {index}",
                    category=category,
                    signals=[
                        signal(SignalKind.DEMAND, basis=SignalBasis.MEASURED),
                        signal(SignalKind.COMPETITION, basis=SignalBasis.SIMULATED),
                    ],
                )
                for index in range(2)
            ]

    result = ProductResearchAgent(HalfReal()).run({"category": "home", "max_results": 2})

    assert {c["provenance"] for c in result.data["candidates"]} == {"mixed"}
    assert result.confidence == 0.6
    assert "some signals are fixture data, not measurements" in result.assumptions


def test_a_candidate_without_competition_cannot_be_scored():
    """Con una fuente real que solo sabe de demanda, el score no se puede
    calcular — y no se inventa un factor de competencia para poder."""

    class DemandOnly:
        name = "demand-only"

        def supports(self):
            return frozenset({SignalKind.DEMAND})

        def discover(self, *, category, keywords, market, max_results):
            return [
                CandidateSignals(
                    name="measured thing",
                    category=category,
                    signals=[
            signal(SignalKind.DEMAND, basis=SignalBasis.MEASURED),
        ],
                )
            ]

    result = ProductResearchAgent(DemandOnly()).run({"category": "home", "max_results": 1})

    candidate = result.data["candidates"][0]
    assert candidate["opportunity_score"] is None
    assert candidate["competition_level"] is None
    assert candidate["provenance"] == "real"
    assert any("cannot be scored" in risk for risk in result.risks)
