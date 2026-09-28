"""Adaptador de referencia #2: competencia medida con la API Browse de eBay.

**Qué es y qué no es.** Esto cuenta **cuántos anuncios activos** hay en un
mercado de eBay para una consulta de texto. Es una señal de competencia medida —
la primera del sistema, porque Wikimedia solo sabe de interés— y **no** es el
número de vendedores de un producto concreto, **no** son unidades vendidas y
**no** es el tamaño del mercado. Un término con 260.000 anuncios está más
disputado que uno con 12; eso es todo lo que dice, y va escrito en el `method` de
cada señal que sale de aquí.

Por qué eBay como segundo adaptador, y por qué de referencia y no definitivo: es
gratis con un keyset de desarrollador, tiene entorno de pruebas propio, cubre
varios mercados por cabecera y **mide** en vez de estimar. La arquitectura queda
agnóstica a propósito (ADR 0015): este fichero es una implementación del contrato,
y quitarlo es quitarlo de una lista.

## Lo que deliberadamente NO emite

La respuesta trae también el precio de cada anuncio, y aquí se descarta. No por
descuido: `Signal.value` está normalizado a 0-1 y un precio no lo es, así que
hacerlo bien exige una dimensión de moneda que el contrato todavía no tiene
(decisión del Milestone 37: el contrato no se amplía porque un proveedor tenga el
dato). Se dice aquí para que no desaparezca sin dejar rastro, que es lo que el
Milestone 35 corrigió cuando el adaptador de Wikimedia tiraba once de doce meses.

## Y lo que su licencia no permite todavía

La matriz de derechos de uso tiene a eBay casi entero en `UNKNOWN` (ADR 0015):
su contrato define «Restricted APIs» por lo que la API aporta —tendencias de
mercado, estrategias de precio, volúmenes de venta— y no se ha podido determinar
si Browse entra ahí. Mientras siga sin resolverse, **sus señales no se persisten
ni entran en ningún score**: el sistema puede leerlas y no puede usarlas. Eso no
es un defecto del adaptador; es la regla de que lo que no se sabe no se permite.
"""

import datetime
import logging
import math
from urllib.parse import quote

import httpx

from app.costs.service import ApiBudgetExceededError, CallMeter, UnmeteredCalls
from app.integrations.ports import (
    CandidateSignals,
    ProductSignalProvider,
    Signal,
    SignalBasis,
    SignalKind,
)
from app.integrations.product_intelligence.terms import terms_for

logger = logging.getLogger(__name__)

PROVIDER_NAME = "ebay-browse"
SOURCE = "api.ebay.com/buy/browse/v1/item_summary/search"

#: El canal que mide este adaptador, declarado en `channels.py` (Milestone 38).
CHANNEL = "marketplace:ebay"

#: Producción y pruebas. El mismo adaptador sirve para los dos: lo único que
#: cambia es el host, que es justo lo que hace que `ProviderKind.SANDBOX` valga
#: para algo (Milestone 37).
PRODUCTION_HOST = "https://api.ebay.com"
SANDBOX_HOST = "https://api.sandbox.ebay.com"

SEARCH_PATH = "/buy/browse/v1/item_summary/search"
TOKEN_PATH = "/identity/v1/oauth2/token"

#: El único ámbito que hace falta para buscar: acceso de aplicación, sin usuario
#: y sin cuenta de vendedor.
OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"

SEARCH_OPERATION = "item_summary/search"
TOKEN_OPERATION = "identity/oauth2/token"

#: Qué mercado de eBay representa cada mercado nuestro. **Solo lo que se puede
#: afirmar**: un mercado sin correspondencia no se aproxima con el de al lado, se
#: queda sin respuesta. `eu` no es un país y `mx` no se ha verificado.
MARKETPLACE_FOR_MARKET: dict[str, str] = {
    "us": "EBAY_US",
    "uk": "EBAY_GB",
    "es": "EBAY_ES",
    "de": "EBAY_DE",
    "fr": "EBAY_FR",
    "it": "EBAY_IT",
}

#: Anuncios activos que se consideran el techo de la escala (competencia 1,0). Es
#: una constante de normalización declarada, no una medida: mueve el número sin
#: cambiar el orden entre candidatos, y por eso va escrita en el `method`.
LISTINGS_CEILING = 50_000

