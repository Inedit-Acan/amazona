"""Adaptador real #1: interés medido con la API de Wikimedia Pageviews.

**Qué es y qué no es.** Esto mide cuánta gente consultó un artículo de una
enciclopedia. Es un **proxy de interés**: nunca demanda de compra, nunca ventas,
nunca intención de gasto. Un pico de visitas a «Air fryer» dice que la gente
buscó qué es una freidora de aire, no que la comprara. Cada señal que sale de
aquí lo lleva escrito en su `method`, porque el número viaja lejos del sitio
donde se produjo y quien lo lea después tiene que poder saber qué tiene entre
manos.

Por qué esta fuente como primera real: es pública, documentada, sin clave, sin
coste, sin límite práctico y con historia mensual por proyecto lingüístico, así
que se puede probar de verdad —hoy, aquí— en vez de quedar pendiente de dar de
alta unas credenciales. Sus límites son igual de claros: los términos de nicho
tienen volúmenes bajos, y una enciclopedia no es un marketplace.

Qué **no** hace, nunca: inventar. Si la API no responde, si el artículo no
existe o si el cuerpo no es el que se espera, no hay señal para ese término —no
un cero, que se leería como «no hay demanda» cuando lo cierto es «no lo sabemos».
"""

import datetime
import logging
import math
from urllib.parse import quote

import httpx

from app.integrations.ports import (
    CandidateSignals,
    Observation,
    ProductSignalProvider,
    Signal,
    SignalKind,
)
from app.integrations.product_intelligence.terms import terms_for

logger = logging.getLogger(__name__)

PROVIDER_NAME = "wikimedia-pageviews"
SOURCE = "wikimedia.org/api/rest_v1/metrics/pageviews"
BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

#: Wikimedia pide identificarse. Una petición anónima es la que acaba bloqueada,
#: y con razón.
USER_AGENT = "AMAZONA/0.1 (https://github.com/Inedit-Acan/amazona)"

#: Qué proyecto lingüístico representa cada mercado. Es una aproximación y se
#: dice: `eu` no es un idioma, y el inglés es la lengua franca del catálogo.
PROJECT_FOR_MARKET: dict[str, str] = {
    "us": "en.wikipedia",
    "uk": "en.wikipedia",
    "eu": "en.wikipedia",
    "es": "es.wikipedia",
    "mx": "es.wikipedia",
    "de": "de.wikipedia",
    "fr": "fr.wikipedia",
}
DEFAULT_PROJECT = "en.wikipedia"

#: Visitas mensuales que se consideran el techo de la escala (valor 1,0). Es una
#: constante de normalización declarada, no una medida: sube y baja el número
#: sin cambiar el orden entre candidatos, y por eso va escrita en el `method`.
VIEWS_CEILING = 1_000_000

#: Cuánta historia se pide. Doce meses dan estacionalidad completa y permiten
#: comparar el último trimestre con el anterior.
DEFAULT_MONTHS = 12

#: Tope de peticiones por llamada a `discover`. La investigación corre dentro de
#: un trabajo con arriendo de 60 s (ADR 0009): sin tope, una categoría con
#: muchos términos se acercaría al arriendo y el segador la daría por muerta.
DEFAULT_MAX_REQUESTS = 8

DEFAULT_TIMEOUT_SECONDS = 6.0

_DEMAND_METHOD = (
    f"monthly Wikipedia pageviews over the last {{months}} months, summed and log-normalised "
    f"against a declared ceiling of {VIEWS_CEILING:,} views/month. "
    "PROXY FOR INTEREST — not purchase demand, not sales, not intent to spend."
)
_OUTLOOK_METHOD = (
    "ratio of the last 3 months of Wikipedia pageviews against the 3 before them, "
    "clamped to 0-1 around parity. PROXY FOR TRAJECTORY of public interest — not a sales forecast."
)


def _period_of(timestamp: str) -> str:
    """`2026080100` → `2026-08`. La etiqueta del mes tal y como la fuente lo
    expresa, sin convertir a nada."""
    return f"{timestamp[:4]}-{timestamp[4:6]}"


def _month_range(months: int, today: datetime.date) -> tuple[str, str]:
    """Ventana cerrada: hasta el final del mes pasado. El mes en curso está a
    medias y compararlo con meses completos inventaría una caída."""
    first_of_this_month = today.replace(day=1)
    end = first_of_this_month - datetime.timedelta(days=1)
    # `months` meses completos contando el último: restar `months - 1` deja la
    # ventana exacta, y restar `months` daría uno de más.
    start_year, start_month = divmod((end.year * 12 + end.month - 1) - (months - 1), 12)
    start = datetime.date(start_year, start_month + 1, 1)
    return start.strftime("%Y%m%d00"), end.strftime("%Y%m%d00")


def normalise_views(total_views: int) -> float:
    """Visitas totales → 0-1 en escala logarítmica.

    Logarítmica porque el interés se reparte por órdenes de magnitud: entre 100
    y 1.000 visitas hay la misma distancia informativa que entre 10.000 y
    100.000, y una escala lineal aplastaría todo lo que no sea un fenómeno de
    masas contra el cero.
    """
    if total_views <= 0:
        return 0.0
    return min(1.0, math.log10(1 + total_views) / math.log10(1 + VIEWS_CEILING))


def confidence_for(total_views: int, points: int) -> float:
    """Cuánto fiarse de este número concreto.

    Sube con el volumen y con la cantidad de meses observados, y **nunca llega
    a 1**: por bien medido que esté, sigue siendo un proxy de otra cosa.
    """
    if total_views <= 0 or points == 0:
        return 0.0
    volume = min(1.0, math.log10(1 + total_views) / 5)
    coverage = min(1.0, points / DEFAULT_MONTHS)
    return round(min(0.75, 0.2 + 0.55 * volume * coverage), 4)


