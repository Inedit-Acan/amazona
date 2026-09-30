"""Adaptador real de tipos de cambio: las referencias del euro del BCE
(Milestone 42, ADR 0020).

**Qué hace.** Descarga el fichero XML público que el BCE publica cada día laborable
TARGET y lo devuelve como observaciones con su fecha. Nada más.

**Qué no hace, nunca.** No decide qué monedas admite el sistema (eso es el
catálogo, y lo aplica el servicio). No calcula cruces. No corrige la fecha de una
tasa. No rellena un día sin publicación. No adivina «sin cambios» si la fuente no
contesta o contesta algo raro: falla, y quien lo llama no guarda nada.

## Fuente y términos (leídos el 29-09-2026)

- Fichero diario: `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`.
- Histórico de 90 días: `…/eurofxref-hist-90d.xml`. **Solo para recuperación
  explícita**, nunca como respaldo automático de un fallo del diario.
- Sin alta ni credenciales. Los términos de uso están en el aviso legal del BCE
  (`…/services/using-our-site/disclaimer/`): uso libre citando la fuente y
  diciendo si se modifica. El propio BCE advierte de que son referencias
  informativas, no para transacciones.
- No se usa la API SDMX del Data Portal: no se han verificado sus términos.

## Dos estilos de comillas

El fichero diario entrega los atributos con comillas simples y el de 90 días con
dobles. Se lee con un parser XML, no con expresiones regulares.
"""

import datetime
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

import httpx

from app.core.errors import AmazonaError
from app.costs.service import CallMeter, UnmeteredCalls
from app.integrations.ports import ExchangeRateFeed, ReferenceRateSet
from app.money.ecb import PROVIDER_NAME

DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
USER_AGENT = "AMAZONA/0.1 (https://github.com/Inedit-Acan/amazona; ECB reference rates refresh)"
DEFAULT_TIMEOUT_SECONDS = 10.0
#: El histórico de 90 días pesa unos 70 KB. Un cuerpo mucho mayor no es lo que
#: esperamos, y no se parsea.
MAX_BODY_BYTES = 1_000_000
BASE_CURRENCY = "EUR"
OP_DAILY = "eurofxref-daily"
OP_HISTORY = "eurofxref-hist-90d"


class FeedUnavailableError(AmazonaError):
    """La fuente no contestó bien o contestó algo que no se entiende.

    **No es «sin cambios»** ni «no hay tasas»: no se pudo leer, y quien lo reciba
    no debe guardar nada ni borrar lo que ya tenía.
    """


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_reference_xml(text: str, *, source_url: str, retrieved_at: datetime.datetime) -> list[ReferenceRateSet]:
    """Interpreta el XML del BCE (diario o histórico) y **valida todo** antes de
    devolver nada: un día a medias no existe.

    Devuelve los días de más reciente a más antiguo. Falla con
    `FeedUnavailableError` ante XML malformado, sin días, un día sin monedas, una
    fecha o una tasa ilegible, una tasa no positiva o una moneda repetida.
    """
    # Un documento con DTD o entidades no es lo que publica el BCE, y un parser
    # estándar no debe expandirlas.
    upper = text[:4096].upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise FeedUnavailableError("the ECB feed carries a DTD or entities, which it never does")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FeedUnavailableError(f"the ECB feed is not well-formed XML: {exc}") from exc

    sets: list[ReferenceRateSet] = []
    seen_dates: set[datetime.date] = set()
    for node in root.iter():
        if _local(node.tag) != "Cube" or "time" not in node.attrib:
            continue
        try:
            published_on = datetime.date.fromisoformat(node.attrib["time"])
        except ValueError as exc:
            raise FeedUnavailableError(f"unreadable date in the ECB feed: {node.attrib['time']!r}") from exc
        if published_on in seen_dates:
            raise FeedUnavailableError(f"the ECB feed lists {published_on} twice")
        seen_dates.add(published_on)

        rates: dict[str, Decimal] = {}
        for child in node:
            if _local(child.tag) != "Cube":
                continue
            code = child.attrib.get("currency", "")
            raw = child.attrib.get("rate", "")
            if len(code) != 3 or not code.isalpha() or not code.isupper():
                raise FeedUnavailableError(f"unreadable currency code in the ECB feed: {code!r}")
            if code in rates:
                raise FeedUnavailableError(f"the ECB feed lists {code} twice on {published_on}")
            try:
                value = Decimal(raw)
            except InvalidOperation as exc:
                raise FeedUnavailableError(f"unreadable {code} rate on {published_on}: {raw!r}") from exc
            if not value.is_finite() or value <= 0:
                raise FeedUnavailableError(f"the {code} rate on {published_on} is not positive: {raw!r}")
            rates[code] = value
        if not rates:
            raise FeedUnavailableError(f"the ECB feed has no rates for {published_on}")
        sets.append(
            ReferenceRateSet(
                provider=PROVIDER_NAME,
                published_on=published_on,
                base=BASE_CURRENCY,
                rates=rates,
                retrieved_at=retrieved_at,
                source_url=source_url,
            )
        )

    if not sets:
        raise FeedUnavailableError("the ECB feed has no dated rates")
    return sorted(sets, key=lambda item: item.published_on, reverse=True)


class EcbReferenceRateFeed(ExchangeRateFeed):
    """Descarga el fichero del BCE. El cliente HTTP y el contador se inyectan,
    igual que en los demás adaptadores: sin ellos no hay forma de probarlo sin red
    ni de contar la llamada."""

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

    def fetch_daily(self) -> ReferenceRateSet:
        sets = self._fetch(DAILY_URL, OP_DAILY)
        if len(sets) != 1:
            raise FeedUnavailableError(
                f"the ECB daily feed should carry one day and carries {len(sets)}"
            )
        return sets[0]

    def fetch_history(self) -> list[ReferenceRateSet]:
        return self._fetch(HISTORY_URL, OP_HISTORY)

    def _fetch(self, url: str, operation: str) -> list[ReferenceRateSet]:
        # Autorizar **antes** de salir: una denegación por cuota o por falta de
        # límite autorizado deja su fila y no llega a la red.
        self._meter.authorise(provider=PROVIDER_NAME, operation=operation, units=1)

        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            response = client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            raise FeedUnavailableError(f"the ECB did not answer: {exc}") from exc
        finally:
            if self._client is None:
                client.close()

        if response.status_code != 200:
            raise FeedUnavailableError(f"the ECB answered HTTP {response.status_code}")
        body = response.content
        if len(body) > MAX_BODY_BYTES:
            raise FeedUnavailableError("the ECB feed is far larger than expected; not parsed")
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FeedUnavailableError("the ECB feed is not UTF-8") from exc

        retrieved_at = self._now or datetime.datetime.now(datetime.UTC)
        return parse_reference_xml(text, source_url=url, retrieved_at=retrieved_at)
