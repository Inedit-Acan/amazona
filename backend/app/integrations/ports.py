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
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.core.errors import ValidationError
from app.integrations.channels import channel_for
from app.sourcing.capabilities import CapabilityDeclaration
from app.sourcing.provenance import MissingVerifierError, SupplierFactProvenance
from app.sourcing.trade_terms import currency_for, incoterm_for


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


class SignalBasis(StrEnum):
    """De qué está hecho un número (Milestone 37, ADR 0015).

    Hasta aquí una señal era «simulada o no», un booleano. Eso junta dos cosas
    que no son la misma: un número que una fuente **observó** y un número que una
    fuente **modeló** con un método propio, a veces sin decir cuál. Las dos
    vienen del mundo, pero no valen lo mismo, y presentar una estimación como una
    medición es la misma clase de mentira que presentar un fixture como un dato.

    - `MEASURED`: la fuente lo observó y lo reporta. Visitas a un artículo,
      anuncios activos para una consulta.
    - `ESTIMADO`: la fuente lo derivó. Un ranking de ventas convertido a
      unidades, una cifra de ventas «estimada» por un proveedor. Puede ser útil y
      **no es una observación**.
    - `SIMULATED`: un fixture. No viene del mundo en absoluto.
    """

    MEASURED = "measured"
    ESTIMATED = "estimated"
    SIMULATED = "simulated"


#: Techo de confianza por base. **Una estimación no puede declararse tan fiable
#: como una medición**, y un fixture menos aún.
#:
#: Los números no son arbitrarios: 0,6 está por debajo del 0,75 que es el techo
#: del único adaptador que mide de verdad, así que un número modelado nunca
#: adelanta por confianza a uno observado. Y 0,4 queda por encima del 0,3 que
#: emiten los fixtures hoy, así que no cambia ninguna cifra existente — solo
#: pone un techo a las futuras.
MAX_CONFIDENCE_FOR_BASIS: dict[SignalBasis, float] = {
    SignalBasis.MEASURED: 1.0,
    SignalBasis.ESTIMATED: 0.6,
    SignalBasis.SIMULATED: 0.4,
}

#: En qué orden se prefiere una señal cuando hay varias del mismo tipo. Lo
#: medido antes que lo estimado, y lo estimado antes que lo inventado.
_BASIS_RANK: dict[SignalBasis, int] = {
    SignalBasis.MEASURED: 0,
    SignalBasis.ESTIMATED: 1,
    SignalBasis.SIMULATED: 2,
}


class SignalKind(StrEnum):
    """Qué mide una señal. Son los cinco ejes que el sistema ya usaba, ahora
    nombrados: antes vivían como claves sueltas de un diccionario del mock."""

    #: Cuánto interés hay. 0-1, más alto = más demanda.
    #:
    #: Es **interés**, y en su acepción más amplia: cuánta gente se ocupa de este
    #: tipo de producto. No es intención de compra ni volumen de búsqueda
    #: comercial: esos son `SEARCH_DEMAND` y `MARKETPLACE_DEMAND`, y se separaron
    #: en el Milestone 38 precisamente para que no acabaran aquí dentro.
    DEMAND = "demand"
    #: Cuánta gente **busca** esto, en una superficie de búsqueda. Mide intención:
    #: quien busca «comprar freidora de aire» está más cerca de pagar que quien
    #: consulta qué es una freidora de aire (plan maestro §8, «Search demand»).
    #:
    #: **Nadie la emite todavía**: no hay fuente gratuita fiable de volumen de
    #: búsqueda comercial. Existe para que el día que la haya no aterrice en
    #: `DEMAND` y contamine una medida de interés con una de intención.
    SEARCH_DEMAND = "search_demand"
    #: Cuánta demanda hay **dentro de un marketplace**: búsquedas, ventas o
    #: rotación en ese canal (plan maestro §8, «Marketplace demand»).
    #:
    #: Tampoco la emite nadie todavía, por el mismo motivo: no hay fuente.
    MARKETPLACE_DEMAND = "marketplace_demand"
    #: Cuánta competencia. 0-1, más alto = MÁS competencia (no se invierte aquí:
    #: el que la use decide si eso es bueno o malo).
    COMPETITION = "competition"
    #: Trayectoria de crecimiento. 0-1, más alto = mejor perspectiva.
    FUTURE_OUTLOOK = "future_outlook"
    #: Riesgo regulatorio. 0-1, más alto = MÁS riesgo.
    REGULATORY_RISK = "regulatory_risk"
    #: Facilidad de escalar fabricación y logística. 0-1, más alto = más fácil.
    SCALABILITY = "scalability"


