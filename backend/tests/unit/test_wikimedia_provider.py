"""El adaptador real #1 (Milestone 34, ADR 0012).

Ninguna de estas pruebas sale a internet: el cliente HTTP se inyecta con
respuestas grabadas. Lo que se comprueba es lo que de verdad importa de un
adaptador —qué pregunta, cómo interpreta lo que le devuelven, y **qué hace
cuando no le devuelven nada**—. Esa última parte es la mitad del trabajo: un
adaptador que convierte un error de red en un cero convierte una avería en un
descubrimiento.

El recorrido contra la API de verdad está en el humo del milestone, no aquí: un
test que depende de la red es un test que falla por motivos que no son el código.
"""

import datetime
import json

import httpx
import pytest

from app.costs.service import ApiBudgetExceededError
from app.integrations.ports import SignalKind
from app.integrations.product_intelligence.wikimedia import (
    PROVIDER_NAME,
    VIEWS_CEILING,
    WikimediaPageviewsProvider,
    confidence_for,
    normalise_views,
    outlook_from,
)

TODAY = datetime.date(2026, 9, 26)


def series_body(views: list[int]) -> dict:
    return {
        "items": [
            {
                "project": "en.wikipedia",
                "article": "Air_fryer",
                "granularity": "monthly",
                "timestamp": f"2025{month:02d}0100",
                "access": "all-access",
                "agent": "user",
                "views": value,
            }
            for month, value in enumerate(views, start=1)
        ]
    }


def client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def always(status: int, body: dict | str | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body, request=request)
        return httpx.Response(status, json=body or {}, request=request)

    return handler


def provider(handler, **kwargs) -> WikimediaPageviewsProvider:
    return WikimediaPageviewsProvider(client_returning(handler), today=TODAY, **kwargs)


# --- Normalización, confianza y trayectoria --------------------------------


def test_views_are_normalised_on_a_logarithmic_scale():
    """Entre 100 y 1.000 visitas hay la misma distancia informativa que entre
    10.000 y 100.000; una escala lineal aplastaría todo contra el cero."""
    assert normalise_views(0) == 0.0
    assert normalise_views(VIEWS_CEILING) == pytest.approx(1.0, abs=0.001)
    assert 0.0 < normalise_views(100) < normalise_views(10_000) < normalise_views(1_000_000)
    # Y no se pasa de 1 por mucho que suba.
    assert normalise_views(VIEWS_CEILING * 50) == 1.0


def test_confidence_grows_with_volume_but_never_reaches_one():
    """Por bien medido que esté, sigue siendo un proxy de otra cosa."""
    assert confidence_for(0, 12) == 0.0
    assert confidence_for(50, 12) < confidence_for(50_000, 12)
    assert confidence_for(10_000_000, 12) <= 0.75


def test_fewer_months_observed_means_less_confidence():
    assert confidence_for(50_000, 3) < confidence_for(50_000, 12)


def test_the_trajectory_compares_the_last_quarter_with_the_previous_one():
    assert outlook_from([10, 10, 10, 10, 10, 10]) == 0.5  # paridad
    assert outlook_from([10, 10, 10, 20, 20, 20]) == 1.0  # el doble
    assert outlook_from([20, 20, 20, 10, 10, 10]) == 0.25  # la mitad


def test_without_six_months_there_is_no_trajectory():
    """Con menos historia, cualquier número sería una opinión."""
    assert outlook_from([10, 20, 30]) is None
    assert outlook_from([]) is None


# --- El camino feliz -------------------------------------------------------


def test_a_measured_term_becomes_a_real_demand_signal():
    adapter = provider(always(200, series_body([100, 120, 140, 160, 180, 200, 220, 240])))

    candidates = adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1)

    assert len(candidates) == 1
    demand = candidates[0].signal(SignalKind.DEMAND)
    assert demand is not None
    assert demand.simulated is False
    assert demand.provider == PROVIDER_NAME
    assert 0.0 < demand.value < 1.0
    assert demand.query == "Air fryer"
    assert demand.market == "us"


def test_the_method_says_it_is_a_proxy_and_not_sales():
    """El número viaja lejos de donde se produjo; tiene que llevar escrito qué
    es. Wikimedia mide interés, nunca demanda de compra."""
    adapter = provider(always(200, series_body([1000] * 12)))

    candidates = adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1)

    method = candidates[0].signal(SignalKind.DEMAND).method
    assert "PROXY FOR INTEREST" in method
    assert "not purchase demand" in method
    assert "not sales" in method


