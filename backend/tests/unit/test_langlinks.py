"""Cómo se llama el mismo producto en otro idioma, según la fuente (Milestone 38).

Ninguna prueba sale a internet: el cliente se inyecta con respuestas grabadas, con
la forma que publica la documentación de la API de acciones.

Lo que protegen: que una equivalencia **la declare Wikimedia y no este código**, y
que cuando no la declara **no se invente nada** — ni traducción, ni transcripción,
ni el artículo más parecido, que es la resolución por similitud que la ADR 0014
prohíbe.
"""

import httpx
import pytest

from app.costs.service import ApiBudgetExceededError, CallMeter
from app.integrations.product_intelligence.langlinks import (
    OPERATION,
    PROVIDER_NAME,
    LanglinkResolver,
)


def body(langlinks: list[dict] | None, *, missing: bool = False) -> dict:
    """La forma que publica la documentación de la API de acciones."""
    page: dict = {"pageid": 1, "ns": 0, "title": "Air fryer"}
    if missing:
        page = {"ns": 0, "title": "Air fryer", "missing": True}
    elif langlinks is not None:
        page["langlinks"] = langlinks
    return {"batchcomplete": True, "query": {"pages": [page]}}


def resolver(handler, **kwargs) -> LanglinkResolver:
    return LanglinkResolver(httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def always(status: int, payload: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, request=request)

    return handler


def ask(res: LanglinkResolver, language: str = "es"):
    return res.title_in(title="Air fryer", source_project="en.wikipedia", language=language)


# --- Lo que declara la fuente ----------------------------------------------


def test_a_declared_equivalence_comes_back_with_its_reference():
    payload = body([{"lang": "es", "title": "Freidora de aire"}])

    resolved = ask(resolver(always(200, payload)))

    assert resolved is not None
    title, reference = resolved
    assert title == "Freidora de aire"
    assert "api.php" in reference


def test_only_the_language_that_was_asked_for_is_taken():
    payload = body(
        [{"lang": "de", "title": "Heißluftfritteuse"}, {"lang": "es", "title": "Freidora de aire"}]
    )

    assert ask(resolver(always(200, payload)))[0] == "Freidora de aire"


def test_the_answer_is_cached_within_one_instance():
    """Una investigación pregunta por los mismos términos varias veces y no tiene
    sentido gastar cuota en repetirlo."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=body([{"lang": "es", "title": "Freidora de aire"}]))

    res = resolver(handler)
    ask(res)
    ask(res)

    assert calls["n"] == 1


# --- Lo que hace cuando no hay equivalencia --------------------------------


@pytest.mark.parametrize(
    "payload",
    [body([]), body(None), body(None, missing=True), body([{"lang": "de", "title": "X"}])],
    ids=["sin-langlinks", "sin-la-clave", "articulo-inexistente", "otro-idioma"],
)
def test_no_declaration_means_no_equivalence_and_nothing_invented(payload):
    assert ask(resolver(always(200, payload))) is None


@pytest.mark.parametrize("status", [404, 429, 500, 503])
def test_an_error_leaves_no_equivalence(status):
    assert ask(resolver(always(status, {"error": "vaya"}))) is None


def test_a_body_that_is_not_json_leaves_no_equivalence():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>vaya</html>")

    assert ask(resolver(handler)) is None


def test_an_unexpected_shape_leaves_no_equivalence():
    assert ask(resolver(always(200, {"query": {"pages": "no es una lista"}}))) is None


def test_a_timeout_leaves_no_equivalence():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("demasiado lento", request=request)

    assert ask(resolver(handler)) is None


# --- El contador ------------------------------------------------------------


class DenyAll(CallMeter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        self.calls.append((provider, operation))
        raise ApiBudgetExceededError("sin cuota")


def test_every_call_passes_through_the_meter():
    meter = DenyAll()

    assert ask(resolver(always(200, body([])), meter=meter)) is None
    assert meter.calls == [(PROVIDER_NAME, OPERATION)]


def test_an_exhausted_quota_produces_absence_not_a_guess():
    meter = DenyAll()

    assert ask(resolver(always(200, body([{"lang": "es", "title": "Freidora de aire"}])), meter=meter)) is None


# --- Lo que se le pregunta -------------------------------------------------


def test_it_asks_the_source_project_for_the_language_requested():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=body([{"lang": "es", "title": "Freidora de aire"}]))

    ask(resolver(handler))

    assert "en.wikipedia.org/w/api.php" in seen[0]
    assert "lllang=es" in seen[0]
    assert "prop=langlinks" in seen[0]
