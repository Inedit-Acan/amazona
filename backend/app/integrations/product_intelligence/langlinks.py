"""Cómo se llama el mismo producto en otro idioma, **según la fuente**.

El Milestone 36 dejó escrito y medido el límite que este módulo cierra: aliasar
«Freidora de aire» a «Air fryer» a mano habría cambiado una medición que funciona
por un 404, porque `es.wikipedia` no tiene artículo «Air fryer» (HTTP 404) y sí
tiene «Freidora de aire» (12.099 visitas en doce meses). Resolver idiomas no
necesita un nombre canónico único: necesita **un nombre por mercado**.

Y aquella ADR nombró el mecanismo honesto: los *langlinks* de Wikimedia dan la
equivalencia entre artículos de distintos idiomas **desde una fuente**, no desde
una suposición nuestra.

## Por qué esto no rompe la regla de la ADR 0014

La identidad se resuelve «de forma determinista o declarada, nunca por parecido».
Un langlink es **declarado**: lo declara Wikimedia, no lo deduce este código de que
dos cadenas se parezcan. Cambia quién firma la declaración —una fuente externa en
vez de un catálogo nuestro— y por eso cada equivalencia se guarda con su
procedencia: el proyecto de origen, el de destino y la URL de la consulta.

Lo que **no** hace: inventar. Si no hay langlink, no hay equivalencia. Ni se
traduce, ni se transcribe, ni se busca el artículo más parecido — eso sería
exactamente la resolución por similitud que la ADR 0014 prohíbe.

## Es la API de acciones, no la REST

Las visitas vienen de `wikimedia.org/api/rest_v1`; los langlinks de la API de
acciones de cada proyecto (`es.wikipedia.org/w/api.php`). Son dos superficies con
la misma casa detrás, y por eso el contador de coste las cuenta como proveedores
distintos: una cuota agotada en una no dice nada de la otra.
"""

import logging

import httpx

from app.costs.service import ApiBudgetExceededError, CallMeter, UnmeteredCalls

logger = logging.getLogger(__name__)

PROVIDER_NAME = "wikimedia-langlinks"
OPERATION = "query/langlinks"

#: Wikimedia pide identificarse. Una petición anónima es la que acaba bloqueada.
USER_AGENT = "AMAZONA/0.1 (https://github.com/Inedit-Acan/amazona)"

DEFAULT_TIMEOUT_SECONDS = 6.0

#: Cómo se resuelve el nombre en cada mercado: `market` → (proyecto, código de
#: idioma del langlink). Es el espejo de `PROJECT_FOR_MARKET` del adaptador de
#: visitas, y se mantiene aparte a propósito: si algún día un mercado cambia de
#: proyecto, cambia en un sitio y no en dos.
LANGUAGE_FOR_MARKET: dict[str, str] = {
    "us": "en",
    "uk": "en",
    "eu": "en",
    "es": "es",
    "mx": "es",
    "de": "de",
    "fr": "fr",
    "it": "it",
}


def api_url(project: str) -> str:
    return f"https://{project}.org/w/api.php"


class LanglinkResolver:
    """Pregunta a Wikimedia cómo se llama un artículo en otro idioma.

    Sin caché entre instancias y con caché dentro de una: una investigación
    pregunta por los mismos términos varias veces y no tiene sentido gastar cuota
    en repetirlo. Persistir la equivalencia es trabajo de quien la use — se guarda
    como alias con su procedencia (Milestone 36), no en un caché escondido aquí.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        meter: CallMeter | None = None,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._meter = meter or UnmeteredCalls()
        self._seen: dict[tuple[str, str, str], tuple[str, str] | None] = {}

    def title_in(
        self, *, title: str, source_project: str, language: str
    ) -> tuple[str, str] | None:
        """El título equivalente y la URL de donde salió, o `None`.

        `None` significa **que la fuente no declara equivalencia**, no que no
        exista: puede que el artículo no esté traducido, o que el título de partida
        no exista. Las dos cosas se distinguen en el log y ninguna se rellena.
        """
        key = (title, source_project, language)
        if key in self._seen:
            return self._seen[key]
        resolved = self._ask(title=title, source_project=source_project, language=language)
        self._seen[key] = resolved
        return resolved

    def _ask(
        self, *, title: str, source_project: str, language: str
    ) -> tuple[str, str] | None:
        url = api_url(source_project)
        params = {
            "action": "query",
            "prop": "langlinks",
            "titles": title,
            "lllang": language,
            "format": "json",
            "formatversion": "2",
        }
        try:
            self._meter.authorise(provider=PROVIDER_NAME, operation=OPERATION, units=1)
        except ApiBudgetExceededError as exc:
            logger.warning("langlinks not authorised for %r: %s", title, exc)
            return None

        client = self._client or httpx.Client(
            timeout=self._timeout, headers={"User-Agent": USER_AGENT}
        )
        try:
            response = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            logger.warning("langlinks request failed for %r: %s", title, exc)
            return None
        finally:
            if self._client is None:
                client.close()

        if response.status_code >= 400:
            logger.warning("langlinks answered %s for %r", response.status_code, title)
            return None

        # La lectura entera va dentro del try, no solo el acceso a las claves: una
        # respuesta con la forma equivocada —`pages` como cadena, un langlink que no
        # es un diccionario— tiene que acabar en ausencia como cualquier otro fallo,
        # no en una excepción a mitad del bucle.
        try:
            pages = response.json()["query"]["pages"]
            for page in pages:
                if page.get("missing"):
                    logger.info("langlinks: %r does not exist in %s", title, source_project)
                    continue
                for link in page.get("langlinks") or []:
                    if link.get("lang") == language and link.get("title"):
                        return str(link["title"]), str(response.request.url)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning("langlinks answered an unexpected body for %r: %s", title, exc)
            return None

        logger.info("langlinks: %r has no %s equivalent declared", title, language)
        return None
