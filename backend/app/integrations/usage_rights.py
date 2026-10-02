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


#: EUR-Lex a través de Cellar (Milestone 41, ADR 0019). Leído el 29-09-2026 en el
#: aviso legal de EUR-Lex (`eur-lex.europa.eu/content/legal-notice/legal-notice.html`):
#: «EUR-Lex **metadata** is dedicated to the public domain» (CC0 1.0), y los
#: documentos jurídicos se pueden reutilizar «for commercial or non-commercial
#: purposes» bajo la Decisión 2011/833/UE salvo condiciones especiales indicadas
#: en el propio documento.
#:
#: **Lo que se guarda son solo metadatos**: existencia, vigencia, fechas, ELI. Ni el
#: texto de un artículo ni una traducción, que son lo que sí tendría condiciones.
#: Por eso los permisos de abajo valen para lo que se guarda y **no** se extienden
#: al contenido de los documentos, que no se toca.
#:
#: Aparte de la licencia, el aviso legal advierte de que la información «no es
#: asesoramiento profesional ni jurídico» y de que solo el Diario Oficial es
#: auténtico. Esa advertencia se traslada a la salida de Legal.
_EUR_LEX_CELLAR = ProviderRights(
    provider="eur-lex-cellar",
    source="https://eur-lex.europa.eu/content/legal-notice/legal-notice.html — aviso de derechos de autor",
    verified_on=datetime.date(2026, 9, 29),
    rights={
        UsageRight.STORAGE: RightStatus.ALLOWED,
        UsageRight.RETENTION: RightStatus.ALLOWED,
        UsageRight.TRANSFORMATION: RightStatus.ALLOWED,
        UsageRight.DERIVED_METRICS: RightStatus.ALLOWED,
        UsageRight.SCORING: RightStatus.ALLOWED,
        UsageRight.AI_INGESTION: RightStatus.ALLOWED,
        UsageRight.REDISTRIBUTION: RightStatus.ALLOWED,
        UsageRight.COMMERCIAL_USE: RightStatus.ALLOWED,
    },
    attribution=AttributionRequirement.NOT_REQUIRED,
    notes={
        UsageRight.STORAGE: "Solo metadatos (CC0). El texto de los documentos no se guarda.",
        UsageRight.AI_INGESTION: (
            "Permitido para los metadatos por CC0. No se usa: el plan maestro §26 prohíbe un LLM "
            "en el camino de decisión, y el requisito legal lo declara una persona."
        ),
        UsageRight.REDISTRIBUTION: (
            "Metadatos CC0. Los textos consolidados y resúmenes de EUR-Lex son CC BY 4.0 y "
            "exigirían citar la fuente e indicar cambios: no se redistribuyen."
        ),
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


#: Tipos de cambio de referencia del BCE (Milestone 42, ADR 0020). Leído el
#: 29-09-2026 en el aviso legal del BCE
#: (`ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html`, sección
#: «Copyright») y en la página de las tasas
#: (`…/euro_reference_exchange_rates/html/index.en.html`).
#:
#: **Lo que dice:** los usuarios «may make free use of the information obtained
#: directly from» la web del BCE con cuatro condiciones: citar al BCE como fuente,
#: avisar a quien compre un documento que lo incorpore de que es gratuito, decir
#: explícitamente si la información se modifica, y no enmarcar la web. No exige alta
#: ni credenciales.
#:
#: **Lo que NO dice:** nada sobre almacenar, conservar, puntuar, derivar métricas ni
#: usos comerciales *por separado*. Los permisos de abajo se leen del uso libre
#: general y de la ausencia de una restricción específica; **no** son una
#: autorización expresa de cada uso, y eso queda dicho en las notas. Tampoco dice
#: nada sobre ingestión por sistemas de IA: queda `UNKNOWN`, es decir denegado.
#:
#: **Advertencia que no es un permiso:** el BCE publica las referencias «for
#: information purposes only» y desaconseja usarlas para transacciones. Aquí se usan
#: para estimar un margen. Esa advertencia viaja con la tasa a la pantalla.
_ECB_REFERENCE_RATES = ProviderRights(
    provider="ecb-reference-rates",
    source=(
        "https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html "
        "— «Copyright»; y la página de las tasas de referencia del euro"
    ),
    verified_on=datetime.date(2026, 9, 29),
    rights={
        UsageRight.STORAGE: RightStatus.ALLOWED,
        UsageRight.RETENTION: RightStatus.ALLOWED,
        UsageRight.TRANSFORMATION: RightStatus.ALLOWED,
        UsageRight.DERIVED_METRICS: RightStatus.ALLOWED,
        UsageRight.SCORING: RightStatus.ALLOWED,
        UsageRight.AI_INGESTION: RightStatus.UNKNOWN,
        UsageRight.REDISTRIBUTION: RightStatus.ALLOWED,
        UsageRight.COMMERCIAL_USE: RightStatus.ALLOWED,
    },
    attribution=AttributionRequirement.REQUIRED,
    notes={
        UsageRight.STORAGE: (
            "Uso libre general del contenido de la web del BCE; no hay una cláusula específica "
            "sobre almacenamiento."
        ),
        UsageRight.RETENTION: (
            "Igual que el almacenamiento: no hay plazo de conservación escrito. Las "
            "observaciones no se borran, porque una decisión tiene que poder reconstruirse."
        ),
        UsageRight.TRANSFORMATION: (
            "Invertir una tasa (USD→EUR) es una modificación: la condición 3 obliga a decirlo, y "
            "cada conversión registra la dirección (`inverted`)."
        ),
        UsageRight.DERIVED_METRICS: (
            "Un importe convertido es una cifra derivada, y como tal se marca como modificada."
        ),
        UsageRight.SCORING: (
            "Sin restricción específica. No entra en `opportunity_score` ni en el Decision Engine: "
            "convierte importes."
        ),
        UsageRight.AI_INGESTION: (
            "Los términos no dicen nada. Sin resolver, y por tanto denegado. Coherente con el plan "
            "maestro §26: no hay LLM en el camino de decisión."
        ),
        UsageRight.REDISTRIBUTION: (
            "Permitido con las condiciones de atribución y de aviso de modificación. La tasa se "
            "enseña en pantalla con su fuente y su advertencia."
        ),
        UsageRight.COMMERCIAL_USE: (
            "El uso libre no distingue entre comercial y no comercial. La condición 2 solo se "
            "refiere a documentos que se vendan: no aplica a estimar un margen interno."
        ),
    },
)


#: Legislación consolidada y sumarios de la API de datos abiertos del BOE
#: (Milestone 43, ADR 0021). Leído el 29-09-2026 en el aviso legal de la AEBOE
#: (`boe.es/informacion/aviso_legal/`, «Condiciones de reutilización», licencia tipo
#: de la Resolución de 27-06-2024, vigente desde el 28-06-2024) y en las FAQ de la API
#: consolidada.
#:
#: **Lo que dice:** la reutilización está autorizada «para fines comerciales y no
#: comerciales», incluida «la modificación, adaptación, extracción, reordenación y
#: combinación» para crear productos de valor añadido. Condiciones: citar la fuente
#: («Basado en datos de la Agencia Estatal Boletín Oficial del Estado» cuando hay
#: obra derivada, con enlace a boe.es); en legislación consolidada, indicar
#: **expresamente** que es un texto consolidado de carácter meramente informativo;
#: mencionar la fecha de última actualización y conservar los metadatos de fecha;
#: identificar toda modificación; no desnaturalizar la información ni sugerir que es
#: oficial o que la AEBOE la respalda.
#:
#: **Lo que NO dice:** nada sobre ingestión por sistemas de IA: queda `UNKNOWN`,
#: denegado. Los demás permisos se leen de la autorización general y de la ausencia
#: de una restricción específica; **no** son una autorización expresa de cada uso.
#:
#: **Lo que se guarda:** metadatos, banderas de estado y relaciones del análisis,
#: verbatim. **No** el texto de las normas. Y la propia fuente advierte de que la
#: consolidación y el análisis son informativos: solo los diarios oficiales son
#: auténticos. Esa limitación viaja con el dato hasta la pantalla.
_BOE_OPEN_DATA = ProviderRights(
    provider="boe-open-data",
    source=(
        "https://www.boe.es/informacion/aviso_legal/index.php#reutilizacion — condiciones de "
        "reutilización; y https://www.boe.es/datosabiertos/faq/consolidada.php"
    ),
    verified_on=datetime.date(2026, 9, 29),
    rights={
        UsageRight.STORAGE: RightStatus.ALLOWED,
        UsageRight.RETENTION: RightStatus.ALLOWED,
        UsageRight.TRANSFORMATION: RightStatus.ALLOWED,
        UsageRight.DERIVED_METRICS: RightStatus.ALLOWED,
        UsageRight.SCORING: RightStatus.ALLOWED,
        UsageRight.AI_INGESTION: RightStatus.UNKNOWN,
        UsageRight.REDISTRIBUTION: RightStatus.ALLOWED,
        UsageRight.COMMERCIAL_USE: RightStatus.ALLOWED,
    },
    attribution=AttributionRequirement.REQUIRED,
    notes={
        UsageRight.STORAGE: (
            "Metadatos, banderas y relaciones. El texto de las normas no se guarda."
        ),
        UsageRight.RETENTION: (
            "Sin plazo escrito. Las comprobaciones no se borran: una decisión legal tiene que "
            "poder reconstruirse."
        ),
        UsageRight.TRANSFORMATION: (
            "La normalización de forma (banderas S/N, códigos) es una adaptación: la cita de obra "
            "derivada aplica y los datos de fecha se conservan sin alterar."
        ),
        UsageRight.DERIVED_METRICS: (
            "La corroboración de una transposición es una cifra derivada: se identifica como tal."
        ),
        UsageRight.SCORING: "Sin restricción específica. No entra en `opportunity_score`.",
        UsageRight.AI_INGESTION: (
            "Los términos no dicen nada. Sin resolver, y por tanto denegado. Coherente con el plan "
            "maestro §26: no hay LLM en el camino de decisión legal."
        ),
        UsageRight.REDISTRIBUTION: (
            "Permitido con cita, fecha de actualización y el aviso de que el texto consolidado es "
            "meramente informativo."
        ),
        UsageRight.COMMERCIAL_USE: (
            "La licencia autoriza expresamente fines comerciales y no comerciales."
        ),
    },
)


#: Registro por proveedor. Un proveedor que no esté aquí **no tiene permisos**,
#: no porque se le presuma nada, sino porque nadie ha leído su licencia. Hay un
#: test que falla si un adaptador real se registra sin su entrada.
#: Los simuladores de pagos y de fulfillment (Milestone 44, ADR 0028): los datos que devuelven los generamos
#: nosotros, así que, como con el mock, no hay un tercero a quien pedir permiso. Qué operaciones declaran
#: soportar **no** se dice aquí sino en `operating_policy`: son dos preguntas distintas.
_SIMULATED_PAYMENTS = ProviderRights(
    provider="simulated-payments",
    source="app/payments/providers/simulated.py — datos propios del repositorio",
    verified_on=datetime.date(2026, 10, 2),
    rights=_all(RightStatus.ALLOWED),
    attribution=AttributionRequirement.NOT_REQUIRED,
)
_SIMULATED_FULFILMENT = ProviderRights(
    provider="simulated-fulfilment",
    source="app/orders/simulated_fulfilment.py — datos propios del repositorio",
    verified_on=datetime.date(2026, 10, 2),
    rights=_all(RightStatus.ALLOWED),
    attribution=AttributionRequirement.NOT_REQUIRED,
)

USAGE_RIGHTS: dict[str, ProviderRights] = {
    _FIXTURES.provider: _FIXTURES,
    _SIMULATED_PAYMENTS.provider: _SIMULATED_PAYMENTS,
    _SIMULATED_FULFILMENT.provider: _SIMULATED_FULFILMENT,
    _WIKIMEDIA.provider: _WIKIMEDIA,
    _WIKIMEDIA_LANGLINKS.provider: _WIKIMEDIA_LANGLINKS,
    _EBAY_BROWSE.provider: _EBAY_BROWSE,
    _EUR_LEX_CELLAR.provider: _EUR_LEX_CELLAR,
    _ECB_REFERENCE_RATES.provider: _ECB_REFERENCE_RATES,
    _BOE_OPEN_DATA.provider: _BOE_OPEN_DATA,
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
