"""The boundary between AMAZONA and the outside world.

Every external data source an agent depends on is declared here as a Protocol
and nowhere else. An agent depends on the Protocol, never on a concrete
implementation and never on a vendor SDK (plan maestro §23):

    Agent → Domain Service → Port → Adapter → External API

That is what makes it possible to have a mock, a sandbox and a real provider for
the same domain, and to refuse the mock in production (Milestone 30, ADR 0008).

Desde el Milestone 34 (ADR 0012) el contrato de Product Intelligence está hecho
de **señales con procedencia** y no de candidatos ya cocinados. La razón es que
una fuente real no responde «aquí tienes cuatro productos con su nivel de
competencia»: responde «este término tuvo este interés en este mercado en estas
fechas». Un contrato moldeado sobre el mock solo se puede implementar con datos
reales inventando la mitad, que es exactamente lo que el plan maestro §8
prohíbe: «nunca almacenar solo un número final sin procedencia».
"""

import datetime
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class IntegrationDomain(StrEnum):
    """The external data domains the system depends on. One provider is active
    per domain at any time."""

    PRODUCT_INTELLIGENCE = "product_intelligence"
    SUPPLIERS = "suppliers"
    REGULATORY = "regulatory"
    ADS = "ads"
    MARKETPLACES = "marketplaces"


class ProviderKind(StrEnum):
    """How much a provider's data is worth.

    MOCK is deterministic fixture data: fine for development, demos and tests,
    never acceptable as the basis for an operational decision. SANDBOX talks to
    a real provider's test environment — real shape, unreal data. REAL is the
    live source. COMPOSITE (Milestone 34) combines several: lo real primero y el
    mock solo para los huecos, marcado como relleno — útil en desarrollo y
    **inaceptable** donde no se admiten datos simulados, porque puede servirlos.
    """

    MOCK = "mock"
    SANDBOX = "sandbox"
    REAL = "real"
    COMPOSITE = "composite"


class SignalKind(StrEnum):
    """Qué mide una señal. Son los cinco ejes que el sistema ya usaba, ahora
    nombrados: antes vivían como claves sueltas de un diccionario del mock."""

    #: Cuánto interés hay. 0-1, más alto = más demanda.
    DEMAND = "demand"
    #: Cuánta competencia. 0-1, más alto = MÁS competencia (no se invierte aquí:
    #: el que la use decide si eso es bueno o malo).
    COMPETITION = "competition"
    #: Trayectoria de crecimiento. 0-1, más alto = mejor perspectiva.
    FUTURE_OUTLOOK = "future_outlook"
    #: Riesgo regulatorio. 0-1, más alto = MÁS riesgo.
    REGULATORY_RISK = "regulatory_risk"
    #: Facilidad de escalar fabricación y logística. 0-1, más alto = más fácil.
    SCALABILITY = "scalability"


@dataclass(frozen=True)
class Observation:
    """Una medida suelta de las que componen una señal (Milestone 35).

    La señal dice «0,7483 de demanda»; las observaciones dicen de qué está hecho
    ese 0,7483: 41.000 visitas en marzo, 38.000 en abril… Es la evidencia, y sin
    ella el número solo se puede creer o no creer.

    `period` es una etiqueta legible del tramo medido (`2026-08` para un mes).
    No se interpreta ni se convierte: se guarda como la fuente lo expresa.
    """

    period: str
    value: float


@dataclass(frozen=True)
class Signal:
    """Una medición, con todo lo que hace falta para saber de dónde salió.

    Los nueve campos son los que pide el plan maestro §8 —provider, source,
    query, timestamp, market, value, confidence, raw_reference, method— más
    `kind`, que dice qué se midió, y `simulated`, que dice en una sola lectura
    si esto es un dato o un relleno.

    `method` no es decoración: es donde se escribe qué significa realmente el
    número. Una cuenta de visitas a una enciclopedia es un **proxy de interés**,
    nunca demanda de compra ni ventas, y quien lea la señal tiene que poder
    saberlo sin preguntar.
    """

    kind: SignalKind
    #: Normalizado a 0-1 para que señales de fuentes distintas sean comparables.
    value: float
    #: Cuánto se fía el proveedor de este número concreto.
    confidence: float
    #: Quién lo produjo: `wikimedia-pageviews`, `fixtures`…
    provider: str
    #: De dónde salió: el host de la API, el fichero de fixtures.
    source: str
    #: Qué se preguntó exactamente.
    query: str
    market: str
    observed_at: datetime.datetime
    #: Cómo se calculó, y qué es y qué no es.
    method: str
    #: La respuesta cruda o cómo volver a ella: una URL, una clave de fixture.
    raw_reference: str | None = None
    #: True si es dato de relleno. Nunca se deduce del proveedor por su nombre.
    simulated: bool = False
    #: Las medidas que componen el valor, si la fuente las da. Vacío no significa
    #: cero: significa que esta señal no viene de una serie (Milestone 35).
    observations: list[Observation] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateSignals:
    """Un candidato y lo que se sabe de él, señal a señal."""

    name: str
    category: str
    signals: list[Signal] = field(default_factory=list)
    #: Por qué este candidato, en una frase. `None` cuando la fuente no da
    #: explicaciones — que es lo normal en una API de métricas.
    rationale: str | None = None

    def signal(self, kind: SignalKind) -> Signal | None:
        """La mejor señal de ese tipo: la real antes que el relleno y, a
        igualdad, la de más confianza."""
        matching = [s for s in self.signals if s.kind is kind]
        if not matching:
            return None
        return sorted(matching, key=lambda s: (s.simulated, -s.confidence))[0]


class ProductSignalProvider(Protocol):
    """Demand and opportunity signals for a category.

    `supports()` existe para poder componer sin adivinar: un proveedor real que
    solo sabe de demanda lo dice, y quien compone sabe qué hueco queda por
    rellenar en vez de descubrirlo por la ausencia de una clave."""

    #: Nombre estable del proveedor, el que se persiste en cada señal.
    name: str

    def supports(self) -> frozenset[SignalKind]: ...

    def discover(
        self, *, category: str, keywords: list[str], market: str, max_results: int
    ) -> list[CandidateSignals]: ...


class SupplierDirectory(Protocol):
    """Suppliers able to provide a category, with their commercial terms."""

    def get_suppliers(self, *, category: str, max_results: int = 5) -> list[dict]: ...


class RegulatoryDirectory(Protocol):
    """Regulatory requirements that apply to a category in a market."""

    def get_requirements(self, *, category: str, market: str) -> dict | None: ...


class AdPerformanceDirectory(Protocol):
    """Expected advertising performance for a category on a platform."""

    def get_performance_estimate(self, *, category: str, platform: str) -> dict | None: ...


class MarketplaceDirectory(Protocol):
    """Competition and demand on a marketplace for a category."""

    def get_marketplace_data(self, *, category: str, platform: str) -> dict | None: ...


#: The Protocol each domain expects. Used by the registry to document what a
#: future adapter has to implement.
PORT_FOR_DOMAIN: dict[IntegrationDomain, type] = {
    IntegrationDomain.PRODUCT_INTELLIGENCE: ProductSignalProvider,
    IntegrationDomain.SUPPLIERS: SupplierDirectory,
    IntegrationDomain.REGULATORY: RegulatoryDirectory,
    IntegrationDomain.ADS: AdPerformanceDirectory,
    IntegrationDomain.MARKETPLACES: MarketplaceDirectory,
}
