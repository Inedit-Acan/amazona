"""El adaptador de referencia #2 (Milestone 37, ADR 0015).

Ninguna de estas pruebas sale a internet: el cliente HTTP se inyecta con
respuestas grabadas, igual que en el adaptador de Wikimedia. Lo que se comprueba
es lo que de verdad importa de un adaptador —qué pregunta, cómo interpreta lo que
le devuelven, y **qué hace cuando no le devuelven nada**—, más lo que el plan
maestro §31 exige de un adaptador real: fallos, límite de ritmo y timeout.

El recorrido contra la API de verdad **no está aquí y todavía no se ha hecho**:
necesita un keyset de desarrollador gratuito que solo el propietario puede dar de
alta. Un test que depende de la red es un test que falla por motivos que no son
el código.
"""

import datetime
import json

import httpx
import pytest

from app.costs.service import ApiBudgetExceededError, CallMeter
from app.integrations.ports import SignalBasis, SignalKind
from app.integrations.product_intelligence.ebay import (
    LISTINGS_CEILING,
    MAX_CONFIDENCE,
    PRODUCTION_HOST,
    PROVIDER_NAME,
    SANDBOX_HOST,
    EbayBrowseProvider,
    EbayCredentialsMissingError,
    confidence_for,
    normalise_listings,
)

TOKEN_BODY = {"access_token": "t-1", "expires_in": 7200, "token_type": "Application Access Token"}


def handler_for(*, search_status: int = 200, search_body: dict | None = None, token_status: int = 200):
    """Un transporte grabado: el token primero, la búsqueda después."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(token_status, json=TOKEN_BODY)
        body = {"total": 1234, "itemSummaries": []} if search_body is None else search_body
        return httpx.Response(search_status, json=body)

    return handler


def client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def provider(client: httpx.Client, **kwargs) -> EbayBrowseProvider:
    kwargs.setdefault("client_id", "id")
    kwargs.setdefault("client_secret", "secret")
    return EbayBrowseProvider(client, **kwargs)


def discover(prov: EbayBrowseProvider, *, market: str = "us", max_results: int = 1):
    return prov.discover(category="home", keywords=[], market=market, max_results=max_results)


# --- Lo que sabe hacer -----------------------------------------------------


def test_it_only_claims_to_know_about_competition():
    """Podría dar precios y no los da: `Signal.value` está normalizado a 0-1 y un
    precio necesita moneda, que el contrato aún no tiene."""
    assert provider(client_with(handler_for())).supports() == frozenset({SignalKind.COMPETITION})


def test_a_listing_count_becomes_a_measured_competition_signal():
    [candidate] = discover(provider(client_with(handler_for(search_body={"total": 1234}))))

    [signal] = candidate.signals
    assert signal.kind is SignalKind.COMPETITION
    assert signal.basis is SignalBasis.MEASURED
    assert signal.provider == PROVIDER_NAME
    assert signal.value == round(normalise_listings(1234), 4)


def test_the_method_says_what_the_number_is_not():
    """Un recuento de anuncios no es vendedores de un producto ni unidades
    vendidas, y quien lea la señal tres capas más allá tiene que poder saberlo."""
    [candidate] = discover(provider(client_with(handler_for())))

    method = candidate.signals[0].method
    assert "PROXY FOR COMPETITION" in method
    assert "not units sold" in method
    assert "EBAY_US" in method


def test_the_raw_reference_leads_back_to_the_query():
    [candidate] = discover(provider(client_with(handler_for())))

    assert candidate.signals[0].raw_reference.startswith(f"{PRODUCTION_HOST}/buy/browse")


def test_a_count_is_not_a_series():
    """Vacío no significa cero observaciones: significa que esto no se mide así."""
    [candidate] = discover(provider(client_with(handler_for())))

    assert candidate.signals[0].observations == []


# --- Lo que hace cuando no hay dato ----------------------------------------


@pytest.mark.parametrize(
    "handler",
    [
        handler_for(search_status=404),
        handler_for(search_status=429),
        handler_for(search_status=500),
        handler_for(search_status=503),
        handler_for(search_body={"itemSummaries": []}),
        handler_for(search_body={"total": "muchos"}),
    ],
    ids=["404", "429", "500", "503", "no-total", "total-no-numerico"],
)
def test_no_answer_means_no_signal_never_a_zero(handler):
    """Un cero de competencia se leería como un hueco de mercado, que es la
    conclusión más cara que este sistema puede sacar de un error de red."""
    assert discover(provider(client_with(handler))) == []


def test_a_measured_zero_is_not_a_signal_either():
    """Cero anuncios está medido y aun así no se emite: diría más de lo que
    sabemos sobre por qué no hay ninguno."""
    assert discover(provider(client_with(handler_for(search_body={"total": 0})))) == []


def test_a_token_that_never_arrives_leaves_no_signal():
    assert discover(provider(client_with(handler_for(token_status=401)))) == []


def test_a_body_that_is_not_json_leaves_no_signal():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=TOKEN_BODY)
        return httpx.Response(200, text="<html>vaya</html>")

    assert discover(provider(client_with(handler))) == []


def test_a_timeout_leaves_no_signal():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=TOKEN_BODY)
        raise httpx.ReadTimeout("demasiado lento", request=request)

    assert discover(provider(client_with(handler))) == []


def test_one_failing_term_does_not_take_the_others_down():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=TOKEN_BODY)
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"detail": "slow down"})
        return httpx.Response(200, json={"total": 500})

    candidates = discover(provider(client_with(handler)), max_results=3)

    assert len(candidates) == 2


# --- Mercados ---------------------------------------------------------------


def test_an_unmapped_market_is_answered_with_silence():
    """Preguntar por el mercado de al lado mediría otra cosa y la presentaría como
    esta. `eu` no es un país."""
    assert discover(provider(client_with(handler_for())), market="eu") == []


def test_each_market_asks_its_own_marketplace():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=TOKEN_BODY)
        seen.append(request.headers["X-EBAY-C-MARKETPLACE-ID"])
        return httpx.Response(200, json={"total": 10})

    discover(provider(client_with(handler)), market="es")

    assert seen == ["EBAY_ES"]


# --- Credenciales y entorno ------------------------------------------------


@pytest.mark.parametrize(
    ("client_id", "client_secret"), [("", "secret"), ("id", ""), ("", "")]
)
def test_without_credentials_it_refuses_to_exist(client_id, client_secret):
    """Falla al construirse y no en la primera búsqueda: un proceso que descubre a
    mitad del pipeline que no puede preguntar ya ha hecho el daño (ADR 0008 §4)."""
    with pytest.raises(EbayCredentialsMissingError):
        EbayBrowseProvider(client_id=client_id, client_secret=client_secret)


def test_the_sandbox_host_is_not_the_production_host():
    """Lo que da contenido a `ProviderKind.SANDBOX`, que era una casilla vacía."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=TOKEN_BODY)
        return httpx.Response(200, json={"total": 10})

    discover(provider(client_with(handler), host=SANDBOX_HOST))

    assert all(url.startswith(SANDBOX_HOST) for url in seen)
    assert not any(url.startswith(PRODUCTION_HOST) for url in seen)


