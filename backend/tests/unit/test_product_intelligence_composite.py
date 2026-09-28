"""La composición de proveedores (Milestone 34, ADR 0012).

La regla es de una línea y viene de la ADR 0008: **lo real se usa siempre que
exista y lo simulado solo como relleno, diciendo que lo es**. Lo que estas
pruebas protegen es el caso que se cuela solo: que el relleno no acabe
inventando hallazgos cuando la fuente real no encuentra nada.
"""

import datetime

import pytest

from app.integrations.ports import CandidateSignals, ProductSignalProvider, Signal, SignalBasis, SignalKind
from app.integrations.product_intelligence.composite import CompositeProductSignalProvider
from app.integrations.product_intelligence.mock import MockProductSignalProvider


def signal(kind: SignalKind, *, basis: SignalBasis, value: float = 0.5) -> Signal:
    fixture = basis is SignalBasis.SIMULATED
    return Signal(
        kind=kind,
        value=value,
        # Un fixture no puede declarar la confianza de una medición: lo impide el
        # techo por base (Milestone 37).
        confidence=0.3 if fixture else 0.7 if basis is SignalBasis.MEASURED else 0.6,
        provider="fixtures" if fixture else "wikimedia-pageviews",
        source="fixtures" if fixture else "wikimedia.org",
        query="term",
        market="us",
        observed_at=datetime.datetime.now(datetime.UTC),
        method="…",
        basis=basis,
    )


class Fake(ProductSignalProvider):
    def __init__(self, name: str, candidates: list[CandidateSignals], supports: set[SignalKind]):
        self.name = name
        self._candidates = candidates
        self._supports = supports

    def supports(self) -> frozenset[SignalKind]:
        return frozenset(self._supports)

    def discover(self, *, category, keywords, market, max_results):
        return list(self._candidates)


def real_candidate(name: str = "Air fryer") -> CandidateSignals:
    return CandidateSignals(
        name=name,
        category="home",
        signals=[signal(SignalKind.DEMAND, basis=SignalBasis.MEASURED, value=0.8)],
    )


def filler_candidate(name: str = "Air fryer") -> CandidateSignals:
    return CandidateSignals(
        name=name,
        category="home",
        signals=[
            signal(SignalKind.DEMAND, basis=SignalBasis.SIMULATED, value=0.2),
            signal(SignalKind.COMPETITION, basis=SignalBasis.SIMULATED, value=0.5),
        ],
    )


def test_it_needs_at_least_one_provider():
    with pytest.raises(ValueError):
        CompositeProductSignalProvider([])


def test_it_knows_everything_its_providers_know():
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [], {SignalKind.DEMAND}),
            Fake("filler", [], {SignalKind.COMPETITION, SignalKind.SCALABILITY}),
        ]
    )

    assert composite.supports() == frozenset(
        {SignalKind.DEMAND, SignalKind.COMPETITION, SignalKind.SCALABILITY}
    )


def test_the_filler_completes_the_signals_the_real_source_does_not_have():
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [real_candidate()], {SignalKind.DEMAND}),
            Fake("filler", [filler_candidate()], {SignalKind.DEMAND, SignalKind.COMPETITION}),
        ]
    )

    [candidate] = composite.discover(category="home", keywords=[], market="us", max_results=5)

    assert candidate.signal(SignalKind.COMPETITION) is not None
    assert candidate.signal(SignalKind.COMPETITION).simulated is True


def test_the_filler_never_overwrites_a_measured_signal():
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [real_candidate()], {SignalKind.DEMAND}),
            Fake("filler", [filler_candidate()], {SignalKind.DEMAND, SignalKind.COMPETITION}),
        ]
    )

    [candidate] = composite.discover(category="home", keywords=[], market="us", max_results=5)

    demand = candidate.signal(SignalKind.DEMAND)
    assert demand.simulated is False
    assert demand.value == 0.8


def test_the_filler_does_not_invent_candidates_the_real_source_never_found():
    """El caso peligroso: si la red falla y el relleno aporta sus candidatos,
    una avería se convierte en un descubrimiento."""
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [real_candidate("Air fryer")], {SignalKind.DEMAND}),
            Fake(
                "filler",
                [filler_candidate("Air fryer"), filler_candidate("Something nobody measured")],
                {SignalKind.DEMAND},
            ),
        ]
    )

    candidates = composite.discover(category="home", keywords=[], market="us", max_results=5)

    assert [c.name for c in candidates] == ["Air fryer"]


