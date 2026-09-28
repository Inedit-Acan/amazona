"""El riesgo de un proveedor, por dimensiones (Milestone 39, plan maestro §11).

El plan pide ocho riesgos y añade una instrucción que es media especificación:
«No convertirlo inicialmente en un único score opaco. Mantener dimensiones
explicables».

Este módulo la cumple literalmente. No hay `overall_risk`, no hay media
ponderada y no hay función que devuelva un número entre 0 y 1. Hay ocho
respuestas, cada una con su nivel, su motivo escrito y los hechos concretos en
los que se apoya. Quien quiera decidir, decide mirando las ocho.

Y hay una novena posibilidad en cada una: `UNKNOWN`. Un riesgo que no se ha
podido evaluar **no es un riesgo bajo**. Esa confusión es la versión de este
dominio del cero inventado que el Milestone 34 prohibió, y aquí es más cara: un
riesgo de fraude «bajo» porque nadie miró es una compra hecha a ciegas que
parece hecha con los ojos abiertos.

## De dónde sale cada nivel

De los hechos ya guardados, y de nada más. No hay fuente externa de riesgo de
proveedor —eso cuesta dinero y el Milestone 39 tiene presupuesto cero—, así que
todas las evaluaciones que este módulo produce son `AMAZONA_ESTIMATE`: las
calculamos nosotros con un método que está escrito aquí y se puede discutir.
Ninguna se presenta como comprobada por un tercero.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.sourcing.capabilities import CapabilityAnswer, SupplyCapability
from app.sourcing.provenance import SupplierFactProvenance


class RiskDimension(StrEnum):
    """Las ocho del plan maestro §11. Conjunto cerrado."""

    IDENTITY = "identity"
    FINANCIAL = "financial"
    QUALITY = "quality"
    DELIVERY = "delivery"
    LEGAL = "legal"
    FRAUD = "fraud"
    DEPENDENCY = "dependency"
    GEOPOLITICAL_LOGISTICS = "geopolitical_logistics"


class RiskLevel(StrEnum):
    """Cuánto riesgo, o que no se sabe.

    Tres niveles y no cinco a propósito: con los datos que hoy existen, afirmar
    cinco grados sería fingir una precisión que no hay. `UNKNOWN` **no es el
    más bajo ni el más alto**: está fuera de la escala, porque no es una medida.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RiskAssessment:
    """Una dimensión evaluada: el nivel, por qué, y sobre qué."""

    dimension: RiskDimension
    level: RiskLevel
    #: En una frase, por qué ese nivel. Se enseña al usuario tal cual: si el
    #: motivo no se puede escribir, la evaluación no se puede defender.
    rationale: str
    #: Quién sostiene la evaluación. Hoy siempre `AMAZONA_ESTIMATE` cuando hay
    #: nivel, y `UNKNOWN` cuando no lo hay.
    provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN
    #: Qué hechos concretos se miraron. Vacío cuando no se pudo mirar ninguno,
    #: que es exactamente lo que convierte la evaluación en `UNKNOWN`.
    basis: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.level is not RiskLevel.UNKNOWN


@dataclass(frozen=True)
class SupplierRiskFacts:
    """Lo que se sabe de un proveedor y su oferta, listo para evaluar.

    Es un dataclass plano y no un modelo de base de datos a propósito: la
    evaluación es una función pura sobre hechos, comprobable sin una sesión
    abierta, y así el mismo código sirve para una fila guardada y para una ficha
    que alguien está tecleando y todavía no ha guardado.
    """

    country: str | None = None
    region: str | None = None
    website: str | None = None
    #: Quién sostiene que este proveedor es quien dice ser.
    verification: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN
    #: Qué dice el proveedor —o un tercero— de su propia fiabilidad, si es que
    #: alguien lo dice. `None` es desconocido, **no cero**.
    reliability: float | None = None
    reliability_provenance: SupplierFactProvenance = SupplierFactProvenance.UNKNOWN

    incoterm: str | None = None
    payment_terms: str | None = None
    lead_time_days: int | None = None
    transit_days: int | None = None
    destination_market: str | None = None

    capabilities: tuple[CapabilityAnswer, ...] = ()
    #: Cuántos proveedores distintos tiene este producto, contando este. `None`
    #: cuando la pregunta no se ha hecho: no es lo mismo que «uno».
    alternatives_for_product: int | None = None

    def capability(self, capability: SupplyCapability) -> CapabilityAnswer | None:
        for answer in self.capabilities:
            if answer.capability is capability:
                return answer
        return None

    def supports(self, capability: SupplyCapability) -> bool | None:
        answer = self.capability(capability)
        return answer.supported if answer else None


