"""Dónde se mide una señal (Milestone 38, ADR 0016).

`market` dice **en qué geografía**; este módulo dice **en qué canal**. Son dos
preguntas distintas y hasta aquí solo existía la primera, así que una señal de
competencia podía significar cosas incompatibles sin que nada en el dato lo
avisara: cuántos vendedores compiten dentro de un marketplace no es lo mismo que
cuánto cuesta atraer a un comprador a una web propia.

## Cuatro tipos y una lista abierta

Los **tipos** son cerrados porque son conceptos, no proveedores: las cuatro formas
en que un producto se encuentra con quien lo compra. Las **plataformas** son
abiertas: añadir Etsy, Mercado Libre o el marketplace de turno es **una entrada en
este fichero y ninguna migración**. Amazon y eBay son valores, no tipos.

## La clave se lee sola, y ninguna lógica la parsea

Una fila de `product_signals` con `channel = 'marketplace:amazon'` se entiende sin
consultar nada, que es la misma razón por la que `method` viaja con cada número.
Pero el **tipo** lo da este catálogo, no un `split(':')`: si mañana una clave
cambiara de forma, cambiaría aquí y no en cinco sitios que la interpretaban.

## Y TikTok no es TikTok Shop

Uno es una superficie social donde se descubre y se anuncia; el otro es un
marketplace donde se cobra. Comparten marca y no comparten naturaleza, así que son
dos canales con dos tipos distintos. Es el ejemplo que mejor explica por qué el
tipo no se puede deducir del nombre de la plataforma.
"""

from dataclasses import dataclass
from enum import StrEnum


class ChannelKind(StrEnum):
    """Las cuatro formas en que un producto llega a quien lo compra.

    Cerrado a propósito: un tipo nuevo aquí significaría que hay una manera de
    vender que el sistema no contemplaba, y eso merece una decisión, no una
    entrada de catálogo.
    """

    #: Una web propia de KOVA. El canal prioritario del proyecto.
    OWN_WEB = "own_web"
    #: El marketplace de un tercero, donde además se cobra.
    MARKETPLACE = "marketplace"
    #: Una superficie de búsqueda. Mide intención, no transacción.
    SEARCH = "search"
    #: Una superficie social. Mide descubrimiento y conversación.
    SOCIAL = "social"


@dataclass(frozen=True)
class Channel:
    """Un canal concreto, declarado."""

    #: Lo que se persiste en la señal. Autodescriptiva para quien lea una fila.
    key: str
    kind: ChannelKind
    #: Cómo se llama para una persona.
    name: str
    #: Si en este canal se cobra. Un canal transaccional tiene competencia de
    #: vendedores; uno que no lo es tiene competencia de atención.
    transactional: bool
    notes: str = ""


#: Los canales declarados. Añadir una plataforma es añadir aquí una línea.
#:
#: No están todos los marketplaces del mundo, y no deberían: un canal que nadie
#: mide todavía sería una casilla vacía invitando a rellenarla. Están el canal
#: prioritario, los que el propietario ha nombrado y las superficies de las que ya
#: hay o habrá señal.
CHANNELS: dict[str, Channel] = {
    "own_web": Channel(
        key="own_web",
        kind=ChannelKind.OWN_WEB,
        name="Web propia",
        transactional=True,
        notes=(
            "El canal prioritario. Hoy **no hay ninguna web propia con tráfico real**, así que no "
            "hay señal de este canal y no se simula ninguna: cuando exista, su analítica será la "
            "mejor fuente que este sistema puede tener."
        ),
    ),
    "marketplace:amazon": Channel(
        key="marketplace:amazon",
        kind=ChannelKind.MARKETPLACE,
        name="Amazon",
        transactional=True,
        notes="Sin fuente de datos conectada: no hay camino gratuito (ver el documento de fuentes).",
    ),
    "marketplace:ebay": Channel(
        key="marketplace:ebay",
        kind=ChannelKind.MARKETPLACE,
        name="eBay",
        transactional=True,
        notes=(
            "Complementario. Tiene adaptador y está **aparcado**: producción exige aprobación del "
            "eBay Partner Network, y sus derechos de uso siguen sin resolver (ADR 0015 §5)."
        ),
    ),
    "marketplace:etsy": Channel(
        key="marketplace:etsy",
        kind=ChannelKind.MARKETPLACE,
        name="Etsy",
        transactional=True,
        notes="Sin adaptador. Su API es gratuita y el acceso más allá de tu tienda pasa revisión.",
    ),
    "marketplace:mercado_libre": Channel(
        key="marketplace:mercado_libre",
        kind=ChannelKind.MARKETPLACE,
        name="Mercado Libre",
        transactional=True,
        notes="Sin adaptador. Exige aplicación registrada con OAuth, gratuita.",
    ),
    "marketplace:tiktok_shop": Channel(
        key="marketplace:tiktok_shop",
        kind=ChannelKind.MARKETPLACE,
        name="TikTok Shop",
        transactional=True,
        notes=(
            "**No es lo mismo que `social:tiktok`.** Aquí se cobra; allí se descubre. Comparten "
            "marca y no naturaleza."
        ),
    ),
    "search:google": Channel(
        key="search:google",
        kind=ChannelKind.SEARCH,
        name="Búsqueda de Google",
        transactional=False,
        notes=(
            "Es el canal que la venta directa necesita medir —intención y coste del clic— y para "
            "el que **no hay fuente gratuita fiable**. Declarado para que la señal del día que la "
            "haya no tenga que inventarse un sitio donde vivir."
        ),
    ),
    "social:tiktok": Channel(
        key="social:tiktok",
        kind=ChannelKind.SOCIAL,
        name="TikTok",
        transactional=False,
        notes="Descubrimiento y adquisición, no transacción. Ver `marketplace:tiktok_shop`.",
    ),
    "social:reddit": Channel(
        key="social:reddit",
        kind=ChannelKind.SOCIAL,
        name="Reddit",
        transactional=False,
        notes="Señal social real y gratuita, y ruidosa. Sin adaptador todavía.",
    ),
}


class UnknownChannelError(ValueError):
    """Un canal que no está declarado.

    Falla en voz alta porque la alternativa es peor: un typo se convertiría en un
    canal fantasma con sus propias señales, invisible para cualquier consulta que
    buscara el canal de verdad.
    """


def channel_for(key: str) -> Channel:
    channel = CHANNELS.get(key)
    if channel is None:
        available = ", ".join(sorted(CHANNELS))
        raise UnknownChannelError(f"no channel called {key!r}; declared: {available}")
    return channel


def keys_of_kind(kind: ChannelKind) -> tuple[str, ...]:
    """Los canales de un tipo, para preguntar «todos los marketplaces» sin que
    nadie tenga que parsear una cadena."""
    return tuple(
        sorted(key for key, channel in CHANNELS.items() if channel.kind is kind)
    )
