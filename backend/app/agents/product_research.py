from typing import cast

from pydantic import BaseModel, Field

from app.agents.base import Agent, AgentResult, AgentResultStatus
from app.integrations.ports import (
    CandidateSignals,
    IntegrationDomain,
    ProductSignalProvider,
    Signal,
    SignalBasis,
    SignalKind,
)
from app.integrations.product_intelligence.mock import competition_level
from app.integrations.registry import ProviderRegistry
from app.integrations.usage_rights import UsageRight, permits

_COMPETITION_FACTOR = {"low": 1.0, "medium": 0.6, "high": 0.3}

#: Qué señales entran en el `opportunity_score`. La fórmula **no cambia** en el
#: Milestone 34 (plan maestro §9: primero fuentes reales, después el score);
#: lo único nuevo es que ahora se sabe de dónde salió cada entrada.
_SCORING_SIGNALS = (SignalKind.DEMAND, SignalKind.COMPETITION)


class ProductResearchInput(BaseModel):
    category: str
    keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=20)
    market: str = "us"


def may_score(signal: Signal) -> bool:
    """Si la licencia del proveedor permite meter este número en un score
    (Milestone 37, ADR 0015).

    Tener el dato no es tener permiso para puntuar con él. Un `UNKNOWN` cuenta
    como «no»: el silencio de un contrato no autoriza nada.
    """
    return permits(signal.provider, UsageRight.SCORING)


def provenance_of(candidate: CandidateSignals, kinds: tuple[SignalKind, ...]) -> str:
    """De qué está hecho lo que se va a enseñar.

    `real` cuando todo lo que cuenta está **medido**, `estimated` cuando alguna
    pieza está modelada en vez de observada, `simulated` cuando nada viene del
    mundo, y `mixed` cuando se juntan datos del mundo con fixtures — que es el
    caso peligroso, el que sin esta etiqueta se leería como real (ADR 0008,
    ADR 0012, ADR 0015).

    `estimated` se separa de `mixed` a propósito: un conjunto de estimaciones
    honestas sí viene del mundo, y decir de él «mixto» lo confundiría con una
    mezcla de medición y fixture, que es otra cosa.
    """
    relevant = [
        signal for kind in kinds if (signal := candidate.signal(kind, only=may_score)) is not None
    ]
    if not relevant:
        return "unknown"
    bases = {signal.basis for signal in relevant}
    if bases == {SignalBasis.SIMULATED}:
        return "simulated"
    if SignalBasis.SIMULATED in bases:
        return "mixed"
    if SignalBasis.ESTIMATED in bases:
        return "estimated"
    return "real"