def test_the_raw_reference_is_the_url_that_was_called():
    adapter = provider(always(200, series_body([500] * 12)))

    candidates = adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1)

    reference = candidates[0].signal(SignalKind.DEMAND).raw_reference
    assert reference.startswith("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/")
    assert "Air_fryer" in reference


def test_a_growing_series_also_produces_a_trajectory_signal():
    adapter = provider(always(200, series_body([10, 10, 10, 10, 10, 10, 40, 40, 40])))

    candidates = adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1)

    outlook = candidates[0].signal(SignalKind.FUTURE_OUTLOOK)
    assert outlook is not None and outlook.value == 1.0
    assert "PROXY FOR TRAJECTORY" in outlook.method


def test_it_only_claims_the_two_signals_it_can_measure():
    """Competencia, riesgo regulatorio y escalabilidad no se deducen de unas
    visitas, así que no se deducen."""
    adapter = provider(always(200, series_body([100] * 12)))

    assert adapter.supports() == frozenset({SignalKind.DEMAND, SignalKind.FUTURE_OUTLOOK})
    candidates = adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1)
    assert candidates[0].signal(SignalKind.COMPETITION) is None


def test_the_market_picks_the_language_project():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    provider(handler).discover(category="home", keywords=["Air fryer"], market="mx", max_results=1)

    assert "es.wikipedia" in seen[0]


def test_an_unknown_market_falls_back_to_english_instead_of_failing():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    provider(handler).discover(category="home", keywords=["Air fryer"], market="jp", max_results=1)

    assert "en.wikipedia" in seen[0]


def test_it_identifies_itself_on_every_request():
    """Wikimedia pide identificarse, y una petición anónima es la que acaba
    bloqueada."""
    agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    provider(handler).discover(category="home", keywords=["Air fryer"], market="us", max_results=1)

    assert agents and agents[0].startswith("AMAZONA/")


def test_the_window_stops_at_the_end_of_last_month():
    """El mes en curso está a medias: compararlo con meses completos inventaría
    una caída."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    provider(handler, months=6).discover(
        category="home", keywords=["Air fryer"], market="us", max_results=1
    )

    # Seis meses completos terminando en agosto: de marzo a agosto de 2026.
    assert seen[0].endswith("/2026030100/2026083100")


# --- Cuando la fuente no responde lo que se espera -------------------------


@pytest.mark.parametrize(
    "handler",
    [
        always(404, {"detail": "not found"}),
        always(429, {"detail": "rate limited"}),
        always(500, {"detail": "boom"}),
        always(200, "not json at all"),
        always(200, {"unexpected": "shape"}),
        always(200, {"items": []}),
    ],
    ids=["404", "429", "500", "not-json", "wrong-shape", "empty-items"],
)
def test_no_answer_means_no_signal_never_a_zero(handler):
    """Un cero se leería como «no hay demanda». Lo cierto es «no lo sabemos», y
    eso se dice callando, no inventando."""
    adapter = provider(handler)

    candidates = adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1)

    assert candidates == []


def test_a_network_failure_is_survived_term_by_term():
    """Un término que falla no puede llevarse por delante a los demás."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "Air_fryer" in str(request.url):
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json=series_body([500] * 12), request=request)

    adapter = provider(handler)

    candidates = adapter.discover(
        category="home", keywords=["Air fryer", "Humidifier"], market="us", max_results=3
    )

    names = [c.name for c in candidates]
    assert "Air fryer" not in names
    assert "Humidifier" in names


def test_a_term_measured_at_zero_is_not_a_signal_either():
    adapter = provider(always(200, series_body([0] * 12)))

    assert adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1) == []


# --- Presupuesto de peticiones ---------------------------------------------


def test_it_never_makes_more_requests_than_its_budget():
    """La investigación corre dentro de un trabajo con arriendo de 60 s (ADR
    0009): sin tope, una categoría con muchos términos se acercaría al límite."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    provider(handler, max_requests=2).discover(
        category="home", keywords=[], market="us", max_results=20
    )

    assert len(calls) == 2


def test_with_nothing_to_ask_it_asks_nothing():
    """Sin términos no hay preguntas. Y no preguntar no es lo mismo que no
    encontrar nada."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    candidates = provider(handler).discover(
        category="category-nobody-seeded", keywords=[], market="us", max_results=5
    )

    assert candidates == []
    assert calls == []