#: Techo de confianza de este adaptador. Mide de verdad, y aun así **un
#: marketplace no es el mercado**: un producto puede estar disputadísimo en
#: Amazon y vacío en eBay. Por eso no llega a 1 ni se acerca.
MAX_CONFIDENCE = 0.7

DEFAULT_MAX_REQUESTS = 8
DEFAULT_TIMEOUT_SECONDS = 6.0

_COMPETITION_METHOD = (
    "count of active listings matching a keyword query on one eBay marketplace "
    f"({{marketplace}}), log-normalised against a declared ceiling of {LISTINGS_CEILING:,} "
    "listings. PROXY FOR COMPETITION — not the number of sellers of a specific product, "
    "not units sold, not market size."
)


class EbayCredentialsMissingError(RuntimeError):
    """Se ha configurado eBay como fuente real y no hay claves.

    Se lanza al construir el adaptador y no en la primera búsqueda, por el mismo
    motivo que `validate_providers` comprueba los proveedores al arrancar
    (ADR 0008 §4): un proceso que descubre a mitad del pipeline que no puede
    preguntar ya ha hecho el daño.
    """


def normalise_listings(total: int) -> float:
    """Anuncios activos → 0-1, en escala logarítmica.

    Logarítmica porque la diferencia entre 10 y 100 anuncios dice mucho más que
    la que hay entre 10.000 y 10.090. Es la misma forma que usa el adaptador de
    Wikimedia, por coherencia entre señales de fuentes distintas.
    """
    if total <= 0:
        return 0.0
    scaled = math.log10(1 + total) / math.log10(1 + LISTINGS_CEILING)
    return max(0.0, min(1.0, scaled))


def confidence_for(total: int) -> float:
    """Cuánto se fía de su propio número.

    Un recuento grande es una señal sólida; doce anuncios pueden ser ruido, una
    categoría mal elegida o un término que en eBay no se usa. Y nunca pasa del
    techo del adaptador, porque un marketplace no es el mercado.
    """
    if total <= 0:
        return 0.0
    confidence = 0.35 + 0.35 * min(1.0, math.log10(1 + total) / math.log10(1 + 1000))
    return round(min(MAX_CONFIDENCE, confidence), 4)


