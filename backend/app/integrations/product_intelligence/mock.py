"""El proveedor de fixtures, reexpresado como señales (Milestone 34, ADR 0012).

Las cifras son **exactamente** las mismas que servía `MockTrendsProvider` desde
Fase 3 —el dataset no se toca—, pero ahora cada una sale con su procedencia y,
sobre todo, con `simulated=True`. Antes un 0,82 de demanda y un 0,82 medido eran
indistinguibles en la base de datos; ese era el problema que este milestone paga.
"""

import datetime

from app.ai.mock_trends_provider import MockTrendsProvider
from app.integrations.ports import (
    CandidateSignals,
    ProductSignalProvider,
    Signal,
    SignalBasis,
    SignalKind,
)

PROVIDER_NAME = "fixtures"
SOURCE = "app/ai/mock_trends_provider.py"

#: El nivel de competencia del fixture es una etiqueta; la señal es un número.
#: Esta es la única traducción entre los dos, y va en las dos direcciones
#: (`competition_level` de `app/agents/product_research.py`) para que el valor
#: guardado y la etiqueta enseñada nunca puedan contradecirse.
COMPETITION_VALUE: dict[str, float] = {"low": 0.2, "medium": 0.5, "high": 0.8}

#: Qué campo del fixture alimenta cada señal.
_FIELD_FOR_KIND: dict[SignalKind, str] = {
    SignalKind.DEMAND: "demand_signal",
    SignalKind.FUTURE_OUTLOOK: "future_outlook_signal",
    SignalKind.REGULATORY_RISK: "regulatory_risk_signal",
    SignalKind.SCALABILITY: "scalability_signal",
}

_METHOD = (
    "deterministic fixture value; not a measurement of anything — "
    "development and demo data only (ADR 0008)"
)


def competition_level(value: float) -> str:
    """De vuelta a la etiqueta. Los cortes son los del fixture, no nuevos."""
    if value <= 0.35:
        return "low"
    if value <= 0.65:
        return "medium"
    return "high"


class MockProductSignalProvider(ProductSignalProvider):
    """Fixtures con procedencia. Sabe de las cinco señales porque se las
    inventa todas — y lo dice en cada una."""

    name = PROVIDER_NAME

    def __init__(self, directory: MockTrendsProvider | None = None) -> None:
        self._directory = directory or MockTrendsProvider()

    def supports(self) -> frozenset[SignalKind]:
        return frozenset(SignalKind)

    def discover(
        self,
        *,
        category: str,
        keywords: list[str],
        market: str,
        max_results: int,
        channels: list[str] | None = None,
    ) -> list[CandidateSignals]:
        """Los fixtures no miden en ningún canal, así que `channels` se ignora y
        sus señales salen **sin canal** (Milestone 38).

        No es descuido: un fixture que se atribuyera un canal estaría afirmando
        haber medido allí. Y como una señal ligada a canal sin canal solo sirve
        para una decisión sin canal, el relleno no puede colarse en una decisión
        sobre Amazon — que es justo lo que había que impedir."""
        raw = self._directory.get_candidates(
            category=category, keywords=keywords, max_results=max_results
        )
        observed_at = datetime.datetime.now(datetime.UTC)
        return [self._candidate(entry, category, market, observed_at) for entry in raw]

    def _candidate(
        self, entry: dict, category: str, market: str, observed_at: datetime.datetime
    ) -> CandidateSignals:
        signals = [
            self._signal(kind, float(entry[field]), entry["name"], market, observed_at)
            for kind, field in _FIELD_FOR_KIND.items()
            if entry.get(field) is not None
        ]
        level = entry.get("competition_level")
        if level is not None:
            signals.append(
                self._signal(
                    SignalKind.COMPETITION,
                    COMPETITION_VALUE.get(level, 0.5),
                    entry["name"],
                    market,
                    observed_at,
                )
            )
        return CandidateSignals(
            name=entry["name"],
            category=category,
            signals=signals,
            rationale=entry.get("niche_rationale"),
        )

    def _signal(
        self,
        kind: SignalKind,
        value: float,
        query: str,
        market: str,
        observed_at: datetime.datetime,
    ) -> Signal:
        return Signal(
            kind=kind,
            value=value,
            # La confianza de un fixture no es alta por ser determinista: es
            # baja porque no mide nada. Determinista y verdadero no son lo mismo.
            confidence=0.3,
            provider=PROVIDER_NAME,
            source=SOURCE,
            query=query,
            market=market,
            observed_at=observed_at,
            method=_METHOD,
            raw_reference=f"{SOURCE}#{query}",
            basis=SignalBasis.SIMULATED,
        )
