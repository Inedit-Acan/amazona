"""Qué se puede HACER con el dato de cada proveedor (Milestone 37, ADR 0015).

Tener el número no es tener permiso. Un adaptador que recibe una respuesta 200
sabe que **puede** leer el dato; no sabe si puede guardarlo, si puede derivar
métricas de él, si puede meterlo en un score, si puede pasárselo a un LLM, si
puede enseñárselo a un usuario ni si debe citar la fuente al hacerlo. Esas son
condiciones de licencia, viven en un contrato y **no se deducen de que la
petición funcione**.

Este módulo las escribe una vez, por proveedor, con su fuente y su fecha, para
que el resto del sistema pregunte en vez de suponer.

## La regla que lo hace seguro: lo que no se sabe, no se permite

Cada derecho es `ALLOWED`, `DENIED` o `UNKNOWN`, y **`UNKNOWN` se comporta como
`DENIED`**. No se infiere un permiso del silencio de un contrato: que una
licencia no prohíba algo expresamente no es lo mismo que autorizarlo, y la
diferencia la paga el propietario, no el código.

Es la misma familia de decisiones que «una señal ausente se queda ausente»: ante
la falta de información, el sistema no rellena con lo que le conviene.

## Qué NO es esto

No es asesoramiento legal y no pretende serlo. Es un registro de lo que se leyó,
cuándo y dónde, para que una duda sea visible en el código en vez de vivir en la
cabeza de quien escribió el adaptador. Resolver un `UNKNOWN` es una tarea
humana: leer el contrato, o preguntarle al proveedor.
"""

import datetime
from dataclasses import dataclass, field
from enum import StrEnum


class UsageRight(StrEnum):
    """Los usos que una licencia puede permitir, prohibir o no aclarar."""

    #: Guardar el dato más allá de la petición que lo trajo.
    STORAGE = "storage"
    #: Conservarlo indefinidamente, en vez de tener que caducarlo.
    RETENTION = "retention"
    #: Transformarlo: normalizar, agregar, convertir de unidades.
    TRANSFORMATION = "transformation"
    #: Derivar métricas propias de él y guardarlas como tales.
    DERIVED_METRICS = "derived_metrics"
    #: Meterlo en un score, un ranking o un algoritmo de decisión.
    SCORING = "scoring"
    #: Pasárselo a un modelo de lenguaje o a cualquier sistema de IA que no sea
    #: del propio proveedor.
    AI_INGESTION = "ai_ingestion"
    #: Redistribuirlo o exponerlo a un usuario final, en bruto o agregado.
    REDISTRIBUTION = "redistribution"
    #: Usarlo con ánimo comercial.
    COMMERCIAL_USE = "commercial_use"


class RightStatus(StrEnum):
    """Lo que dice la licencia sobre un uso.

    `UNKNOWN` no es un estado intermedio ni un «probablemente sí»: a efectos de
    lo que el sistema hace, **pesa igual que `DENIED`**. Existe separado porque
    la diferencia importa para quien tenga que resolverlo: `DENIED` está cerrado,
    `UNKNOWN` está por leer.
    """

    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class AttributionRequirement(StrEnum):
    """Si hay que citar la fuente al enseñar el dato.

    Va aparte de `UsageRight` porque no es un permiso, es un **deber**: lo
    conservador aquí no es abstenerse, es atribuir. Por eso `UNKNOWN` se trata
    como `REQUIRED` y no como una prohibición.
    """

    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderRights:
    """Lo que se leyó de la licencia de un proveedor, y cuándo."""

    #: El mismo nombre que la señal persiste en `provider`.
    provider: str
    #: Dónde se leyó. Sin esto, la matriz es una opinión.
    source: str
    #: Cuándo se leyó. Una licencia cambia; una fecha de 2026 avisa en 2028.
    verified_on: datetime.date
    rights: dict[UsageRight, RightStatus] = field(default_factory=dict)
    attribution: AttributionRequirement = AttributionRequirement.UNKNOWN
    #: Por qué cada derecho quedó como quedó. La clave es el derecho.
    notes: dict[UsageRight, str] = field(default_factory=dict)

    def status_of(self, right: UsageRight) -> RightStatus:
        """Un derecho que nadie escribió es un derecho sin leer, no un permiso."""
        return self.rights.get(right, RightStatus.UNKNOWN)

    def permits(self, right: UsageRight) -> bool:
        return self.status_of(right) is RightStatus.ALLOWED

    @property
    def attribution_required(self) -> bool:
        """Ante la duda se atribuye: citar de más no hace daño a nadie."""
        return self.attribution is not AttributionRequirement.NOT_REQUIRED

    @property
    def unresolved(self) -> list[UsageRight]:
        """Lo que queda por leer. Es la lista de tareas humanas del proveedor."""
        return sorted(
            (right for right in UsageRight if self.status_of(right) is RightStatus.UNKNOWN),
            key=lambda right: right.value,
        )