class EbayBrowseProvider(ProductSignalProvider):
    """Competencia medida, un mercado a la vez."""

    name = PROVIDER_NAME

    def supports(self) -> frozenset[SignalKind]:
        """Solo competencia. Podría dar precios y no los da (ver la cabecera)."""
        return frozenset({SignalKind.COMPETITION})

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        host: str = PRODUCTION_HOST,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        meter: CallMeter | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise EbayCredentialsMissingError(
                "ebay-browse needs EBAY__CLIENT_ID and EBAY__CLIENT_SECRET; "
                "a free developer keyset is enough — there is nothing to pay for"
            )
        self._client = client
        self._client_id = client_id
        self._client_secret = client_secret
        self._host = host.rstrip("/")
        self._max_requests = max_requests
        self._timeout = timeout
        self._meter = meter or UnmeteredCalls()
        self._token: str | None = None

    def discover(
        self,
        *,
        category: str,
        keywords: list[str],
        market: str,
        max_results: int,
        channels: list[str] | None = None,
    ) -> list[CandidateSignals]:
        # Este adaptador mide un canal y solo uno. Si se investiga para otros,
        # calla: responder de eBay cuando se pregunta por una web propia sería
        # dejar que quien lea lo confunda (Milestone 38).
        if channels is not None and CHANNEL not in channels:
            logger.info("ebay was not asked about %s; channels requested: %s", CHANNEL, channels)
            return []

        marketplace = MARKETPLACE_FOR_MARKET.get(market)
        if marketplace is None:
            # Preguntar por el mercado de al lado mediría otra cosa y lo
            # presentaría como esta. Sin correspondencia no hay respuesta.
            logger.info("ebay has no marketplace mapped for market %r", market)
            return []

        terms = terms_for(category, keywords, limit=min(max_results, self._max_requests))
        if not terms:
            return []

        observed_at = datetime.datetime.now(datetime.UTC)
        client = self._client or httpx.Client(timeout=self._timeout)
        candidates: list[CandidateSignals] = []
        try:
            for term in terms:
                total, url = self._total_for(client, term, marketplace)
                if total is None:
                    continue
                signal = self._signal_for(term, total, market, marketplace, url, observed_at)
                if signal is not None:
                    candidates.append(
                        CandidateSignals(
                            name=term, category=category, signals=[signal], rationale=None
                        )
                    )
        finally:
            if self._client is None:
                client.close()
        return candidates

    # --- Una consulta ------------------------------------------------------

    def _total_for(
        self, client: httpx.Client, term: str, marketplace: str
    ) -> tuple[int | None, str]:
        """Cuántos anuncios hay, o `None` si no se pudo saber.

        Todos los caminos de fallo acaban igual a propósito —sin dato—: un
        artículo inexistente, un 429, un presupuesto agotado y un cuerpo raro
        significan cosas distintas para quien opera, se registran distinto en el
        log, y **ninguno significa «no hay competencia»**. Un cero aquí se leería
        como un hueco de mercado, que es la conclusión más cara que puede sacar
        este sistema de un error de red.
        """
        # `limit=1` porque solo queremos el recuento: el detalle de los anuncios
        # no se usa, y pedirlo traería identidades de vendedores que no queremos
        # ni tocar (ADR 0015).
        url = f"{self._host}{SEARCH_PATH}?q={quote(term, safe='')}&limit=1"
        try:
            token = self._access_token(client)
        except (ApiBudgetExceededError, httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("ebay token unavailable for %r: %s", term, exc)
            return None, url

        try:
            self._meter.authorise(
                provider=PROVIDER_NAME, operation=SEARCH_OPERATION, units=1
            )
        except ApiBudgetExceededError as exc:
            logger.warning("ebay search not authorised for %r: %s", term, exc)
            return None, url

        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
            "Accept": "application/json",
        }
        try:
            response = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("ebay request failed for %r: %s", term, exc)
            return None, url

        if response.status_code == 429:
            logger.warning("ebay rate-limited the request for %r", term)
            return None, url
        if response.status_code >= 400:
            logger.warning("ebay answered %s for %r", response.status_code, term)
            return None, url

        try:
            total = int(response.json()["total"])
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("ebay answered an unexpected body for %r: %s", term, exc)
            return None, url
        return total, url

    def _access_token(self, client: httpx.Client) -> str:
        """El token de aplicación, pedido una vez por instancia.

        No hace falta usuario ni consentimiento: es el flujo de credenciales de
        cliente, y por eso este adaptador no necesita cuenta de vendedor.
        """
        if self._token is not None:
            return self._token
        self._meter.authorise(provider=PROVIDER_NAME, operation=TOKEN_OPERATION, units=1)
        response = client.post(
            f"{self._host}{TOKEN_PATH}",
            data={"grant_type": "client_credentials", "scope": OAUTH_SCOPE},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(self._client_id, self._client_secret),
        )
        response.raise_for_status()
        self._token = str(response.json()["access_token"])
        return self._token

    def _signal_for(
        self,
        term: str,
        total: int,
        market: str,
        marketplace: str,
        url: str,
        observed_at: datetime.datetime,
    ) -> Signal | None:
        if total <= 0:
            # Medido y vacío. Se distingue de «no medido» en el log y tampoco se
            # convierte en señal: un cero aquí diría más de lo que sabemos.
            logger.info("ebay reports no listings at all for %r in %s", term, marketplace)
            return None
        return Signal(
            kind=SignalKind.COMPETITION,
            value=round(normalise_listings(total), 4),
            confidence=confidence_for(total),
            provider=PROVIDER_NAME,
            source=SOURCE,
            query=term,
            market=market,
            observed_at=observed_at,
            method=_COMPETITION_METHOD.format(marketplace=marketplace),
            raw_reference=url,
            basis=SignalBasis.MEASURED,
            # Competencia **de este canal**. Sin esto, el número podría leerse
            # como competencia de una web propia, que es otra magnitud.
            channel=CHANNEL,
            # Un recuento no es una serie. Vacío no significa cero observaciones:
            # significa que esta señal no se mide así (Milestone 35).
            observations=[],
        )