def outlook_from(series: list[int]) -> float | None:
    """Trayectoria: últimos tres meses contra los tres anteriores. `None` si no
    hay seis meses — con menos, cualquier número sería una opinión."""
    if len(series) < 6:
        return None
    recent = sum(series[-3:])
    previous = sum(series[-6:-3])
    if previous <= 0:
        return None if recent <= 0 else 1.0
    ratio = recent / previous
    # Paridad (ratio 1) = 0,5. El doble o más = 1. La mitad o menos = 0.
    return round(max(0.0, min(1.0, 0.5 + (ratio - 1.0) / 2.0)), 4)


class WikimediaPageviewsProvider(ProductSignalProvider):
    """Interés real por término y mercado. Solo sabe de dos de las cinco
    señales, y lo declara: competencia, riesgo regulatorio y escalabilidad no
    se pueden deducir de unas visitas, así que no se deducen."""

    name = PROVIDER_NAME

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        months: int = DEFAULT_MONTHS,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        today: datetime.date | None = None,
    ) -> None:
        self._client = client
        self._months = months
        self._max_requests = max_requests
        self._timeout = timeout
        self._today = today

    def supports(self) -> frozenset[SignalKind]:
        return frozenset({SignalKind.DEMAND, SignalKind.FUTURE_OUTLOOK})

    def discover(
        self, *, category: str, keywords: list[str], market: str, max_results: int
    ) -> list[CandidateSignals]:
        terms = terms_for(category, keywords, limit=min(max_results, self._max_requests))
        if not terms:
            # No hay nada que preguntar. No es lo mismo que no haber encontrado
            # nada, y por eso no se devuelve un candidato vacío.
            return []

        project = PROJECT_FOR_MARKET.get(market, DEFAULT_PROJECT)
        start, end = _month_range(self._months, self._today or datetime.date.today())
        observed_at = datetime.datetime.now(datetime.UTC)

        candidates: list[CandidateSignals] = []
        client = self._client or httpx.Client(timeout=self._timeout, headers={"User-Agent": USER_AGENT})
        try:
            for term in terms:
                series, url = self._series_for(client, project, term, start, end)
                if series is None:
                    continue
                signals = self._signals_for(term, series, market, url, observed_at)
                if signals:
                    candidates.append(
                        CandidateSignals(name=term, category=category, signals=signals, rationale=None)
                    )
        finally:
            if self._client is None:
                client.close()
        return candidates

    # --- Una consulta ------------------------------------------------------

    def _series_for(
        self, client: httpx.Client, project: str, term: str, start: str, end: str
    ) -> tuple[list[tuple[str, int]] | None, str]:
        """La serie mensual de un término, o `None` si no se pudo saber.

        Todos los caminos de fallo acaban igual a propósito: sin dato. Un
        artículo que no existe, una API caída, un límite de ritmo y un cuerpo
        inesperado significan cosas distintas para quien opera —y se registran
        distinto en el log— pero ninguno significa «cero interés».
        """
        article = quote(term.replace(" ", "_"), safe="")
        url = f"{BASE_URL}/{project}/all-access/user/{article}/monthly/{start}/{end}"
        try:
            response = client.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as exc:
            logger.warning("wikimedia request failed for %r: %s", term, exc)
            return None, url

        if response.status_code == 404:
            logger.info("wikimedia has no article for %r in %s", term, project)
            return None, url
        if response.status_code == 429:
            logger.warning("wikimedia rate-limited the request for %r", term)
            return None, url
        if response.status_code >= 400:
            logger.warning("wikimedia answered %s for %r", response.status_code, term)
            return None, url

        try:
            items = response.json()["items"]
            # Mes y visitas, no solo visitas: la serie es la evidencia de la
            # señal y se persiste con ella (Milestone 35).
            series = [(_period_of(item["timestamp"]), int(item["views"])) for item in items]
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("wikimedia answered an unexpected body for %r: %s", term, exc)
            return None, url

        return (series or None), url

    def _signals_for(
        self,
        term: str,
        series: list[tuple[str, int]],
        market: str,
        url: str,
        observed_at: datetime.datetime,
    ) -> list[Signal]:
        views = [value for _period, value in series]
        observations = [Observation(period=period, value=float(value)) for period, value in series]
        total = sum(views)
        if total <= 0:
            # Medido y vacío. Se distingue de «no medido» en el log, pero
            # tampoco se convierte en una señal: un cero aquí diría más de lo
            # que sabemos.
            logger.info("wikimedia reports no views at all for %r", term)
            return []

        signals = [
            Signal(
                kind=SignalKind.DEMAND,
                value=round(normalise_views(total), 4),
                confidence=confidence_for(total, len(series)),
                provider=PROVIDER_NAME,
                source=SOURCE,
                query=term,
                market=market,
                observed_at=observed_at,
                method=_DEMAND_METHOD.format(months=self._months),
                raw_reference=url,
                simulated=False,
                observations=observations,
            )
        ]

        outlook = outlook_from(views)
        if outlook is not None:
            signals.append(
                Signal(
                    kind=SignalKind.FUTURE_OUTLOOK,
                    value=outlook,
                    confidence=confidence_for(total, len(series)),
                    provider=PROVIDER_NAME,
                    source=SOURCE,
                    query=term,
                    market=market,
                    observed_at=observed_at,
                    method=_OUTLOOK_METHOD,
                    raw_reference=url,
                    simulated=False,
                    observations=observations,
                )
            )
        return signals