def test_with_no_real_source_at_all_the_filler_still_answers():
    """Es lo que se ve hoy con el mock a solas: todo simulado y marcado."""
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [], {SignalKind.DEMAND}),
            Fake("filler", [filler_candidate("A"), filler_candidate("B")], {SignalKind.DEMAND}),
        ]
    )

    candidates = composite.discover(category="home", keywords=[], market="us", max_results=5)

    assert [c.name for c in candidates] == ["A", "B"]
    assert all(s.simulated for c in candidates for s in c.signals)


def test_names_are_matched_without_caring_about_case_or_spacing():
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [real_candidate("Air fryer")], {SignalKind.DEMAND}),
            Fake("filler", [filler_candidate("  AIR FRYER ")], {SignalKind.COMPETITION}),
        ]
    )

    candidates = composite.discover(category="home", keywords=[], market="us", max_results=5)

    assert len(candidates) == 1
    assert candidates[0].signal(SignalKind.COMPETITION) is not None


def test_the_order_of_the_first_source_is_kept():
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [real_candidate("B"), real_candidate("A")], {SignalKind.DEMAND}),
            Fake("filler", [filler_candidate("A")], {SignalKind.COMPETITION}),
        ]
    )

    candidates = composite.discover(category="home", keywords=[], market="us", max_results=5)

    assert [c.name for c in candidates] == ["B", "A"]


def test_it_respects_the_limit_asked_for():
    composite = CompositeProductSignalProvider(
        [Fake("real", [real_candidate(f"c{i}") for i in range(5)], {SignalKind.DEMAND})]
    )

    assert len(composite.discover(category="home", keywords=[], market="us", max_results=2)) == 2


def test_real_plus_fixtures_produces_a_mixed_candidate_end_to_end():
    """El montaje que resuelve el registro con `composite`: demanda medida y
    competencia de relleno, cada una con su procedencia."""
    composite = CompositeProductSignalProvider(
        [Fake("real", [real_candidate("Air fryer")], {SignalKind.DEMAND}), MockProductSignalProvider()]
    )

    [candidate] = composite.discover(category="home", keywords=[], market="us", max_results=1)

    assert candidate.signal(SignalKind.DEMAND).simulated is False
    assert candidate.signal(SignalKind.COMPETITION) is None or candidate.signal(
        SignalKind.COMPETITION
    ).simulated is True


# --- Identidad entre proveedores (Milestone 36, ADR 0014) ------------------


@pytest.mark.parametrize(
    ("real_name", "filler_name"),
    [
        # Lo que la clave anterior (`casefold`) ya juntaba.
        ("Air fryer", "air fryer"),
        # Y lo que no: el paréntesis de desambiguación y la palabra compuesta.
        ("Belt (clothing)", "Belt"),
        ("Air fryer", "Airfryer"),
        ("Smartwatch", "smart watch"),
    ],
)
def test_the_filler_completes_a_candidate_whose_name_has_another_shape(real_name, filler_name):
    """Antes esto producía dos candidatos: uno real sin competencia y otro de
    relleno. Con dos fuentes reales, duplicar en vez de componer es el fallo que
    este milestone paga."""
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [real_candidate(real_name)], {SignalKind.DEMAND}),
            Fake("fixtures", [filler_candidate(filler_name)], set(SignalKind)),
        ]
    )

    candidates = composite.discover(category="home", keywords=[], market="us", max_results=5)

    assert len(candidates) == 1
    [candidate] = candidates
    # El nombre del primero manda: el real, no el del relleno.
    assert candidate.name == real_name
    assert candidate.signal(SignalKind.DEMAND).simulated is False
    assert candidate.signal(SignalKind.COMPETITION).simulated is True


def test_two_candidates_nobody_declared_equal_stay_two():
    composite = CompositeProductSignalProvider(
        [
            Fake("real", [real_candidate("Air fryer")], {SignalKind.DEMAND}),
            Fake("otra-real", [real_candidate("Air dryer")], {SignalKind.DEMAND}),
        ]
    )

    candidates = composite.discover(category="home", keywords=[], market="us", max_results=5)

    assert {c.name for c in candidates} == {"Air fryer", "Air dryer"}