def _all(status: RightStatus) -> dict[UsageRight, RightStatus]:
    return {right: status for right in UsageRight}


#: Lo que emite el mock. No hay licencia de nadie: el dato es nuestro, inventado
#: por nosotros, en un fichero del repositorio. Todo permitido porque no hay un
#: tercero a quien pedir permiso — y aun así **sigue siendo un fixture**, lo cual
#: lo gobierna la base de la señal, no esta matriz. Son dos preguntas distintas:
#: «¿puedo usar esto legalmente?» y «¿esto es verdad?».
_FIXTURES = ProviderRights(
    provider="fixtures",
    source="app/ai/mock_trends_provider.py — datos propios del repositorio",
    verified_on=datetime.date(2026, 9, 28),
    rights=_all(RightStatus.ALLOWED),
    attribution=AttributionRequirement.NOT_REQUIRED,
    notes={
        UsageRight.SCORING: (
            "Permitido legalmente y desaconsejado en la práctica: un fixture no mide nada. "
            "Lo que impide que contamine una decisión es su base SIMULATED, no su licencia."
        )
    },
)


#: Wikimedia Pageviews. Verificado el 28-09-2026 en la propia API: su
#: especificación declara que «content accessed via this API is licensed under
#: the CC-BY-SA 3.0 and GFDL licenses» salvo que la documentación del endpoint
#: diga otra cosa, exige un `User-Agent` identificable y pide no pasar de 200
#: peticiones por segundo.
#:
#: CC-BY-SA permite copiar, conservar, adaptar y usar comercialmente, **citando
#: la fuente** y compartiendo igual las adaptaciones que se publiquen. De ahí
#: salen los permisos de abajo, y de ahí sale que la atribución sea obligatoria.
_WIKIMEDIA = ProviderRights(
    provider="wikimedia-pageviews",
    source="https://wikimedia.org/api/rest_v1/?spec — info.description y info.termsOfService",
    verified_on=datetime.date(2026, 9, 28),
    rights={
        UsageRight.STORAGE: RightStatus.ALLOWED,
        UsageRight.RETENTION: RightStatus.ALLOWED,
        UsageRight.TRANSFORMATION: RightStatus.ALLOWED,
        UsageRight.DERIVED_METRICS: RightStatus.ALLOWED,
        UsageRight.SCORING: RightStatus.ALLOWED,
        # CC-BY-SA no dice nada de entrenar ni alimentar modelos. No decir nada
        # no es autorizar, y aquí no se infiere.
        UsageRight.AI_INGESTION: RightStatus.UNKNOWN,
        UsageRight.REDISTRIBUTION: RightStatus.ALLOWED,
        UsageRight.COMMERCIAL_USE: RightStatus.ALLOWED,
    },
    attribution=AttributionRequirement.REQUIRED,
    notes={
        UsageRight.RETENTION: "CC-BY-SA no impone caducidad.",
        UsageRight.DERIVED_METRICS: (
            "ShareAlike puede alcanzar a las adaptaciones que se publiquen; para uso interno no "
            "cambia nada, para algo publicado habrá que mirarlo."
        ),
        UsageRight.AI_INGESTION: (
            "Sin resolver, y por tanto denegado. La licencia no lo aborda expresamente. "
            "Afecta al plan maestro §26 si algún día un LLM resume estas señales."
        ),
        UsageRight.COMMERCIAL_USE: (
            "Permitido por licencia. Aparte de la licencia, el volumen: Wikimedia ofrece su API "
            "Enterprise para reutilización comercial de alto volumen, y el límite declarado aquí "
            "son 200 peticiones/s. Es una cuestión de cortesía y de escala, no de permiso."
        ),
    },
)


