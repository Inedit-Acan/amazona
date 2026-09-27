"""Qué dice cada proveedor, y en qué se parecen (Milestone 35, ADR 0013).

El plan maestro §32 pide «comparar resultados contra mock». La forma obvia sería
poner los dos lado a lado y restar: cuánto se equivoca el mock en la demanda de
tal producto. **Esa comparación no se puede hacer hoy y el informe lo dice con
números**: los nueve candidatos del mock son nombres inventados que no existen
como artículo de enciclopedia, así que la intersección entre lo que mide una
fuente real y lo que se inventa el mock es vacía.

Lo que sí se puede contrastar, y es lo que este módulo produce: **qué sabe cada
uno, sobre qué, y con cuánta confianza**. Cuántos candidatos, cuántos
compartidos, qué señales cubre cada proveedor, cómo se reparte la confianza y
cuántos candidatos quedan con score. Eso convierte los límites conocidos en
medidas, que es lo que hace falta para decidir la siguiente fuente.

Función pura, como `evaluate_action` o `assess_pipeline_run`: entra lo que
devolvieron dos proveedores, sale el informe. Nada de base de datos.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from app.integrations.ports import CandidateSignals, SignalKind

#: Las señales que el `opportunity_score` necesita. Se miran aparte porque su
#: ausencia no es una carencia cualquiera: sin ellas no hay score (ADR 0012 §8).
SCORING_SIGNALS = (SignalKind.DEMAND, SignalKind.COMPETITION)


def normalise(name: str) -> str:
    """La clave con la que se busca solapamiento: el nombre sin mayúsculas ni
    espacios de sobra.

    Es deliberadamente ingenua. Emparejar «Air fryer» con «Airfryer» o con un
    ASIN es **resolución de entidades**, y hacerla ahora sería resolver un
    conjunto vacío: este informe existe, entre otras cosas, para demostrar con
    números que hará falta cuando entre la segunda fuente real (ADR 0013).
    """
    return " ".join(name.split()).casefold()


@dataclass
class ProviderSummary:
    """Qué produjo un proveedor."""

    provider: str
    candidates: int
    #: Cuántos candidatos traen cada tipo de señal.
    coverage: dict[str, int] = field(default_factory=dict)
    #: Cuántos candidatos podrían puntuarse: los que traen demanda y competencia.
    scorable: int = 0
    #: Confianza media de sus señales, o None si no produjo ninguna. No se
    #: sustituye por cero: un proveedor sin señales no es un proveedor con
    #: confianza cero.
    mean_confidence: float | None = None
    #: Cuántas de sus señales son medidas y cuántas relleno.
    measured_signals: int = 0
    simulated_signals: int = 0


@dataclass
class ComparisonReport:
    category: str
    market: str
    baseline: ProviderSummary
    candidate: ProviderSummary
    #: Candidatos que aparecen en los dos, por nombre normalizado.
    shared: list[str] = field(default_factory=list)
    only_baseline: list[str] = field(default_factory=list)
    only_candidate: list[str] = field(default_factory=list)
    #: Para lo compartido, la diferencia de valor por tipo de señal. Vacío
    #: cuando no hay nada compartido, que hoy es siempre.
    deltas: list[dict] = field(default_factory=list)
    verdict: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def summarise(provider: str, candidates: Sequence[CandidateSignals]) -> ProviderSummary:
    coverage: dict[str, int] = {}
    confidences: list[float] = []
    measured = 0
    simulated = 0
    scorable = 0

    for candidate in candidates:
        kinds = set()
        for signal in candidate.signals:
            kinds.add(signal.kind)
            confidences.append(signal.confidence)
            if signal.simulated:
                simulated += 1
            else:
                measured += 1
        for kind in kinds:
            coverage[kind.value] = coverage.get(kind.value, 0) + 1
        if all(candidate.signal(kind) is not None for kind in SCORING_SIGNALS):
            scorable += 1

    return ProviderSummary(
        provider=provider,
        candidates=len(candidates),
        coverage=coverage,
        scorable=scorable,
        mean_confidence=round(sum(confidences) / len(confidences), 4) if confidences else None,
        measured_signals=measured,
        simulated_signals=simulated,
    )


def compare(
    *,
    category: str,
    market: str,
    baseline_provider: str,
    baseline: Sequence[CandidateSignals],
    candidate_provider: str,
    candidate: Sequence[CandidateSignals],
) -> ComparisonReport:
    """El informe. `baseline` es contra qué se compara —el mock— y `candidate`
    lo que se está contrastando —la fuente real—."""
    by_baseline = {normalise(c.name): c for c in baseline}
    by_candidate = {normalise(c.name): c for c in candidate}
    shared = sorted(set(by_baseline) & set(by_candidate))

    deltas = [
        delta
        for key in shared
        for delta in _deltas_for(by_baseline[key], by_candidate[key])
    ]

    report = ComparisonReport(
        category=category,
        market=market,
        baseline=summarise(baseline_provider, baseline),
        candidate=summarise(candidate_provider, candidate),
        shared=shared,
        only_baseline=sorted(set(by_baseline) - set(by_candidate)),
        only_candidate=sorted(set(by_candidate) - set(by_baseline)),
        deltas=deltas,
    )
    report.verdict = verdict_for(report)
    return report


def _deltas_for(baseline: CandidateSignals, candidate: CandidateSignals) -> list[dict]:
    """Diferencia por tipo de señal, solo donde los dos tienen algo que decir.
    Donde uno calla no hay delta: restar contra una ausencia sería tratarla
    como un cero."""
    deltas: list[dict] = []
    for kind in SignalKind:
        left = baseline.signal(kind)
        right = candidate.signal(kind)
        if left is None or right is None:
            continue
        deltas.append(
            {
                "candidate": candidate.name,
                "kind": kind.value,
                "baseline_value": left.value,
                "candidate_value": right.value,
                "difference": round(right.value - left.value, 4),
            }
        )
    return deltas


def verdict_for(report: ComparisonReport) -> str:
    """El informe en una línea, escrito para que un cero no se lea como un
    fallo del sistema sino como lo que es: que los dos proveedores no están
    hablando de lo mismo."""
    if report.candidate.candidates == 0:
        return (
            f"{report.candidate.provider} no midió nada para {report.category}: "
            "no hay con qué contrastar, y eso no dice que no haya demanda."
        )
    if not report.shared:
        return (
            f"Ningún candidato en común: {report.baseline.provider} propone "
            f"{report.baseline.candidates} nombres inventados y {report.candidate.provider} mide "
            f"{report.candidate.candidates} términos reales. No se pueden restar sus cifras; lo "
            "comparable es qué sabe medir cada uno."
        )
    return (
        f"{len(report.shared)} candidato(s) en común de "
        f"{report.baseline.candidates} y {report.candidate.candidates}: "
        f"{len(report.deltas)} señal(es) contrastables."
    )
