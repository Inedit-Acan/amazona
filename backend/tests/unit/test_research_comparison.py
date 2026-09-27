"""La comparación entre proveedores (Milestone 35, ADR 0013).

La comparación obvia —poner los dos lado a lado y restar— no se puede hacer
hoy, y lo importante de este módulo es que **lo dice con números en vez de
devolver un informe vacío que parezca correcto**. Aquí se prueban las dos cosas:
lo que mide cuando no hay nada en común, y lo que mide cuando sí lo hay.
"""

import datetime

from app.integrations.ports import CandidateSignals, Signal, SignalKind
from app.research.comparison import compare, normalise, summarise


def signal(kind: SignalKind, value: float, *, simulated: bool, confidence: float = 0.5) -> Signal:
    return Signal(
        kind=kind,
        value=value,
        confidence=confidence,
        provider="fixtures" if simulated else "wikimedia-pageviews",
        source="somewhere",
        query="term",
        market="us",
        observed_at=datetime.datetime.now(datetime.UTC),
        method="…",
        simulated=simulated,
    )


def mock_candidate(name: str) -> CandidateSignals:
    return CandidateSignals(
        name=name,
        category="home",
        signals=[
            signal(SignalKind.DEMAND, 0.7, simulated=True, confidence=0.3),
            signal(SignalKind.COMPETITION, 0.2, simulated=True, confidence=0.3),
            signal(SignalKind.FUTURE_OUTLOOK, 0.6, simulated=True, confidence=0.3),
            signal(SignalKind.REGULATORY_RISK, 0.2, simulated=True, confidence=0.3),
            signal(SignalKind.SCALABILITY, 0.8, simulated=True, confidence=0.3),
        ],
    )


def real_candidate(name: str, demand: float = 0.6) -> CandidateSignals:
    return CandidateSignals(
        name=name,
        category="home",
        signals=[
            signal(SignalKind.DEMAND, demand, simulated=False, confidence=0.65),
            signal(SignalKind.FUTURE_OUTLOOK, 0.55, simulated=False, confidence=0.65),
        ],
    )


def run(baseline, candidate):
    return compare(
        category="home",
        market="us",
        baseline_provider="fixtures",
        baseline=baseline,
        candidate_provider="wikimedia-pageviews",
        candidate=candidate,
    )


# --- Lo que resume cada proveedor ------------------------------------------


def test_the_summary_counts_what_each_provider_knows():
    summary = summarise("fixtures", [mock_candidate("A"), mock_candidate("B")])

    assert summary.candidates == 2
    assert summary.coverage["demand"] == 2
    assert summary.coverage["competition"] == 2
    assert summary.scorable == 2
    assert summary.simulated_signals == 10
    assert summary.measured_signals == 0


def test_a_real_provider_shows_the_signals_it_cannot_measure_as_absent():
    """Ausencia, no cero: `competition` sencillamente no está en la cobertura."""
    summary = summarise("wikimedia-pageviews", [real_candidate("Air fryer")])

    assert summary.coverage["demand"] == 1
    assert "competition" not in summary.coverage
    assert summary.scorable == 0
    assert summary.measured_signals == 2


def test_a_provider_with_nothing_has_no_mean_confidence_instead_of_zero():
    summary = summarise("wikimedia-pageviews", [])

    assert summary.candidates == 0
    assert summary.mean_confidence is None


# --- El caso real de hoy: cero en común ------------------------------------


def test_with_no_shared_candidate_the_report_says_why_instead_of_looking_empty():
    report = run([mock_candidate("Silicone kitchen organizer")], [real_candidate("Air fryer")])

    assert report.shared == []
    assert report.deltas == []
    assert "Ningún candidato en común" in report.verdict
    assert "nombres inventados" in report.verdict
    assert "lo comparable es qué sabe medir cada uno" in report.verdict


def test_what_is_only_on_each_side_is_named():
    report = run([mock_candidate("Silicone kitchen organizer")], [real_candidate("Air fryer")])

    assert report.only_baseline == ["silicone kitchen organizer"]
    assert report.only_candidate == ["air fryer"]


def test_the_report_contrasts_coverage_even_when_nothing_is_shared():
    """Es la comparación que sí se puede hacer: qué sabe medir cada uno."""
    report = run([mock_candidate("A"), mock_candidate("B")], [real_candidate("Air fryer")])

    assert report.baseline.coverage["competition"] == 2
    assert "competition" not in report.candidate.coverage
    assert report.baseline.scorable == 2
    assert report.candidate.scorable == 0
    assert report.candidate.mean_confidence > report.baseline.mean_confidence


def test_a_real_provider_that_measured_nothing_is_not_a_verdict_about_demand():
    report = run([mock_candidate("A")], [])

    assert "no midió nada" in report.verdict
    assert "no dice que no haya demanda" in report.verdict


# --- Cuando sí hay algo compartido -----------------------------------------


def test_a_shared_candidate_produces_deltas_only_where_both_spoke():
    report = run([mock_candidate("Air fryer")], [real_candidate("Air fryer", demand=0.62)])

    assert report.shared == ["air fryer"]
    kinds = {delta["kind"] for delta in report.deltas}
    # Demanda y perspectiva: los dos hablan. Competencia: solo el mock, así que
    # no hay delta — restar contra una ausencia sería tratarla como un cero.
    assert kinds == {"demand", "future_outlook"}


def test_the_delta_is_the_real_value_minus_the_fixture():
    report = run([mock_candidate("Air fryer")], [real_candidate("Air fryer", demand=0.62)])

    demand = next(delta for delta in report.deltas if delta["kind"] == "demand")
    assert demand["baseline_value"] == 0.7
    assert demand["candidate_value"] == 0.62
    assert demand["difference"] == -0.08


def test_names_match_ignoring_case_and_spacing():
    report = run([mock_candidate("  AIR   FRYER ")], [real_candidate("air fryer")])

    assert report.shared == ["air fryer"]


def test_normalise_is_deliberately_naive():
    """Emparejar «Airfryer» con «Air fryer» es resolución de entidades, y hoy
    resolvería un conjunto vacío (ADR 0013)."""
    assert normalise("Air Fryer") == normalise("  air   fryer ")
    assert normalise("Airfryer") != normalise("Air fryer")


def test_the_verdict_counts_what_can_be_contrasted():
    report = run(
        [mock_candidate("Air fryer"), mock_candidate("Otro")],
        [real_candidate("Air fryer"), real_candidate("Humidifier")],
    )

    assert "1 candidato(s) en común de 2 y 2" in report.verdict
    assert "2 señal(es) contrastables" in report.verdict


def test_the_report_serialises_whole():
    """Se guarda como informe, y se lee entero."""
    report = run([mock_candidate("A")], [real_candidate("Air fryer")])

    as_dict = report.as_dict()
    assert as_dict["baseline"]["provider"] == "fixtures"
    assert as_dict["candidate"]["provider"] == "wikimedia-pageviews"
    assert as_dict["verdict"] == report.verdict
    assert as_dict["only_candidate"] == ["air fryer"]