#: Wikimedia langlinks. **Misma casa y misma licencia de contenido** que las
#: visitas: los proyectos de Wikimedia publican su texto bajo CC-BY-SA, verificado
#: el 28-09-2026. Lo que se guarda de aquí no es ni siquiera contenido de un
#: artículo: es la **equivalencia declarada** entre dos títulos.
#:
#: `AI_INGESTION` queda sin resolver por lo mismo que en las visitas: la licencia
#: no lo aborda, y no decir nada no es autorizar.
_WIKIMEDIA_LANGLINKS = ProviderRights(
    provider="wikimedia-langlinks",
    source="https://wikimedia.org/api/rest_v1/?spec y los términos de uso de Wikimedia",
    verified_on=datetime.date(2026, 9, 28),
    rights={
        UsageRight.STORAGE: RightStatus.ALLOWED,
        UsageRight.RETENTION: RightStatus.ALLOWED,
        UsageRight.TRANSFORMATION: RightStatus.ALLOWED,
        UsageRight.DERIVED_METRICS: RightStatus.ALLOWED,
        # No produce señales, así que no puntúa nada: resuelve identidad. Se
        # declara permitido para que no haya que razonarlo cada vez.
        UsageRight.SCORING: RightStatus.ALLOWED,
        UsageRight.AI_INGESTION: RightStatus.UNKNOWN,
        UsageRight.REDISTRIBUTION: RightStatus.ALLOWED,
        UsageRight.COMMERCIAL_USE: RightStatus.ALLOWED,
    },
    attribution=AttributionRequirement.REQUIRED,
    notes={
        UsageRight.STORAGE: (
            "Lo que se persiste es un nombre y quién declaró la equivalencia, no el texto de "
            "ningún artículo."
        ),
        UsageRight.AI_INGESTION: "Sin resolver, y por tanto denegado. Igual que en las visitas.",
    },
)


