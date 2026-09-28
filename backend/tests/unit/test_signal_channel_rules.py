"""Qué señal sirve para decidir sobre qué canal (Milestone 38, ADR 0016).

La propiedad que estos tests protegen es la que el propietario puso por escrito:
**una señal sin canal solo puede usarse como señal verdaderamente agnóstica, y
nunca interpretarse automáticamente como válida para todos los canales.**

El caso concreto que esto evita: que una competencia medida en un marketplace
—o peor, la de un fixture— decida sobre una web propia.
"""

import datetime

import pytest

from app.agents.product_research import ProductResearchAgent, may_score, scoring_filter
from app.integrations.channels import UnknownChannelError
from app.integrations.ports import (
    CHANNEL_BOUND_KINDS,
    CandidateSignals,
    ProductSignalProvider,
    Signal,
    SignalBasis,
    SignalKind,
)

OWN_WEB = "own_web"
EBAY = "marketplace:ebay"


def signal(
    kind: SignalKind,
    *,
    channel: str | None = None,
    value: float = 0.6,
    provider: str = "wikimedia-pageviews",
) -> Signal:
    return Signal(
        kind=kind,
        value=value,
        confidence=0.5,
        provider=provider,
        source="somewhere",
        query="Air fryer",
        market="us",
        observed_at=datetime.datetime(2026, 9, 28, tzinfo=datetime.UTC),
        method="…",
        basis=SignalBasis.MEASURED,
        channel=channel,
    )


def candidate(*signals: Signal) -> CandidateSignals:
    return CandidateSignals(name="Air fryer", category="home", signals=list(signals))


# --- Qué señales dependen del canal ----------------------------------------


def test_competition_and_the_two_demands_are_channel_bound():
    """«Cuánta competencia hay» es una pregunta incompleta sin decir dónde."""
    assert CHANNEL_BOUND_KINDS == frozenset(
        {SignalKind.COMPETITION, SignalKind.SEARCH_DEMAND, SignalKind.MARKETPLACE_DEMAND}
    )


def test_interest_and_the_product_axes_are_not():
    """El interés por un tipo de producto, su trayectoria, su riesgo regulatorio y
    lo fácil que es escalarlo son propiedades del producto, no del sitio donde se
    vende."""
    for kind in (
        SignalKind.DEMAND,
        SignalKind.FUTURE_OUTLOOK,
        SignalKind.REGULATORY_RISK,
        SignalKind.SCALABILITY,
    ):
        assert kind not in CHANNEL_BOUND_KINDS


# --- La regla ---------------------------------------------------------------


def test_a_channel_agnostic_signal_serves_any_decision():
    c = candidate(signal(SignalKind.DEMAND))

    assert c.usable_for_channel(c.signals[0], OWN_WEB)
    assert c.usable_for_channel(c.signals[0], None)


def test_a_channel_bound_signal_only_serves_its_own_channel():
    c = candidate(signal(SignalKind.COMPETITION, channel=EBAY))

    assert c.usable_for_channel(c.signals[0], EBAY)
    assert not c.usable_for_channel(c.signals[0], OWN_WEB)


def test_a_channel_bound_signal_without_a_channel_is_not_valid_for_all():
    """La lectura que hay que impedir: si valiera para todos, el relleno de un
    fixture decidiría sobre Amazon."""
    c = candidate(signal(SignalKind.COMPETITION))

    assert not c.usable_for_channel(c.signals[0], OWN_WEB)
    assert not c.usable_for_channel(c.signals[0], EBAY)
    # Y sí sirve para una decisión igualmente sin canal: eso es «agnóstica».
    assert c.usable_for_channel(c.signals[0], None)


def test_a_signal_from_another_channel_cannot_sneak_into_an_agnostic_decision():
    """Al revés también: la competencia de eBay no alimenta un score genérico."""
    c = candidate(signal(SignalKind.COMPETITION, channel=EBAY))

    assert not c.usable_for_channel(c.signals[0], None)


# --- Y en el score ----------------------------------------------------------


class Fixed(ProductSignalProvider):
    name = "de-mentira"

    def __init__(self, *signals: Signal) -> None:
        self._signals = list(signals)

    def supports(self):
        return frozenset({s.kind for s in self._signals})

    def discover(self, *, category, keywords, market, max_results, channels=None):
        return [CandidateSignals(name="Air fryer", category=category, signals=self._signals)]


def score_for(channel: str | None, *signals: Signal) -> dict:
    agent = ProductResearchAgent(trends_provider=Fixed(*signals))
    result = agent.run({"category": "home", "max_results": 1, "channel": channel})
    return result.data["candidates"][0]


def test_scoring_for_a_channel_uses_that_channels_competition():
    row = score_for(
        EBAY,
        signal(SignalKind.DEMAND, value=0.8),
        signal(SignalKind.COMPETITION, value=0.2, channel=EBAY),
    )

    assert row["opportunity_score"] is not None
    assert row["channel"] == EBAY
    assert row["scoring_wrong_channel"] == []


def test_scoring_for_one_channel_refuses_anothers_competition():
    row = score_for(
        OWN_WEB,
        signal(SignalKind.DEMAND, value=0.8),
        signal(SignalKind.COMPETITION, value=0.2, channel=EBAY),
    )

    assert row["opportunity_score"] is None
    assert row["scoring_wrong_channel"] == [EBAY]


def test_a_score_denied_by_channel_says_so_instead_of_looking_broken():
    """Los dos motivos se arreglan de formas distintas: uno leyendo un contrato y el
    otro consiguiendo una fuente del canal que falta."""
    row = score_for(
        OWN_WEB,
        signal(SignalKind.DEMAND, value=0.8),
        signal(SignalKind.COMPETITION, value=0.2, channel=EBAY),
    )

    assert row["scoring_withheld_from"] == []
    assert row["scoring_wrong_channel"] == [EBAY]


def test_an_agnostic_score_still_works_exactly_as_before():
    """Sin canal pedido, el comportamiento es el de siempre: es lo que impide que
    este milestone mueva las cifras del mock."""
    row = score_for(
        None,
        signal(SignalKind.DEMAND, value=0.8),
        signal(SignalKind.COMPETITION, value=0.2),
    )

    assert row["opportunity_score"] is not None
    assert row["channel"] is None


def test_a_signal_without_a_channel_is_reported_as_such_when_it_does_not_fit():
    row = score_for(
        OWN_WEB,
        signal(SignalKind.DEMAND, value=0.8),
        signal(SignalKind.COMPETITION, value=0.2),
    )

    assert row["opportunity_score"] is None
    assert row["scoring_wrong_channel"] == ["sin canal"]


def test_the_two_filters_are_independent_and_both_necessary():
    """Una licencia impecable no arregla un canal equivocado, y un canal correcto no
    arregla una licencia sin leer."""
    wrong_channel = signal(SignalKind.COMPETITION, channel=EBAY)
    unread_licence = signal(SignalKind.COMPETITION, channel=OWN_WEB, provider="sin-licencia-leida")
    c = candidate(wrong_channel, unread_licence)
    usable = scoring_filter(c, OWN_WEB)

    assert may_score(wrong_channel) and not usable(wrong_channel)
    assert c.usable_for_channel(unread_licence, OWN_WEB) and not usable(unread_licence)


# --- Y un canal inventado no existe ----------------------------------------


def test_a_signal_cannot_declare_an_undeclared_channel():
    with pytest.raises(UnknownChannelError):
        signal(SignalKind.COMPETITION, channel="marketplace:el-que-me-invente")
