"""Adaptador real de normativa: EUR-Lex, a través del repositorio Cellar
(Milestone 41, ADR 0019).

**Qué hace.** Dado el número CELEX de una norma que **una persona ha declarado**,
pregunta a Cellar —el repositorio que hay detrás de EUR-Lex— si existe, si está en
vigor y con qué fechas. Nada más.

**Qué no hace, nunca.** No dice a qué productos se aplica una norma: ninguna fuente
pública lo dice, y deducirlo sería un juicio jurídico disfrazado de dato. No trae
el texto de los artículos. No busca normas por tema. No traduce. Si Cellar no
responde, no hay ancla — no un «vigente por defecto».

## Por qué Cellar y no el «webservice» de EUR-Lex

El «webservice» y el volcado masivo de EUR-Lex **exigen cuenta EU Login**: es un
alta, y este proyecto no da de alta nada. El punto de acceso SPARQL de Cellar y su
API REST se consultan sin registro (comprobado el 2026-09-29 con consultas
anónimas). Si esto cambiara, el adaptador debe dejar de usarse y no sustituirse
por otra vía con alta.

## Derechos

Los metadatos de EUR-Lex son CC0 (aviso legal de EUR-Lex, verificado el
2026-09-29). Aquí solo se guardan metadatos, ninguna traducción ni texto.

## Las fechas se entregan tal cual

Para la Directiva 2014/35 la fuente devuelve **dos** fechas de entrada en vigor, y
el fin de validez `9999-12-31`. Este adaptador conserva las dos y el valor bruto:
elegir una fecha, o decidir que `9999-12-31` significa «sin fin», sería atribuirle
un significado jurídico que la fuente no documenta.
"""

import datetime
import re
from urllib.parse import urlencode

import httpx

from app.core.errors import AmazonaError, ValidationError
from app.costs.service import CallMeter, UnmeteredCalls
from app.integrations.ports import RegulatoryAnchorSource, SourceAnchor

PROVIDER_NAME = "eur-lex-cellar"
OPERATION = "sparql/celex-lookup"
ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
USER_AGENT = "AMAZONA/0.1 (https://github.com/Inedit-Acan/amazona; regulatory anchor lookup)"
#: Corto a propósito: en la prueba de humo del 29-09-2026 Cellar tardó más de 20 s
#: en responder a dos de tres consultas y dio un 504 en la tercera, y un análisis
#: corre dentro de un trabajo con arriendo de 60 s (ADR 0009).
DEFAULT_TIMEOUT_SECONDS = 10.0

#: Solo actos legislativos del sector 3 (`3` + año + letra + número), que es lo
#: que EUR-Lex identifica como derecho derivado. Se valida **antes** de
#: interpolarlo en la consulta: un identificador que no encaja no llega a Cellar.
CELEX_PATTERN = re.compile(r"^3\d{4}[A-Z]\d{4}$")

_CDM = "http://publications.europa.eu/ontology/cdm#"
_PROPERTIES = (
    "resource_legal_in-force",
    "resource_legal_date_entry-into-force",
    "resource_legal_date_end-of-validity",
    "resource_legal_eli",
    "work_date_document",
    "work_has_resource-type",
)


class AnchorUnavailableError(AmazonaError):
    """La fuente no contestó bien. **No es «no encontrado»**: no se pudo
    preguntar, y quien lo reciba no debe guardar nada como si la fuente hubiera
    hablado."""


def validate_celex(celex: str) -> str:
    cleaned = celex.strip().upper()
    if not CELEX_PATTERN.fullmatch(cleaned):
        raise ValidationError(
            f"{celex!r} is not a CELEX number of a legislative act (expected like 32014L0035)"
        )
    return cleaned


def _query(celex: str) -> str:
    values = " ".join(f"cdm:{name}" for name in _PROPERTIES)
    return (
        f"PREFIX cdm: <{_CDM}>\n"
        "SELECT ?p ?o WHERE {\n"
        f'  ?w cdm:resource_legal_id_celex "{celex}"^^<http://www.w3.org/2001/XMLSchema#string> .\n'
        f"  VALUES ?p {{ {values} }}\n"
        "  ?w ?p ?o .\n"
        "}"
    )


def _in_force(values: list[str]) -> bool | None:
    """`1`/`true` y `0`/`false`. Cualquier otra cosa es que la fuente no lo dijo."""
    if len(values) != 1:
        return None
    value = values[0].strip().lower()
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    return None


class EurLexCellarSource(RegulatoryAnchorSource):
    """Ancla normas contra Cellar. El cliente HTTP y el contador se inyectan, igual
    que en los adaptadores de Product Intelligence: sin ellos no hay forma de
    probarlo sin red ni de contar la llamada."""

    name = PROVIDER_NAME

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        meter: CallMeter | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        now: datetime.datetime | None = None,
    ) -> None:
        self._client = client
        self._meter = meter or UnmeteredCalls()
        self._timeout = timeout
        self._now = now

    def lookup(self, celex: str) -> SourceAnchor:
        celex = validate_celex(celex)
        params = {"query": _query(celex), "format": "application/sparql-results+json"}
        url = f"{ENDPOINT}?{urlencode(params)}"

        # Autorizar **antes** de salir: una denegación por cuota o por falta de
        # límite autorizado deja su fila y no llega a la red.
        self._meter.authorise(provider=PROVIDER_NAME, operation=OPERATION, units=1)

        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            response = client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            raise AnchorUnavailableError(f"Cellar did not answer: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

        if response.status_code != 200:
            raise AnchorUnavailableError(f"Cellar answered HTTP {response.status_code}")
        try:
            bindings = response.json()["results"]["bindings"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AnchorUnavailableError("Cellar answered with an unexpected body") from exc

        raw: dict[str, list[str]] = {}
        for binding in bindings:
            try:
                prop = binding["p"]["value"].removeprefix(_CDM)
                raw.setdefault(prop, []).append(str(binding["o"]["value"]))
            except (KeyError, TypeError) as exc:
                raise AnchorUnavailableError("Cellar answered with an unexpected row") from exc

        retrieved_at = self._now or datetime.datetime.now(datetime.UTC)
        if not raw:
            return SourceAnchor(
                provider=PROVIDER_NAME, celex=celex, found=False, retrieved_at=retrieved_at,
                source_url=url,
            )

        type_uris = raw.get("work_has_resource-type") or []
        type_uri = type_uris[0] if type_uris else None
        end = raw.get("resource_legal_date_end-of-validity") or []
        eli = raw.get("resource_legal_eli") or []
        document_date = raw.get("work_date_document") or []
        return SourceAnchor(
            provider=PROVIDER_NAME,
            celex=celex,
            found=True,
            retrieved_at=retrieved_at,
            source_url=url,
            in_force=_in_force(raw.get("resource_legal_in-force", [])),
            act_type_code=type_uri.rsplit("/", 1)[-1] if type_uri else None,
            eli=eli[0] if eli else None,
            document_date=document_date[0] if document_date else None,
            entry_into_force=tuple(sorted(raw.get("resource_legal_date_entry-into-force", []))),
            end_of_validity=end[0] if len(end) == 1 else None,
            raw=raw,
        )