class ProductResearchAgent(Agent):
    """Fase 3, Agente 1: discovers and ranks *multiple* candidate products
    for a category/niche (unlike ProductAgent, which validates a single
    given product).

    Desde el Milestone 34 trabaja sobre señales con procedencia: el proveedor
    activo puede ser fixtures, una fuente real o una composición de ambas, y
    cada candidato dice de qué está hecho. La fórmula del score es la misma de
    siempre."""

    capability = "product_research"
    input_schema = ProductResearchInput

    def __init__(self, trends_provider: ProductSignalProvider | None = None) -> None:
        # Resolved from configuration, not hardcoded: which provider backs this
        # agent is a deployment decision (Milestone 30).
        self._trends: ProductSignalProvider = trends_provider or cast(
            ProductSignalProvider, ProviderRegistry().resolve(IntegrationDomain.PRODUCT_INTELLIGENCE)
        )

    def run(self, task_input: dict) -> AgentResult:
        params = ProductResearchInput.model_validate(task_input)
        candidates = self._trends.discover(
            category=params.category,
            keywords=params.keywords,
            market=params.market,
            max_results=params.max_results,
        )

        if not candidates:
            return AgentResult(
                status=AgentResultStatus.COMPLETED,
                recommendation="REVIEW",
                confidence=0.3,
                evidence=[],
                risks=[f"no trend data available for category {params.category!r}"],
                assumptions=[],
                data={"candidates": []},
            )

        ranked = sorted(
            (self._describe(candidate, params) for candidate in candidates),
            key=lambda c: (c["opportunity_score"] is not None, c["opportunity_score"] or 0.0),
            reverse=True,
        )

        scored = [c for c in ranked if c["opportunity_score"] is not None]
        top_score = scored[0]["opportunity_score"] if scored else 0.0
        recommendation = "GO" if top_score >= 0.5 else "REVIEW"
        confidence = self._confidence(ranked)

        risks = [f"{c['name']}: high competition" for c in ranked if c["competition_level"] == "high"]
        risks += [
            f"{c['name']}: no competition signal, so it cannot be scored"
            for c in ranked
            if c["opportunity_score"] is None
        ]
        assumptions = self._assumptions(ranked)

        return AgentResult(
            status=AgentResultStatus.COMPLETED,
            recommendation=recommendation,
            confidence=confidence,
            evidence=[
                f"{c['name']}: opportunity score {c['opportunity_score']}"
                for c in ranked
                if c["opportunity_score"] is not None
            ],
            risks=risks,
            assumptions=assumptions,
            data={"candidates": ranked},
        )

    # --- Un candidato ------------------------------------------------------

    def _describe(self, candidate: CandidateSignals, params: ProductResearchInput) -> dict:
        # Lo que se enseña: la mejor señal de cada tipo, sin más filtro. Verla en
        # el panel del propietario es uso interno, no redistribución (ADR 0015).
        demand = candidate.signal(SignalKind.DEMAND)
        competition = candidate.signal(SignalKind.COMPETITION)
        outlook = candidate.signal(SignalKind.FUTURE_OUTLOOK)
        regulatory = candidate.signal(SignalKind.REGULATORY_RISK)
        scalability = candidate.signal(SignalKind.SCALABILITY)

        # Lo que puntúa: solo lo que su licencia permite puntuar. Puede no ser la
        # misma señal que se enseña, y puede no haber ninguna.
        scoring_demand = candidate.signal(SignalKind.DEMAND, only=may_score)
        scoring_competition = candidate.signal(SignalKind.COMPETITION, only=may_score)

        level = competition_level(competition.value) if competition is not None else None
        scoring_level = (
            competition_level(scoring_competition.value)
            if scoring_competition is not None
            else None
        )
        score = None
        if scoring_demand is not None and scoring_level is not None:
            # La fórmula de Fase 3, intacta (plan maestro §9).
            score = round(scoring_demand.value * _COMPETITION_FACTOR.get(scoring_level, 0.3), 4)

        # Si había señal y la licencia la dejó fuera, se dice quién. Un score
        # ausente sin explicación es indistinguible de una avería.
        withheld = sorted(
            {
                signal.provider
                for kind in _SCORING_SIGNALS
                for signal in candidate.signals
                if signal.kind is kind and not may_score(signal)
            }
        )

        return {
            "name": candidate.name,
            "category": candidate.category or params.category,
            "opportunity_score": score,
            "demand_signal": demand.value if demand else None,
            "competition_level": level,
            # Ejes informativos: no alimentan el score ni la recomendación.
            "future_outlook_signal": outlook.value if outlook else None,
            "regulatory_risk_signal": regulatory.value if regulatory else None,
            "scalability_signal": scalability.value if scalability else None,
            "niche_rationale": candidate.rationale,
            #: De qué está hecho el score: real, estimado, mixto o simulado.
            "provenance": provenance_of(candidate, _SCORING_SIGNALS),
            #: Proveedores cuya señal existe pero cuya licencia no permite
            #: puntuar con ella (Milestone 37). Vacío es lo normal.
            "scoring_withheld_from": withheld,
            "market": params.market,
            #: La procedencia completa, señal a señal. Es lo que persiste el
            #: servicio en `product_signals` (plan maestro §8).
            "signals": [
                {
                    "kind": signal.kind.value,
                    "value": signal.value,
                    "confidence": signal.confidence,
                    "provider": signal.provider,
                    "source": signal.source,
                    "query": signal.query,
                    "market": signal.market,
                    "observed_at": signal.observed_at.isoformat(),
                    "method": signal.method,
                    "raw_reference": signal.raw_reference,
                    #: Observado, modelado o inventado (Milestone 37). Sustituye
                    #: al booleano `simulated`, que no distinguía las dos
                    #: primeras.
                    "basis": signal.basis.value,
                    # La evidencia mensual, cuando la fuente la da (M35).
                    "observations": [
                        {"period": observation.period, "value": observation.value}
                        for observation in signal.observations
                    ],
                }
                for signal in candidate.signals
            ],
        }

    def _confidence(self, ranked: list[dict]) -> float:
        """La confianza de siempre, rebajada cuando lo que se enseña es medio
        real y medio relleno: un número mixto no merece la misma fe que uno
        medido, y decirlo con el mismo 0,85 sería igualarlos."""
        base = 0.85 if len(ranked) >= 2 else 0.5
        provenances = {c["provenance"] for c in ranked}
        if provenances == {"real"}:
            return base
        if "mixed" in provenances or provenances == {"unknown"}:
            return min(base, 0.6)
        return base

    def _assumptions(self, ranked: list[dict]) -> list[str]:
        assumptions: list[str] = []
        if any(c["provenance"] in ("simulated", "mixed") for c in ranked):
            assumptions.append("some signals are fixture data, not measurements")
        if any(
            signal["provider"] == "wikimedia-pageviews"
            for c in ranked
            for signal in c["signals"]
        ):
            assumptions.append(
                "encyclopedia pageviews are a proxy for public interest, not purchase demand"
            )
        if not assumptions:
            assumptions.append("demand_signal approximates real market demand")
        return assumptions