def _unknown(dimension: RiskDimension, rationale: str) -> RiskAssessment:
    return RiskAssessment(dimension=dimension, level=RiskLevel.UNKNOWN, rationale=rationale)


def _assess(
    dimension: RiskDimension, level: RiskLevel, rationale: str, basis: tuple[str, ...]
) -> RiskAssessment:
    return RiskAssessment(
        dimension=dimension,
        level=level,
        rationale=rationale,
        provenance=SupplierFactProvenance.AMAZONA_ESTIMATE,
        basis=basis,
    )


def _identity(facts: SupplierRiskFacts) -> RiskAssessment:
    known = [name for name, value in (("país", facts.country), ("web", facts.website)) if value]
    if facts.verification is SupplierFactProvenance.THIRD_PARTY_VERIFIED:
        return _assess(
            RiskDimension.IDENTITY,
            RiskLevel.LOW,
            "la identidad está verificada por un tercero independiente",
            ("verificación de tercero", *known),
        )
    if not known:
        return _unknown(
            RiskDimension.IDENTITY,
            "no consta ni el país ni la web del proveedor: no hay nada que comprobar",
        )
    if facts.verification is SupplierFactProvenance.SUPPLIER_CLAIM:
        return _assess(
            RiskDimension.IDENTITY,
            RiskLevel.MEDIUM,
            "la identidad la sostiene el propio proveedor y nadie más",
            tuple(known),
        )
    return _assess(
        RiskDimension.IDENTITY,
        RiskLevel.HIGH,
        "hay datos de contacto pero nadie ha declarado de dónde salen",
        tuple(known),
    )


def _financial(facts: SupplierRiskFacts) -> RiskAssessment:
    if not (facts.payment_terms or "").strip():
        return _unknown(
            RiskDimension.FINANCIAL,
            "no constan las condiciones de pago: no se sabe cuánto dinero se adelanta",
        )
    # Deliberadamente literal: se mira si el texto menciona un anticipo, y no se
    # intenta entenderlo más allá. Un analizador de condiciones de pago sería un
    # modelo con opiniones, y aquí hace falta un hecho.
    terms = (facts.payment_terms or "").lower()
    prepaid = any(word in terms for word in ("anticipo", "prepago", "advance", "upfront", "t/t 100"))
    if not prepaid:
        return _assess(
            RiskDimension.FINANCIAL,
            RiskLevel.LOW,
            "las condiciones de pago constan y no mencionan anticipo",
            ("condiciones de pago declaradas",),
        )
    verified = facts.verification is SupplierFactProvenance.THIRD_PARTY_VERIFIED
    return _assess(
        RiskDimension.FINANCIAL,
        RiskLevel.MEDIUM if verified else RiskLevel.HIGH,
        "hay que adelantar dinero a un proveedor cuya identidad "
        + ("está verificada" if verified else "no ha verificado nadie"),
        ("condiciones de pago declaradas", f"verificación: {facts.verification}"),
    )


def _quality(facts: SupplierRiskFacts) -> RiskAssessment:
    if facts.reliability_provenance is SupplierFactProvenance.THIRD_PARTY_VERIFIED:
        return _assess(
            RiskDimension.QUALITY,
            RiskLevel.LOW if (facts.reliability or 0) >= 0.8 else RiskLevel.MEDIUM,
            "hay una valoración de fiabilidad emitida por un tercero",
            (f"fiabilidad {facts.reliability} ({facts.reliability_provenance})",),
        )
    if facts.reliability is None:
        return _unknown(
            RiskDimension.QUALITY,
            "nadie ha valorado la fiabilidad de este proveedor",
        )
    return _assess(
        RiskDimension.QUALITY,
        RiskLevel.MEDIUM,
        "la única valoración de fiabilidad no viene de un tercero independiente",
        (f"fiabilidad {facts.reliability} ({facts.reliability_provenance})",),
    )