def test_the_terms_asked_for_come_before_the_seeded_ones():
    """Quien pregunta sabe mejor qué busca que una lista general."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    provider(handler, max_requests=3).discover(
        category="home", keywords=["Sous vide"], market="us", max_results=3
    )

    assert "Sous_vide" in calls[0]


def test_the_body_is_read_as_a_series_not_as_a_single_number():
    """Se guarda la suma, pero se mira la serie: sin ella no habría trayectoria."""
    adapter = provider(always(200, series_body([1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9000])))

    candidates = adapter.discover(category="home", keywords=["Air fryer"], market="us", max_results=1)

    assert candidates[0].signal(SignalKind.FUTURE_OUTLOOK).value == 1.0


def test_the_adapter_closes_the_client_it_opened(monkeypatch):
    """Si el adaptador abre su propio cliente, lo cierra. Un socket suelto por
    ejecución es una fuga lenta en un worker que vive días."""
    closed: list[bool] = []
    real_client = httpx.Client(transport=httpx.MockTransport(always(200, series_body([100] * 12))))
    original_close = real_client.close

    def spy_close() -> None:
        closed.append(True)
        original_close()

    real_client.close = spy_close  # type: ignore[method-assign]
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client)

    WikimediaPageviewsProvider(today=TODAY).discover(
        category="home", keywords=["Air fryer"], market="us", max_results=1
    )

    assert closed == [True]


def test_an_injected_client_is_not_closed_by_the_adapter():
    """El que lo abrió, lo cierra: cerrar un cliente prestado rompería al que
    lo comparte."""
    client = httpx.Client(transport=httpx.MockTransport(always(200, series_body([100] * 12))))

    WikimediaPageviewsProvider(client, today=TODAY).discover(
        category="home", keywords=["Air fryer"], market="us", max_results=1
    )

    assert client.is_closed is False
    client.close()


def test_the_request_url_is_the_documented_endpoint():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=series_body([100] * 12), request=request)

    provider(handler, months=12).discover(
        category="home", keywords=["Air fryer"], market="us", max_results=1
    )

    assert calls[0] == (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        "en.wikipedia/all-access/user/Air_fryer/monthly/2025090100/2026083100"
    )


def test_the_recorded_body_shape_is_the_real_one():
    """La forma que se simula en estas pruebas es la que devuelve la API de
    verdad, grabada de una llamada real."""
    recorded = json.loads(
        '{"items":[{"project":"en.wikipedia","article":"Wireless_earbuds","granularity":"monthly",'
        '"timestamp":"2025060100","access":"all-access","agent":"user","views":13}]}'
    )
    adapter = provider(always(200, recorded))

    candidates = adapter.discover(
        category="electronics", keywords=["Wireless earbuds"], market="us", max_results=1
    )

    assert candidates[0].signal(SignalKind.DEMAND).value > 0
    # Trece visitas en un mes: medido, real y con poca confianza. Las tres cosas
    # a la vez, que es justo lo que el campo existe para poder decir.
    assert candidates[0].signal(SignalKind.DEMAND).confidence < 0.4


# --- El contador de llamadas externas (Milestone 37, plan maestro §25) -------


class CountingMeter:
    """Un contador que apunta y, si se le dice, corta."""

    def __init__(self, allowed: int = 99) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, str, int]] = []

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        self.calls.append((provider, operation, units))
        if len(self.calls) > self.allowed:
            raise ApiBudgetExceededError("sin cuota")


def test_every_request_passes_through_the_meter():
    """Esta fuente no cuesta dinero y **sí** consume cuota: su especificación pide
    no pasar de 200 peticiones por segundo. Contar lo gratuito también es el
    trabajo del libro de costes."""
    meter = CountingMeter()
    provider = WikimediaPageviewsProvider(
        client_returning(always(200, series_body([100] * 12))), today=TODAY, meter=meter
    )

    provider.discover(category="home", keywords=[], market="us", max_results=3)

    assert [operation for _provider, operation, _units in meter.calls] == [
        "pageviews/per-article"
    ] * 3
    assert all(name == PROVIDER_NAME for name, _operation, _units in meter.calls)


def test_an_exhausted_quota_produces_absence_not_a_zero():
    """Lo mismo que un 404 o un timeout: sin dato. Un cero se leería como «no hay
    interés» cuando lo cierto es «no lo sabemos»."""
    meter = CountingMeter(allowed=1)
    provider = WikimediaPageviewsProvider(
        client_returning(always(200, series_body([100] * 12))), today=TODAY, meter=meter
    )

    candidates = provider.discover(category="home", keywords=[], market="us", max_results=3)

    assert len(candidates) == 1


def test_without_a_meter_it_still_works_for_a_unit_test():
    """`UnmeteredCalls` es el valor por defecto documentado: en un montaje real lo
    inyecta el registro, y hay un test aparte que lo comprueba."""
    provider = WikimediaPageviewsProvider(
        client_returning(always(200, series_body([100] * 12))), today=TODAY
    )

    assert provider.discover(category="home", keywords=[], market="us", max_results=1)