#: Las señales que **no significan nada sin decir dónde se midieron** (Milestone
#: 38, ADR 0016).
#:
#: «Cuánta competencia hay» es una pregunta incompleta: dentro de un marketplace
#: es cuántos vendedores compiten por la misma búsqueda; para una web propia es
#: cuánto cuesta el clic y cuánto cuesta posicionar. Son magnitudes distintas, y
#: hasta el Milestone 38 compartían casilla sin etiqueta.
#:
#: Las demás —interés, trayectoria, riesgo regulatorio, escalabilidad— son
#: propiedades del producto y no del sitio donde se vende, así que pueden no tener
#: canal sin perder significado.
CHANNEL_BOUND_KINDS: frozenset[SignalKind] = frozenset(
    {SignalKind.COMPETITION, SignalKind.SEARCH_DEMAND, SignalKind.MARKETPLACE_DEMAND}
)


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
    `kind`, que dice qué se midió, y `basis`, que dice en una sola lectura si
    esto se observó, se modeló o se inventó (Milestone 37).

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
    #:
    #: **Es una referencia, no el cuerpo de la respuesta.** Guardar el payload
    #: entero metería identidades de vendedores —datos personales, con deberes de
    #: borrado— en una tabla de métricas (ADR 0015).
    raw_reference: str | None = None
    #: Observado, modelado o inventado. Nunca se deduce del nombre del proveedor.
    basis: SignalBasis = SignalBasis.MEASURED
    #: Dónde se midió (Milestone 38, ADR 0016). Una clave declarada en
    #: `channels.py`: `own_web`, `marketplace:amazon`, `search:google`…
    #:
    #: `None` significa **agnóstica del canal**, no «válida para todos»: el
    #: interés por un tipo de producto no depende de dónde se venda, y por eso
    #: puede no tenerlo. Quien decida sobre un canal concreto **no puede** usar una
    #: señal ligada a canal que no sea de ese canal.
    channel: str | None = None
    #: Las medidas que componen el valor, si la fuente las da. Vacío no significa
    #: cero: significa que esta señal no viene de una serie (Milestone 35).
    observations: list[Observation] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Falla si una señal se declara más fiable de lo que su base permite.

        Se comprueba aquí y no en cada adaptador porque es una regla del sistema,
        no una cortesía de cada proveedor: **una estimación no puede presentarse
        como una medición** (ADR 0015). Y falla en voz alta, en los tests de quien
        escriba el adaptador, en vez de recortarse en silencio en producción — un
        recorte callado es exactamente la clase de arreglo que esconde el problema.
        """
        ceiling = MAX_CONFIDENCE_FOR_BASIS[self.basis]
        if self.confidence > ceiling:
            raise ValueError(
                f"a {self.basis} signal cannot declare confidence {self.confidence}: "
                f"the ceiling for {self.basis} is {ceiling}"
            )
        # Un canal sin declarar no se acepta: un typo se convertiría en un canal
        # fantasma con sus propias señales, invisible para cualquier consulta que
        # buscara el canal de verdad (Milestone 38).
        if self.channel is not None:
            channel_for(self.channel)

    @property
    def simulated(self) -> bool:
        """Si esto es relleno. Se conserva porque media aplicación lo pregunta
        así, y ahora se deduce de la base en vez de vivir en paralelo a ella:
        dos fuentes de verdad para lo mismo era el problema que el Milestone 34
        vino a arreglar."""
        return self.basis is SignalBasis.SIMULATED


@dataclass(frozen=True)
class DeclaredAlias:
    """Otro nombre de este candidato, **declarado por una fuente** (Milestone 38).

    La ADR 0014 admite dos vías para la identidad: determinista o declarada. Hasta
    aquí lo declarado era un catálogo escrito a mano; esto es lo mismo firmado por
    otro: Wikimedia dice que «Freidora de aire» es el artículo español de «Air
    fryer», y eso no lo deduce este código de que dos cadenas se parezcan.

    `method` dice quién lo declaró (`langlinks:es.wikipedia`), porque una fusión sin
    motivo escrito es indistinguible de un error.
    """

    name: str
    method: str


@dataclass(frozen=True)
class CandidateSignals:
    """Un candidato y lo que se sabe de él, señal a señal."""

    name: str
    category: str
    signals: list[Signal] = field(default_factory=list)
    #: Por qué este candidato, en una frase. `None` cuando la fuente no da
    #: explicaciones — que es lo normal en una API de métricas.
    rationale: str | None = None
    #: Nombres que una fuente declara equivalentes a este candidato. Vacío es lo
    #: normal: la mayoría de las fuentes no dicen nada sobre cómo se llama esto en
    #: otro idioma (Milestone 38).
    declared_aliases: list[DeclaredAlias] = field(default_factory=list)

    def usable_for_channel(self, signal: Signal, channel: str | None) -> bool:
        """Si esta señal sirve para decidir sobre **ese** canal (Milestone 38).

        La regla, y es estrecha a propósito:

        - Una señal **no** ligada a canal —interés, trayectoria, riesgo,
          escalabilidad— sirve siempre: mide una propiedad del producto, no del
          sitio donde se vende.
        - Una señal **ligada** a canal sirve solo si declara exactamente ese canal.
          Una competencia medida en eBay no dice nada sobre una web propia.
        - Y una señal ligada a canal **sin** canal declarado solo sirve para una
          decisión igualmente sin canal. Es la diferencia entre «agnóstica» y
          «válida para todos», que es la lectura que hay que impedir: si valiera
          para todos, el relleno de un fixture decidiría sobre Amazon.
        """
        if signal.kind not in CHANNEL_BOUND_KINDS:
            return True
        return signal.channel == channel

    def signal(
        self, kind: SignalKind, *, only: Callable[[Signal], bool] | None = None
    ) -> Signal | None:
        """La mejor señal de ese tipo: **lo medido antes que lo estimado, y lo
        estimado antes que lo inventado**; a igualdad de base, la de más
        confianza (Milestone 37).

        Antes el criterio era un booleano, así que una estimación y una medición
        competían solo por confianza — y una estimación optimista podía ganarle a
        una medición prudente.

        `only` acota entre qué señales se elige. El contrato **no sabe** por qué
        alguien querría acotar: quien llama decide, y hoy quien llama lo usa para
        excluir las señales que su licencia no permite meter en un score (ADR
        0015). Mantenerlo genérico es lo que impide que este fichero acabe
        sabiendo de licencias."""
        matching = [s for s in self.signals if s.kind is kind and (only is None or only(s))]
        if not matching:
            return None
        return sorted(matching, key=lambda s: (_BASIS_RANK[s.basis], -s.confidence))[0]


class ProductSignalProvider(Protocol):
    """Demand and opportunity signals for a category.

    `supports()` existe para poder componer sin adivinar: un proveedor real que
    solo sabe de demanda lo dice, y quien compone sabe qué hueco queda por
    rellenar en vez de descubrirlo por la ausencia de una clave.

    `channels` (Milestone 38) dice **para qué canales** se investiga. Un adaptador
    que solo sabe de un canal calla cuando no se le pregunta por él, en vez de
    responder de otro sitio y dejar que quien lea lo confunda. `None` significa
    una investigación agnóstica del canal — el comportamiento de siempre."""

    #: Nombre estable del proveedor, el que se persiste en cada señal.
    name: str

    def supports(self) -> frozenset[SignalKind]: ...

    def discover(
        self,
        *,
        category: str,
        keywords: list[str],
        market: str,
        max_results: int,
        channels: list[str] | None = None,
    ) -> list[CandidateSignals]: ...


@dataclass(frozen=True)
class SupplierOffer:
    """Lo que una fuente de proveedores contesta sobre un candidato
    (Milestone 39, ADR 0017).

    Sustituye al `dict` que devolvía `get_suppliers`. El cambio es el mismo que
    el Milestone 34 hizo con Product Intelligence y por el mismo motivo: un
    contrato moldeado sobre el mock solo se puede implementar con datos reales
    inventando la mitad. Un directorio real no contesta «este proveedor es
    verified y su fiabilidad es 0,88»; contesta un nombre, un país, a veces un
    precio, casi nunca un Incoterm — y **calla** el resto.

    Por eso casi todo es opcional y nada tiene valor por defecto distinto de
    `None`. Un MOQ que el proveedor no ha publicado no es un MOQ de uno, y un
    coste logístico que nadie ha calculado no es cero.

    `provenance` es quién sostiene lo que viene aquí dentro. Es del conjunto,
    no de cada campo: una fuente habla con una sola voz. Lo que se afirma con
    voces distintas —el precio del proveedor y el transporte estimado por
    nosotros— se separa al persistirlo, no aquí.
    """

    #: Cómo se llama la empresa, tal y como lo dice la fuente.
    name: str
    #: Quién sostiene estos datos. Una fuente que no lo sepa decir no debería
    #: estar conectada: es la pregunta que el plan maestro §10 obliga a
    #: contestar antes de llamar «verified» a nada.
    provenance: SupplierFactProvenance
    #: De dónde salió: el host de la API, la clave del fixture, `manual:<quién>`.
    source: str

    region: str | None = None
    country: str | None = None
    city: str | None = None
    website: str | None = None

    unit_price: float | None = None
    #: ISO 4217. Sin moneda, el precio no se compara con ningún otro.
    currency: str | None = None
    quoted_unit: str | None = None
    quoted_quantity: int | None = None
    moq: int | None = None
    #: Días de preparación, sin el transporte.
    lead_time_days: int | None = None
    transit_days: int | None = None
    transport_mode: str | None = None
    #: Incoterms 2020.
    incoterm: str | None = None
    payment_terms: str | None = None
    destination_market: str | None = None
    valid_from: datetime.datetime | None = None
    valid_until: datetime.datetime | None = None

    #: Lo que la fuente dice de la fiabilidad del proveedor, 0-1. `None` es
    #: desconocido y **no es cero**.
    reliability: float | None = None
    #: Quién sostiene la identidad de la empresa, que es un hecho distinto de
    #: quién sostiene su tarifa. `None` = nadie lo ha dicho.
    verification: SupplierFactProvenance | None = None
    #: Obligatorio cuando `verification` es `THIRD_PARTY_VERIFIED`.
    verified_by: str | None = None

    #: Las capacidades del plan §16 que la fuente declare. Vacío es lo normal:
    #: ninguna fuente pública dice si hace envío ciego.
    capabilities: tuple[CapabilityDeclaration, ...] = ()

    observed_at: datetime.datetime | None = None

    def __post_init__(self) -> None:
        """Falla si la oferta dice algo que no se puede sostener.

        Se comprueba aquí, en los tests de quien escriba el adaptador, y no al
        pintar la pantalla: es el mismo criterio que el techo de confianza del
        Milestone 37. Un Incoterm inventado y un «verificado» sin emisor son
        errores que solo se ven si algo los mira.
        """
        if self.provenance is SupplierFactProvenance.UNKNOWN:
            raise ValidationError(
                "a supplier offer must say who says so: an unattributed offer is "
                "what Milestone 39 exists to remove"
            )
        if self.provenance is SupplierFactProvenance.THIRD_PARTY_VERIFIED and not (
            self.source or ""
        ).strip():
            raise MissingVerifierError(
                "a third-party verified offer must name the verifier (plan maestro §10)"
            )
        if self.verification is SupplierFactProvenance.THIRD_PARTY_VERIFIED and not (
            self.verified_by or ""
        ).strip():
            raise MissingVerifierError(
                f"{self.name}: identity cannot be third-party verified without naming "
                "the verifier (plan maestro §10)"
            )
        if self.currency is not None:
            currency_for(self.currency)
        if self.incoterm is not None:
            incoterm_for(self.incoterm)
        if self.unit_price is not None and self.currency is None:
            raise ValidationError(
                f"{self.name}: a price without a currency cannot be compared with any "
                "other price, and assuming they match invents an exchange rate of 1.00"
            )


class SupplierDirectory(Protocol):
    """Proveedores capaces de suministrar una categoría, con lo que se sepa de
    sus condiciones comerciales — y con la procedencia de cada respuesta."""

    #: Nombre estable de la fuente, el que se persiste en cada cotización.
    name: str

    def find_suppliers(
        self, *, category: str, destination_market: str, max_results: int = 5
    ) -> list[SupplierOffer]: ...


class RegulatoryDirectory(Protocol):
    """Regulatory requirements that apply to a category in a market."""

    def get_requirements(self, *, category: str, market: str) -> dict | None: ...


@dataclass(frozen=True)
class SourceAnchor:
    """Lo que una fuente normativa dice de **una norma que alguien nombró**
    (Milestone 41, ADR 0019).

    No dice a qué productos se aplica: ninguna fuente pública lo dice. Solo que
    la norma existe, si está en vigor y con qué fechas, **tal como la fuente las
    entrega** — sin elegir entre dos fechas de entrada en vigor y sin dar
    significado jurídico a un valor que la fuente no documenta.
    """

    provider: str
    celex: str
    #: `False` cuando la fuente respondió y no conoce ese número. No es un error:
    #: es una respuesta, y es distinta de «no pude preguntar».
    found: bool
    retrieved_at: datetime.datetime
    #: La consulta que produjo esto, para poder repetirla.
    source_url: str
    in_force: bool | None = None
    #: Código del tipo de acto en la fuente (`DIR`, `REG`…), sin traducir.
    act_type_code: str | None = None
    eli: str | None = None
    document_date: str | None = None
    entry_into_force: tuple[str, ...] = ()
    end_of_validity: str | None = None
    #: Todo lo que la fuente devolvió, sin interpretar. Es la evidencia.
    raw: dict[str, list[str]] = field(default_factory=dict)


class RegulatoryAnchorSource(Protocol):
    """Una fuente que ancla una norma **ya declarada**: existe, vigencia, fechas.

    Contrato distinto de `RegulatoryDirectory`: aquel responde «qué se exige a
    esta categoría», que es un juicio; este responde «qué dice la fuente de esta
    norma», que es un hecho. La diferencia es la ADR 0019.
    """

    name: str

    def lookup(self, celex: str) -> SourceAnchor: ...


@dataclass(frozen=True)
class ReferenceRateSet:
    """Las referencias que una fuente publicó **para un día** (Milestone 42, ADR 0020).

    `rates` es lo que la fuente dijo, sin filtrar por lo que nosotros admitimos:
    decidir qué monedas caben en el catálogo es cosa del servicio, y el adaptador no
    debe esconder lo que la fuente publica. La convención es la del BCE —`1 base =
    rate divisa`—, y `base` va explícita para que nadie tenga que adivinarla.
    """

    provider: str
    #: La fecha efectiva **de la fuente**, tal cual. No se corrige ni se traslada.
    published_on: datetime.date
    base: str
    rates: dict[str, Decimal]
    retrieved_at: datetime.datetime
    source_url: str


class ExchangeRateFeed(Protocol):
    """Una fuente que publica tipos de cambio de referencia.

    Es el lado **escritura** del contrato FX: trae observaciones para guardarlas.
    El lado lectura sigue siendo `ExchangeRateProvider` (`app/money/rates.py`), que
    solo lee la base de datos. Un análisis económico nunca llama a esto.
    """

    name: str

    def fetch_daily(self) -> ReferenceRateSet: ...

    def fetch_history(self) -> list[ReferenceRateSet]: ...


@dataclass(frozen=True)
class PublicationCheck:
    """Lo que se pudo comprobar de la **publicación oficial** de una norma nacional
    (Milestone 43, ADR 0021). Es una comprobación **auxiliar**.

    Cuatro estados, y ninguno de «falló» se lee como «no existe»:

    - `confirmed`: el sumario del diario oficial de ese día lista el identificador.
    - `absent_from_summary`: el sumario se leyó bien y **no** lo lista. Es la
      única respuesta negativa, y solo existe si la lectura fue correcta.
    - `check_failed`: no se pudo preguntar o no se pudo leer (red, formato,
      presupuesto). **No es una conclusión.**
    - `not_checked`: no había con qué preguntar (sin fecha de publicación) o no
      aplica (antes de 2009 solo es oficial la edición en papel).
    """

    state: str
    detail: str | None = None
    #: Enlace oficial estable a la disposición, cuando se puede construir.
    url: str | None = None


@dataclass(frozen=True)
class NationalNormRecord:
    """Lo que una fuente de Derecho nacional dijo de **una norma que alguien
    nombró** (Milestone 43, ADR 0021).

    No dice a qué producto se aplica ni qué directiva traspone «por sí misma»: da
    los metadatos de la norma y las relaciones que su análisis documenta, **tal
    como la fuente los entrega**. Ni la consolidación ni el análisis son texto
    oficial: son informativos.
    """

    provider: str
    national_id: str
    retrieved_at: datetime.datetime
    #: `False` cuando la fuente respondió que no tiene esa norma **consolidada**.
    #: No dice que la norma no exista: puede no estar en la colección.
    consolidated: bool
    #: Los metadatos, verbatim (fechas como cadena `AAAAMMDD`, banderas `S`/`N`).
    metadata: dict[str, object] = field(default_factory=dict)
    #: Las relaciones del análisis, normalizadas en forma pero **no en contenido**:
    #: `{"previous": [...], "next": [...]}` con `id_norma`, código, texto de la
    #: relación y texto de detalle.
    relations: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    publication: PublicationCheck = field(default_factory=lambda: PublicationCheck("not_checked"))
    source_urls: tuple[str, ...] = ()


class NationalNormSource(Protocol):
    """Una fuente que ancla una norma nacional **ya declarada**.

    Puerto hermano de `RegulatoryAnchorSource`, no una generalización suya: aquel
    devuelve existencia y vigencia de un acto de la UE; este devuelve metadatos,
    banderas de estado y relaciones de una norma nacional cuyo texto consolidado
    es meramente informativo. Forzar los dos en un solo contrato dejaría campos
    vacíos en cada uno y mezclaría lo oficial con lo informativo.
    """

    name: str

    def lookup(self, national_id: str) -> NationalNormRecord: ...


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