def _delivery(facts: SupplierRiskFacts) -> RiskAssessment:
    sla = facts.supports(SupplyCapability.SLA)
    tracking = facts.supports(SupplyCapability.TRACKING)
    times = [d for d in (facts.lead_time_days, facts.transit_days) if d is not None]
    if not times and sla is None and tracking is None:
        return _unknown(
            RiskDimension.DELIVERY,
            "no consta plazo, ni SLA, ni seguimiento: la entrega no se puede evaluar",
        )
    basis = tuple(
        item
        for item in (
            f"preparación {facts.lead_time_days} d" if facts.lead_time_days is not None else None,
            f"tránsito {facts.transit_days} d" if facts.transit_days is not None else None,
            f"SLA: {sla}" if sla is not None else None,
            f"seguimiento: {tracking}" if tracking is not None else None,
        )
        if item
    )
    total = sum(times) if times else None
    if sla and tracking and total is not None and total <= 14:
        return _assess(
            RiskDimension.DELIVERY, RiskLevel.LOW, "hay SLA, seguimiento y un plazo corto", basis
        )
    if total is not None and total > 30:
        return _assess(
            RiskDimension.DELIVERY,
            RiskLevel.HIGH,
            f"el plazo declarado suma {total} días",
            basis,
        )
    if sla is False or tracking is False:
        return _assess(
            RiskDimension.DELIVERY,
            RiskLevel.HIGH,
            "el proveedor declara que no ofrece SLA o seguimiento",
            basis,
        )
    return _assess(
        RiskDimension.DELIVERY, RiskLevel.MEDIUM, "hay plazo pero falta SLA o seguimiento", basis
    )


def _legal(facts: SupplierRiskFacts) -> RiskAssessment:
    returns = facts.supports(SupplyCapability.RETURNS)
    eu_address = facts.supports(SupplyCapability.EU_RETURN_ADDRESS)
    if returns is None and eu_address is None:
        return _unknown(
            RiskDimension.LEGAL,
            "no consta si acepta devoluciones ni si tiene dirección de retorno en la UE",
        )
    basis = tuple(
        item
        for item in (
            f"devoluciones: {returns}" if returns is not None else None,
            f"retorno UE: {eu_address}" if eu_address is not None else None,
        )
        if item
    )
    if returns and eu_address:
        return _assess(
            RiskDimension.LEGAL,
            RiskLevel.LOW,
            "acepta devoluciones con dirección de retorno en la UE",
            basis,
        )
    if returns is False or eu_address is False:
        return _assess(
            RiskDimension.LEGAL,
            RiskLevel.HIGH,
            "falta una pieza del derecho de desistimiento: devoluciones o retorno en la UE",
            basis,
        )
    return _assess(
        RiskDimension.LEGAL,
        RiskLevel.MEDIUM,
        "solo consta una mitad: devoluciones o retorno en la UE, no las dos",
        basis,
    )


def _fraud(facts: SupplierRiskFacts) -> RiskAssessment:
    if facts.verification is SupplierFactProvenance.UNKNOWN:
        return _unknown(
            RiskDimension.FRAUD,
            "nadie ha dicho de dónde salen los datos de este proveedor",
        )
    if facts.verification is SupplierFactProvenance.SIMULATED:
        return _assess(
            RiskDimension.FRAUD,
            RiskLevel.HIGH,
            "este proveedor viene de datos de demostración: no existe",
            ("procedencia simulada",),
        )
    if facts.verification is SupplierFactProvenance.THIRD_PARTY_VERIFIED:
        return _assess(
            RiskDimension.FRAUD,
            RiskLevel.LOW,
            "un tercero independiente ha comprobado que el proveedor es quien dice ser",
            ("verificación de tercero",),
        )
    return _assess(
        RiskDimension.FRAUD,
        RiskLevel.MEDIUM,
        "todo lo que se sabe del proveedor lo dice el propio proveedor",
        (f"verificación: {facts.verification}",),
    )


def _dependency(facts: SupplierRiskFacts) -> RiskAssessment:
    if facts.alternatives_for_product is None:
        return _unknown(
            RiskDimension.DEPENDENCY,
            "no se ha contado cuántos proveedores alternativos hay para este producto",
        )
    count = facts.alternatives_for_product
    basis = (f"{count} proveedor(es) para el producto",)
    if count <= 1:
        return _assess(
            RiskDimension.DEPENDENCY, RiskLevel.HIGH, "no hay alternativa a este proveedor", basis
        )
    if count == 2:
        return _assess(
            RiskDimension.DEPENDENCY, RiskLevel.MEDIUM, "solo hay una alternativa", basis
        )
    return _assess(
        RiskDimension.DEPENDENCY, RiskLevel.LOW, "hay varias alternativas para el producto", basis
    )


