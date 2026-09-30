"""Adaptador real de Derecho nacional: legislación consolidada del BOE
(Milestone 43, ADR 0021).

**Qué hace.** Dado el identificador de una norma española que **una persona ha
declarado** como transposición de una directiva, pide a la API de datos abiertos de
la AEBOE sus metadatos y su análisis (las relaciones con otras normas) y, como
comprobación auxiliar, el sumario del diario oficial del día de su publicación.

**Qué no hace, nunca.** No busca normas (no usa el endpoint de lista), no dice a qué
producto se aplica una norma ni qué directiva traspone «por sí misma», no trae el
texto de los artículos ni el ELI completo, y no interpreta un 404 como «la norma no
existe»: significa *no consolidada o inexistente*, y la fuente no distingue.

## Condiciones de la fuente (aviso legal de la AEBOE, leído el 29-09-2026)

- Reutilización libre, comercial y no comercial, incluida la transformación, con
  cita («Basado en datos de la Agencia Estatal Boletín Oficial del Estado»).
- La legislación consolidada y su análisis son **meramente informativos**; solo el
  diario oficial es auténtico (desde 2009).
- **Sin alta, sin credenciales y sin cuota publicada.** La AEBOE puede suspender el
  acceso sin aviso. Si dejara de ser anónimo, el adaptador se retira y no se
  sustituye por una vía con alta.

## Privacidad

El `User-Agent` es un identificador técnico neutro del proyecto. **Nunca** lleva un
nombre, un correo ni ningún dato personal.

## Todo o nada

Metadatos y análisis son el núcleo: si cualquiera falla, no hay observación. El
sumario es una comprobación **auxiliar**: si falla, la observación se devuelve con
`check_failed`, que **no** es una conclusión negativa; solo un sumario leído bien que
no lista la norma da `absent_from_summary`.
"""

import datetime
import re

import httpx

from app.core.errors import AmazonaError
from app.costs.service import ApiBudgetExceededError, CallMeter, UnmeteredCalls
from app.integrations.ports import NationalNormRecord, NationalNormSource, PublicationCheck
from app.legal.national import PROVIDER_NAME, official_url, validate_national_id

BASE = "https://www.boe.es/datosabiertos/api"
CONSOLIDATED = f"{BASE}/legislacion-consolidada/id"
SUMMARY = f"{BASE}/boe/sumario"
#: Identificador técnico neutro del proyecto: sin nombre, sin correo, sin contacto.
USER_AGENT = "KOVA-Regulatory-Client/0.1"
DEFAULT_TIMEOUT_SECONDS = 10.0
#: El sumario de un día pesa unos 120 KB. Un cuerpo mucho mayor no es lo esperado.
MAX_BODY_BYTES = 3_000_000
OP_METADATA = "consolidada/metadatos"
OP_ANALYSIS = "consolidada/analisis"
OP_SUMMARY = "boe/sumario"
#: Antes del 1 de enero de 2009 solo la edición en papel del BOE es oficial.
FIRST_OFFICIAL_ELECTRONIC_DATE = "20090101"


class NationalSourceUnavailableError(AmazonaError):
    """La fuente no contestó bien. **No es «no encontrada»**: no se pudo
    preguntar, y quien lo reciba no debe guardar nada como si la fuente hubiera
    hablado."""


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _parse_body(response: httpx.Response, what: str) -> object:
    if len(response.content) > MAX_BODY_BYTES:
        raise NationalSourceUnavailableError(f"the BOE {what} answer is far larger than expected")
    try:
        return response.json()
    except ValueError as exc:
        raise NationalSourceUnavailableError(f"the BOE {what} answer is not valid JSON") from exc


def _data(body: object, what: str) -> object:
    if not isinstance(body, dict) or "data" not in body:
        raise NationalSourceUnavailableError(f"the BOE {what} answer has an unexpected shape")
    return body["data"]


def parse_metadata(body: object, national_id: str) -> dict[str, object]:
    """Los metadatos, **verbatim**. Falla si la respuesta no es la norma pedida."""
    data = _data(body, "metadata")
    item = data[0] if isinstance(data, list) and data else data
    if not isinstance(item, dict) or item.get("identificador") != national_id:
        raise NationalSourceUnavailableError(
            "the BOE metadata answer does not describe the requested identifier"
        )
    if not isinstance(item.get("titulo"), str) or not item["titulo"].strip():
        raise NationalSourceUnavailableError("the BOE metadata answer carries no title")
    return dict(item)


def _relation(item: object) -> dict[str, object]:
    if not isinstance(item, dict) or not isinstance(item.get("id_norma"), str):
        raise NationalSourceUnavailableError("the BOE analysis carries an unexpected relation row")
    relation = item.get("relacion")
    code: int | None = None
    label = ""
    if isinstance(relation, dict):
        label = str(relation.get("texto") or "")
        try:
            code = int(str(relation.get("codigo")))
        except ValueError:
            code = None
    return {
        "id_norma": item["id_norma"],
        "relation_code": code,
        "relation": label,
        "text": str(item.get("texto") or ""),
    }


