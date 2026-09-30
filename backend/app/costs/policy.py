"""Lo que cuesta llamar a cada proveedor, declarado (Milestone 37, plan §25).

El plan maestro §25 es explícito: **antes** de introducir LLM o APIs comerciales
hay que poder contar `provider, operation, units, estimated_cost, actual_cost,
currency, correlation_id` y poner límites. Este módulo es la mitad declarativa de
eso: qué modelo de precio tiene cada proveedor y qué topes trae de fábrica.

## Gratis no es lo mismo que sin límite

Una fuente gratuita también se agota: eBay publica 5.000 llamadas al día,
Wikimedia pide no pasar de 200 por segundo. Así que una política declara dos
cosas distintas —**cuánto cuesta** y **cuánto se puede pedir**— y la segunda
existe aunque la primera sea cero.

## Y de pago sin límite autorizado significa que no se llama

El presupuesto del Milestone 37 es **0 €**. Un proveedor con coste por unidad
mayor que cero y sin un límite de gasto autorizado **no se llama**: se deniega y
se anota por qué. No se hereda un presupuesto de ninguna parte y no se escribe
aquí ningún techo futuro — eso vive en configuración, donde el propietario lo
pone cuando decida ponerlo.
"""

from dataclasses import dataclass
from enum import StrEnum


class Pricing(StrEnum):
    """Cómo cobra un proveedor.

    `FREE` no significa «sin condiciones»: significa que la unidad no se factura.
    Sus cuotas siguen existiendo y se siguen respetando.
    """

    FREE = "free"
    PAID = "paid"


@dataclass(frozen=True)
class CostPolicy:
    """Lo que se sabe del precio y de las cuotas de un proveedor.

    Todo lo de aquí está **verificado en la documentación del proveedor**, con su
    fecha en el comentario de cada entrada. Un número inventado en este fichero
    se convertiría en un presupuesto inventado.
    """

    provider: str
    pricing: Pricing
    #: Qué se cuenta: peticiones, tokens, créditos. Sin esto, «8 unidades» no
    #: significa nada.
    unit: str
    #: Lo que cuesta una unidad. `0.0` en las gratuitas.
    cost_per_unit: float
    currency: str
    #: La cuota que el proveedor publica, si publica alguna.
    quota_units_per_day: int | None = None
    #: Tope por ejecución, para no acercarse al arriendo de 60 s de un trabajo
    #: (ADR 0009). No es una condición del proveedor: es nuestra.
    max_units_per_run: int | None = None
    #: Dónde se comprobaron estas cifras.
    source: str = ""


#: Wikimedia Pageviews: sin clave, sin coste y con un límite de cortesía de 200
#: peticiones por segundo declarado en la propia especificación de la API
#: (verificado el 28-09-2026). El tope por ejecución es el que el adaptador ya
#: se aplicaba desde el Milestone 34.
_WIKIMEDIA = CostPolicy(
    provider="wikimedia-pageviews",
    pricing=Pricing.FREE,
    unit="requests",
    cost_per_unit=0.0,
    currency="EUR",
    quota_units_per_day=None,
    max_units_per_run=8,
    source="https://wikimedia.org/api/rest_v1/?spec — «no more than 200 requests/s»",
)

#: eBay Browse: gratis con un keyset de desarrollador. **5.000 llamadas al día**
#: por aplicación, ampliables con una revisión gratuita (verificado el
#: 28-09-2026 en la documentación y el soporte oficial).
_EBAY_BROWSE = CostPolicy(
    provider="ebay-browse",
    pricing=Pricing.FREE,
    unit="requests",
    cost_per_unit=0.0,
    currency="EUR",
    quota_units_per_day=5000,
    max_units_per_run=8,
    source="https://developer.ebay.com/support/api-call-limits — 5.000 llamadas/día",
)

#: Wikimedia langlinks: la API de acciones de cada proyecto. Sin clave y sin coste,
#: con el mismo límite de cortesía que la REST. Cuenta aparte de las visitas porque
#: es otra superficie: una cuota agotada en una no dice nada de la otra.
_WIKIMEDIA_LANGLINKS = CostPolicy(
    provider="wikimedia-langlinks",
    pricing=Pricing.FREE,
    unit="requests",
    cost_per_unit=0.0,
    currency="EUR",
    quota_units_per_day=None,
    max_units_per_run=8,
    source="https://www.mediawiki.org/wiki/API:Langlinks — API de acciones, sin clave",
)