#: Orígenes cuyo envío a un destino cruza una frontera aduanera relevante para
#: nosotros. No es geopolítica de verdad —eso necesita una fuente— sino la única
#: distinción que los datos guardados permiten hacer hoy: dentro del mercado de
#: destino o fuera de él.
def _geopolitical(facts: SupplierRiskFacts) -> RiskAssessment:
    destination = (facts.destination_market or "").strip().lower()
    region = (facts.region or "").strip().lower()
    country = (facts.country or "").strip().lower()
    if not destination or not (region or country):
        return _unknown(
            RiskDimension.GEOPOLITICAL_LOGISTICS,
            "falta el origen o el mercado de destino: no se sabe qué fronteras cruza",
        )
    # Un país y un mercado no son comparables sin un catálogo de qué países
    # forman cada mercado, y ese catálogo no existe todavía. Decir «cruza una
    # frontera» porque `es` no es la misma cadena que `eu` sería inventarse una
    # aduana entre Valencia y la Unión Europea.
    origin = region if region else country
    if not region and country != destination:
        return _unknown(
            RiskDimension.GEOPOLITICAL_LOGISTICS,
            f"el proveedor consta en {country} y el destino es el mercado {destination}: "
            "sin un catálogo de qué países forman cada mercado no se puede decir si cruza "
            "una frontera",
        )
    basis = (f"origen {origin}", f"destino {destination}")
    if origin == destination:
        return _assess(
            RiskDimension.GEOPOLITICAL_LOGISTICS,
            RiskLevel.LOW,
            "origen y destino son el mismo mercado: no hay importación de por medio",
            basis,
        )
    incoterm = (facts.incoterm or "").strip().upper()
    if incoterm == "DDP":
        return _assess(
            RiskDimension.GEOPOLITICAL_LOGISTICS,
            RiskLevel.MEDIUM,
            "el envío es internacional pero el proveedor asume derechos e importación (DDP)",
            (*basis, "Incoterm DDP"),
        )
    return _assess(
        RiskDimension.GEOPOLITICAL_LOGISTICS,
        RiskLevel.HIGH,
        "el envío cruza una frontera aduanera y la importación no la asume el proveedor",
        (*basis, f"Incoterm {incoterm or 'no declarado'}"),
    )


_ASSESSORS = {
    RiskDimension.IDENTITY: _identity,
    RiskDimension.FINANCIAL: _financial,
    RiskDimension.QUALITY: _quality,
    RiskDimension.DELIVERY: _delivery,
    RiskDimension.LEGAL: _legal,
    RiskDimension.FRAUD: _fraud,
    RiskDimension.DEPENDENCY: _dependency,
    RiskDimension.GEOPOLITICAL_LOGISTICS: _geopolitical,
}


@dataclass(frozen=True)
class SupplierRiskProfile:
    """Las ocho dimensiones evaluadas. **No tiene puntuación total**, y no es un
    olvido: es la instrucción de §11 escrita en el tipo. Quien quiera un número
    tendrá que inventárselo fuera, donde se le vea."""

    assessments: tuple[RiskAssessment, ...] = field(default=())

    def of(self, dimension: RiskDimension) -> RiskAssessment:
        for assessment in self.assessments:
            if assessment.dimension is dimension:
                return assessment
        raise KeyError(dimension)

    def at(self, level: RiskLevel) -> tuple[RiskAssessment, ...]:
        """Las dimensiones que están en un nivel. Filtrar no es puntuar: sigue
        habiendo ocho respuestas y ninguna media."""
        return tuple(a for a in self.assessments if a.level is level)

    @property
    def unassessed(self) -> tuple[RiskDimension, ...]:
        """Lo que no se ha podido evaluar. Es la lista de lo que hay que
        averiguar, y la razón por la que un perfil sin rojos no significa
        todavía que no haya riesgo."""
        return tuple(a.dimension for a in self.assessments if not a.known)


def assess(facts: SupplierRiskFacts) -> SupplierRiskProfile:
    """Las ocho dimensiones, siempre las ocho y siempre en el mismo orden.

    Que devuelva las no evaluables en vez de omitirlas es la mitad del punto:
    una lista corta dejaría al que la lee sin saber si falta una dimensión
    porque está bien o porque nadie la miró.
    """
    return SupplierRiskProfile(
        assessments=tuple(_ASSESSORS[dimension](facts) for dimension in RiskDimension)
    )