#: eBay Browse. La licencia se leyó el 28-09-2026 y **dejó más preguntas que
#: respuestas**, así que casi todo queda sin resolver — y por tanto denegado.
#:
#: El nudo es su categoría de «Restricted APIs», que el contrato define como
#: «any eBay APIs that provide information about market trends, pricing
#: strategies, sales volumes, user behavior». Para esas APIs prohíbe
#: expresamente incorporar la información a sistemas de IA ajenos sin
#: consentimiento escrito, redistribuirla en bruto o agregada, y usarla para
#: desarrollar herramientas de precios sin consentimiento expreso previo.
#:
#: **No se ha podido determinar si Browse entra en esa categoría.** Se obtiene
#: con un keyset estándar, lo que apunta a que no; devuelve recuentos de anuncios
#: y precios de venta pedidos, lo que apunta a que quizá sí. Eso es exactamente
#: un `UNKNOWN`, y no se resuelve adivinando: se resuelve leyendo el contrato con
#: más detalle o preguntándole a eBay.
_EBAY_BROWSE = ProviderRights(
    provider="ebay-browse",
    source="https://developer.ebay.com/join/api-license-agreement — leída el 28-09-2026",
    verified_on=datetime.date(2026, 9, 28),
    rights={
        UsageRight.STORAGE: RightStatus.UNKNOWN,
        UsageRight.RETENTION: RightStatus.UNKNOWN,
        UsageRight.TRANSFORMATION: RightStatus.UNKNOWN,
        UsageRight.DERIVED_METRICS: RightStatus.UNKNOWN,
        UsageRight.SCORING: RightStatus.UNKNOWN,
        UsageRight.AI_INGESTION: RightStatus.UNKNOWN,
        # Este sí está cerrado, y además no nos hace falta: no redistribuimos.
        UsageRight.REDISTRIBUTION: RightStatus.DENIED,
        UsageRight.COMMERCIAL_USE: RightStatus.UNKNOWN,
    },
    attribution=AttributionRequirement.UNKNOWN,
    notes={
        UsageRight.STORAGE: (
            "La licencia no contiene ninguna cláusula de caché ni de almacenamiento para "
            "contenido no personal — la palabra «cache» no aparece—, pero tampoco lo autoriza "
            "expresamente. Sin resolver."
        ),
        UsageRight.DERIVED_METRICS: (
            "«eBay retains all rights… and shall own any content created or derived therefrom or "
            "any form of derivative works». Es propiedad, no prohibición, y hay que aclarar qué "
            "significa para unas métricas guardadas en nuestra base de datos."
        ),
        UsageRight.SCORING: (
            "Para las Restricted APIs el uso «to develop pricing tools» exige consentimiento "
            "escrito previo. Un score de oportunidad no es una herramienta de precios, pero está "
            "lo bastante cerca para no darlo por bueno solo."
        ),
        UsageRight.AI_INGESTION: (
            "Prohibido expresamente para Restricted APIs sin consentimiento escrito. Depende de "
            "si Browse es una de ellas."
        ),
        UsageRight.REDISTRIBUTION: (
            "Denegado por decisión propia además de por contrato: el sistema no expone datos de "
            "terceros a nadie fuera de la organización. Enseñarlo en el Control Center del "
            "propietario es uso interno, no redistribución."
        ),
        UsageRight.COMMERCIAL_USE: (
            "Relectura acotada del 28-09-2026, y apareció algo que no estaba en la licencia sino "
            "en los requisitos de las Buy APIs: «Many of the Buy APIs are a (Limited Release). "
            "The use of eBay's Buy APIs in production is intended for eBay partners only. You "
            "must apply for production access through the eBay Partner Network. Acceptance of "
            "applications is based on the proposed business model». El keyset gratuito sirve para "
            "el sandbox; producción exige aprobación con revisión del modelo de negocio. Eso son "
            "permisos especiales, así que este adaptador queda APARCADO como implementación de "
            "referencia (Milestone 38)."
        ),
    },
)


#: Registro por proveedor. Un proveedor que no esté aquí **no tiene permisos**,
#: no porque se le presuma nada, sino porque nadie ha leído su licencia. Hay un
#: test que falla si un adaptador real se registra sin su entrada.
USAGE_RIGHTS: dict[str, ProviderRights] = {
    _FIXTURES.provider: _FIXTURES,
    _WIKIMEDIA.provider: _WIKIMEDIA,
    _WIKIMEDIA_LANGLINKS.provider: _WIKIMEDIA_LANGLINKS,
    _EBAY_BROWSE.provider: _EBAY_BROWSE,
}


#: Para un proveedor del que no hay nada escrito: todo sin leer, y por tanto
#: nada permitido.
UNREGISTERED = ProviderRights(
    provider="<unregistered>",
    source="nadie ha leído la licencia de este proveedor",
    verified_on=datetime.date(2026, 9, 28),
    rights=_all(RightStatus.UNKNOWN),
    attribution=AttributionRequirement.UNKNOWN,
)


def rights_for(provider: str) -> ProviderRights:
    return USAGE_RIGHTS.get(provider, UNREGISTERED)


def permits(provider: str, right: UsageRight) -> bool:
    """Si el sistema puede hacer *eso* con el dato de *ese* proveedor.

    Es la única función que el resto del código debería llamar. Devuelve `False`
    ante un `UNKNOWN`, y eso es la característica, no una limitación.
    """
    return rights_for(provider).permits(right)