def test_the_token_is_asked_for_once_not_once_per_term():
    tokens = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            tokens["n"] += 1
            return httpx.Response(200, json=TOKEN_BODY)
        return httpx.Response(200, json={"total": 10})

    discover(provider(client_with(handler)), max_results=4)

    assert tokens["n"] == 1


# --- Cuota y presupuesto ---------------------------------------------------


class DenyAfter(CallMeter):
    """Un contador que deja pasar unas cuantas llamadas y luego corta."""

    def __init__(self, allowed: int) -> None:
        self.allowed = allowed
        self.calls: list[tuple[str, int]] = []

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        self.calls.append((operation, units))
        if len(self.calls) > self.allowed:
            raise ApiBudgetExceededError("sin cuota")


def test_every_external_call_passes_through_the_meter():
    """El token también cuenta: consume cuota igual que una búsqueda."""
    meter = DenyAfter(allowed=99)

    discover(provider(client_with(handler_for()), meter=meter), max_results=2)

    operations = [operation for operation, _ in meter.calls]
    assert operations[0] == "identity/oauth2/token"
    assert operations.count("item_summary/search") == 2


def test_an_exhausted_budget_produces_absence_not_a_zero():
    meter = DenyAfter(allowed=1)  # llega para el token y para nada más

    assert discover(provider(client_with(handler_for()), meter=meter), max_results=2) == []


def test_the_request_cap_limits_how_many_terms_are_asked():
    """Existe por el arriendo de 60 s del runtime, no por el proveedor."""
    searches = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=TOKEN_BODY)
        searches["n"] += 1
        return httpx.Response(200, json={"total": 10})

    discover(provider(client_with(handler), max_requests=2), max_results=6)

    assert searches["n"] == 2


# --- La escala --------------------------------------------------------------


def test_more_listings_means_more_competition():
    assert normalise_listings(10) < normalise_listings(1000) < normalise_listings(100_000)


def test_the_scale_is_bounded_at_both_ends():
    assert normalise_listings(0) == 0.0
    assert normalise_listings(LISTINGS_CEILING * 100) == 1.0


def test_confidence_grows_with_the_count_and_never_reaches_certainty():
    """Un marketplace no es el mercado: un producto puede estar disputadísimo en
    otro sitio y vacío en eBay."""
    assert confidence_for(5) < confidence_for(5000)
    assert confidence_for(10_000_000) <= MAX_CONFIDENCE
    assert confidence_for(0) == 0.0


def test_the_recorded_sample_is_the_shape_the_documentation_publishes():
    """La forma viene de la documentación oficial, no de la imaginación: el
    ejemplo publicado trae `total` junto a `itemSummaries`."""
    published = json.loads(
        '{"href": "...", "total": 260202, "next": "...", "limit": 1, "offset": 0,'
        ' "itemSummaries": [{"itemId": "v1|1**********1|0", "title": "Syma X5SW"}]}'
    )

    [candidate] = discover(provider(client_with(handler_for(search_body=published))))

    assert candidate.signals[0].value == round(normalise_listings(260202), 4)
    assert candidate.signals[0].observed_at.tzinfo is datetime.UTC