#: EUR-Lex a través de Cellar (Milestone 41). Consulta SPARQL anónima, sin clave y
#: sin coste (verificado el 29-09-2026: dos consultas anónimas devolvieron HTTP 200;
#: la documentación de reutilización de EUR-Lex lista el punto SPARQL como acceso
#: directo). **No he encontrado una cuota publicada**, así que no se escribe
#: ninguna: `quota_units_per_day` queda en `None` y eso significa «no sé», no «sin
#: límite». El tope por ejecución es nuestro y no una condición del proveedor.
_EUR_LEX_CELLAR = CostPolicy(
    provider="eur-lex-cellar",
    pricing=Pricing.FREE,
    unit="requests",
    cost_per_unit=0.0,
    currency="EUR",
    quota_units_per_day=None,
    max_units_per_run=10,
    source="https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html — SPARQL de Cellar",
)

#: Referencias de tipos de cambio del euro del BCE (Milestone 42). Fichero XML
#: público, sin clave, sin alta y sin coste (verificado el 29-09-2026: descarga
#: anónima del fichero diario y del de 90 días con HTTP 200). **No he encontrado una
#: cuota publicada**, así que no se escribe ninguna: `quota_units_per_day` queda en
#: `None` y eso significa «no sé», no «sin límite». Una petición por refresco; el
#: tope por ejecución (dos: el diario y, si se pide, el histórico) es nuestro.
_ECB_REFERENCE_RATES = CostPolicy(
    provider="ecb-reference-rates",
    pricing=Pricing.FREE,
    unit="requests",
    cost_per_unit=0.0,
    currency="EUR",
    quota_units_per_day=None,
    max_units_per_run=2,
    source=(
        "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/"
        "html/index.en.html — ficheros XML de descarga"
    ),
)

#: Los fixtures no salen a ninguna parte. Existe la política para que el contador
#: no tenga que tratarlos como un caso especial.
_FIXTURES = CostPolicy(
    provider="fixtures",
    pricing=Pricing.FREE,
    unit="requests",
    cost_per_unit=0.0,
    currency="EUR",
    source="datos propios del repositorio; no hay llamada externa",
)


POLICIES: dict[str, CostPolicy] = {
    _WIKIMEDIA.provider: _WIKIMEDIA,
    _WIKIMEDIA_LANGLINKS.provider: _WIKIMEDIA_LANGLINKS,
    _EBAY_BROWSE.provider: _EBAY_BROWSE,
    _EUR_LEX_CELLAR.provider: _EUR_LEX_CELLAR,
    _ECB_REFERENCE_RATES.provider: _ECB_REFERENCE_RATES,
    _FIXTURES.provider: _FIXTURES,
}


#: Para un proveedor sin política escrita. **De pago y sin cuota conocida**, que
#: es la lectura conservadora: si nadie ha averiguado lo que cuesta, no se llama
#: hasta que alguien lo averigüe.
UNKNOWN_POLICY = CostPolicy(
    provider="<unknown>",
    pricing=Pricing.PAID,
    unit="requests",
    # No es que cueste esto: es que no se sabe. Cualquier cifra sería inventada,
    # y un coste desconocido con un tope ausente acaba en denegación de todos
    # modos, que es el resultado correcto.
    cost_per_unit=0.0,
    currency="EUR",
    source="nadie ha escrito la política de coste de este proveedor",
)


def policy_for(provider: str) -> CostPolicy:
    return POLICIES.get(provider, UNKNOWN_POLICY)


@dataclass(frozen=True)
class SpendLimit:
    """Lo que el propietario **ha autorizado** gastar con un proveedor.

    Vive en configuración y no en código a propósito: es dinero suyo, cambia sin
    desplegar, y este fichero no debe contener ningún techo futuro.
    """

    provider: str
    currency: str
    max_cost_per_run: float | None = None
    max_cost_per_day: float | None = None
    max_units_per_day: int | None = None