def parse_relations(body: object) -> dict[str, list[dict[str, object]]]:
    """Las relaciones del análisis, tal cual: forma normalizada, contenido intacto.

    Un análisis sin `referencias` es válido (los nodos son opcionales): da listas
    vacías. Una fila que no se entiende hace fallar la lectura entera.
    """
    data = _data(body, "analysis")
    analysis = data[0] if isinstance(data, list) and data else data
    if not isinstance(analysis, dict):
        raise NationalSourceUnavailableError("the BOE analysis answer has an unexpected shape")
    references = analysis.get("referencias")
    result: dict[str, list[dict[str, object]]] = {"previous": [], "next": []}
    if not isinstance(references, dict):
        return result
    for key, inner, target in (
        ("anteriores", "anterior", "previous"),
        ("posteriores", "posterior", "next"),
    ):
        for block in _as_list(references.get(key)):
            if not isinstance(block, dict):
                raise NationalSourceUnavailableError("the BOE analysis carries an unexpected block")
            result[target].extend(_relation(item) for item in _as_list(block.get(inner)))
    return result


def _lists_identifier(node: object, national_id: str) -> bool:
    """Si algún nodo del sumario tiene ese `identificador`. Recorrido iterativo."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if current.get("identificador") == national_id:
                return True
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return False


class BoeConsolidatedSource(NationalNormSource):
    """Ancla normas contra el BOE. El cliente HTTP y el contador se inyectan, igual
    que en los demás adaptadores: sin ellos no hay forma de probarlo sin red ni de
    contar la llamada."""

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

    def lookup(self, national_id: str) -> NationalNormRecord:
        nid = validate_national_id(national_id)
        retrieved_at = self._now or datetime.datetime.now(datetime.UTC)
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            return self._lookup(client, nid, retrieved_at)
        finally:
            if self._client is None:
                client.close()

    def _lookup(
        self, client: httpx.Client, nid: str, retrieved_at: datetime.datetime
    ) -> NationalNormRecord:
        metadata_url = f"{CONSOLIDATED}/{nid}/metadatos"
        response = self._get(client, metadata_url, OP_METADATA, accept={200, 404})
        if response.status_code == 404:
            return NationalNormRecord(
                provider=PROVIDER_NAME,
                national_id=nid,
                retrieved_at=retrieved_at,
                consolidated=False,
                publication=PublicationCheck(
                    "not_checked", "no consolidated metadata, so no publication date"
                ),
                source_urls=(metadata_url,),
            )
        metadata = parse_metadata(_parse_body(response, "metadata"), nid)

        analysis_url = f"{CONSOLIDATED}/{nid}/analisis"
        analysis = self._get(client, analysis_url, OP_ANALYSIS, accept={200})
        relations = parse_relations(_parse_body(analysis, "analysis"))

        publication = self._check_publication(client, nid, metadata)
        urls: tuple[str, ...] = (metadata_url, analysis_url)
        if publication.state in ("confirmed", "absent_from_summary"):
            urls += (f"{SUMMARY}/{metadata['fecha_publicacion']}",)
        return NationalNormRecord(
            provider=PROVIDER_NAME,
            national_id=nid,
            retrieved_at=retrieved_at,
            consolidated=True,
            metadata=metadata,
            relations=relations,
            publication=publication,
            source_urls=urls,
        )

    def _get(
        self, client: httpx.Client, url: str, operation: str, *, accept: set[int]
    ) -> httpx.Response:
        # Autorizar **antes** de salir: una denegación por cuota o por falta de
        # límite autorizado deja su fila y no llega a la red.
        self._meter.authorise(provider=PROVIDER_NAME, operation=operation, units=1)
        try:
            response = client.get(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise NationalSourceUnavailableError(f"the BOE did not answer: {exc}") from exc
        if response.status_code not in accept:
            raise NationalSourceUnavailableError(f"the BOE answered HTTP {response.status_code}")
        return response

    def _check_publication(
        self, client: httpx.Client, nid: str, metadata: dict[str, object]
    ) -> PublicationCheck:
        """Comprobación auxiliar. **Nunca lanza**: un fallo es `check_failed`."""
        url = official_url(nid)
        raw = metadata.get("fecha_publicacion")
        if not isinstance(raw, str) or not re.fullmatch(r"\d{8}", raw):
            return PublicationCheck("not_checked", "the metadata carry no publication date", url)
        try:
            datetime.datetime.strptime(raw, "%Y%m%d")
        except ValueError:
            return PublicationCheck("not_checked", "the publication date is not a valid date", url)
        if raw < FIRST_OFFICIAL_ELECTRONIC_DATE:
            return PublicationCheck(
                "not_checked",
                "published before 2009-01-01: only the paper edition is official",
                url,
            )
        try:
            response = self._get(client, f"{SUMMARY}/{raw}", OP_SUMMARY, accept={200})
            found = _lists_identifier(_parse_body(response, "summary"), nid)
        except (NationalSourceUnavailableError, ApiBudgetExceededError) as exc:
            return PublicationCheck("check_failed", str(exc), url)
        if found:
            return PublicationCheck("confirmed", f"listed in the BOE summary of {raw}", url)
        return PublicationCheck(
            "absent_from_summary", f"the BOE summary of {raw} does not list it", url
        )
