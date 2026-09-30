"""El adaptador del BOE con transporte falso (Milestone 43, ADR 0021).

Ninguna prueba toca la red. Las respuestas de `tests/fixtures/boe/` son copias reales
de lo que la API de datos abiertos de la AEBOE devolvió el 29-09-2026 (el sumario está
recortado a la rama que contiene la norma).

Lo que se protege: la privacidad del `User-Agent`, «todo o nada» en el núcleo
(metadatos y análisis), y que un fallo de la comprobación auxiliar de publicación
**nunca** se convierta en una conclusión negativa.
"""

import datetime
import json
from pathlib import Path

import httpx
import pytest

from app.core.errors import ValidationError
from app.costs.service import ApiBudgetExceededError, CallMeter
from app.integrations.regulatory.boe import (
    OP_ANALYSIS,
    OP_METADATA,
    OP_SUMMARY,
    USER_AGENT,
    BoeConsolidatedSource,
    NationalSourceUnavailableError,
    parse_metadata,
    parse_relations,
)
from app.legal.national import PROVIDER_NAME

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "boe"
NOW = datetime.datetime(2026, 9, 30, 9, 0, tzinfo=datetime.UTC)
ID = "BOE-A-2011-14252"


def fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


META = fixture(f"metadatos_{ID}.json")
ANALYSIS = fixture(f"analisis_{ID}.json")
SUMMARY = fixture("sumario_20110831_recortado.json")
NOT_CONSOLIDATED = fixture("metadatos_404.xml")


class RecordingMeter(CallMeter):
    def __init__(self, deny_on: str | None = None) -> None:
        self.deny_on = deny_on
        self.calls: list[tuple[str, str, int]] = []

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        if operation == self.deny_on:
            raise ApiBudgetExceededError("denied")
        self.calls.append((provider, operation, units))


def client_for(routes: dict[str, object], seen: list[httpx.Request] | None = None) -> httpx.Client:
    """`routes` va de un sufijo de ruta a `(status, cuerpo)` o a una excepción."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        for suffix, answer in routes.items():
            if request.url.path.endswith(suffix):
                if isinstance(answer, Exception):
                    raise answer
                status, body = answer
                return httpx.Response(status, content=body)
        return httpx.Response(500, content=b"unscripted")

    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_routes(**overrides) -> dict[str, object]:
    routes: dict[str, object] = {
        f"/{ID}/metadatos": (200, META),
        f"/{ID}/analisis": (200, ANALYSIS),
        "/sumario/20110831": (200, SUMMARY),
    }
    routes.update(overrides)
    return routes


def source(routes, *, meter=None, seen=None) -> BoeConsolidatedSource:
    return BoeConsolidatedSource(client_for(routes, seen), meter=meter, now=NOW)


# --- Privacidad y forma de la petición ----------------------------------------


def test_the_user_agent_is_a_neutral_project_identifier_with_no_personal_data():
    assert USER_AGENT.startswith("KOVA-Regulatory-Client/")
    for forbidden in ("@", "mail", "contact", "acan", "ivan", "http"):
        assert forbidden not in USER_AGENT.lower()


def test_every_request_carries_only_that_identifier_and_nothing_personal():
    seen: list[httpx.Request] = []

    source(ok_routes(), seen=seen).lookup(ID)

    assert len(seen) == 3
    for request in seen:
        assert request.headers["user-agent"] == USER_AGENT
        assert request.headers["accept"] == "application/json"
        assert request.method == "GET"
        assert "@" not in str(request.url) and "@" not in str(request.headers)


def test_only_the_three_needed_endpoints_are_used_and_never_search_or_text():
    seen: list[httpx.Request] = []

    source(ok_routes(), seen=seen).lookup(ID)

    assert [r.url.path for r in seen] == [
        f"/datosabiertos/api/legislacion-consolidada/id/{ID}/metadatos",
        f"/datosabiertos/api/legislacion-consolidada/id/{ID}/analisis",
        "/datosabiertos/api/boe/sumario/20110831",
    ]
    assert all("texto" not in r.url.path and "metadata-eli" not in r.url.path for r in seen)


def test_the_three_calls_are_metered_before_they_are_made():
    meter = RecordingMeter()

    source(ok_routes(), meter=meter).lookup(ID)

    assert meter.calls == [
        (PROVIDER_NAME, OP_METADATA, 1),
        (PROVIDER_NAME, OP_ANALYSIS, 1),
        (PROVIDER_NAME, OP_SUMMARY, 1),
    ]


def test_an_identifier_that_is_not_a_boe_id_never_reaches_the_network():
    seen: list[httpx.Request] = []

    with pytest.raises(ValidationError):
        source(ok_routes(), seen=seen).lookup("Real Decreto 1205/2011")

    assert seen == []


def test_a_denied_call_never_reaches_the_network():
    seen: list[httpx.Request] = []

    with pytest.raises(ApiBudgetExceededError):
        source(ok_routes(), meter=RecordingMeter(deny_on=OP_METADATA), seen=seen).lookup(ID)

    assert seen == []


# --- Lo que se devuelve --------------------------------------------------------


def test_a_consolidated_norm_comes_back_verbatim_with_its_relations():
    record = source(ok_routes()).lookup(ID)

    assert record.consolidated is True
    assert record.national_id == ID
    assert record.retrieved_at == NOW
    # Metadatos tal cual: fechas como cadena, banderas S/N, sin reinterpretar.
    assert record.metadata["fecha_publicacion"] == "20110831"
    assert record.metadata["fecha_vigencia"] == "20110901"
    assert record.metadata["estatus_derogacion"] == "N"
    assert record.metadata["estado_consolidacion"] == {"codigo": "3", "texto": "Finalizado"}
    assert record.metadata["url_eli"] == "https://www.boe.es/eli/es/rd/2011/08/26/1205"
    # La relación 426 se conserva como la devolvió el BOE.
    transposes = [r for r in record.relations["previous"] if r["relation_code"] == 426]
    assert transposes == [
        {
            "id_norma": "DOUE-L-2009-81173",
            "relation_code": 426,
            "relation": "TRANSPONE",
            "text": "la Directiva 2009/48/CE, de 18 de junio de 2009",
        }
    ]
    assert len(record.relations["next"]) >= 5


def test_the_publication_is_confirmed_by_the_summary_and_the_link_is_official():
    record = source(ok_routes()).lookup(ID)

    assert record.publication.state == "confirmed"
    assert record.publication.url == "https://www.boe.es/buscar/doc.php?id=BOE-A-2011-14252"
    assert record.source_urls[-1].endswith("/boe/sumario/20110831")


def test_a_repealed_norm_keeps_its_source_flags():
    body = fixture("metadatos_BOE-A-1992-26318_derogada.json")
    routes = {
        "/BOE-A-1992-26318/metadatos": (200, body),
        "/BOE-A-1992-26318/analisis": (200, json.dumps({"status": {"code": "200"}, "data": {}}).encode()),
        "/sumario/19921127": (200, b'{"status": {"code": "200"}, "data": {}}'),
    }

    record = source(routes).lookup("BOE-A-1992-26318")

    assert record.metadata["estatus_derogacion"] == "S"
    assert record.metadata["fecha_derogacion"] == "20210402"
    assert record.metadata["vigencia_agotada"] == "S"
    # Antes de 2009 solo es oficial el papel: el sumario no se pregunta ni se da por bueno.
    assert record.publication.state == "not_checked"
    assert "paper" in (record.publication.detail or "")


# --- 404: no consolidada, no «no existe» ---------------------------------------


def test_a_404_is_not_consolidated_and_stops_there_without_calling_anything_else():
    seen: list[httpx.Request] = []
    routes = {f"/{ID}/metadatos": (404, NOT_CONSOLIDATED)}

    record = source(routes, seen=seen).lookup(ID)

    assert record.consolidated is False
    assert record.metadata == {} and record.relations == {}
    assert record.publication.state == "not_checked"
    assert len(seen) == 1


# --- Todo o nada en el núcleo ---------------------------------------------------


@pytest.mark.parametrize("status", [400, 403, 429, 500, 503])
def test_an_unexpected_status_on_metadata_is_unavailable(status):
    with pytest.raises(NationalSourceUnavailableError, match=str(status)):
        source(ok_routes(**{f"/{ID}/metadatos": (status, b"")})).lookup(ID)


@pytest.mark.parametrize("status", [404, 400, 500])
def test_any_failure_on_the_analysis_discards_the_whole_observation(status):
    """Metadatos sin análisis no es una observación coherente: no se devuelve nada."""
    with pytest.raises(NationalSourceUnavailableError):
        source(ok_routes(**{f"/{ID}/analisis": (status, b"")})).lookup(ID)


def test_a_network_failure_is_unavailable():
    error = httpx.ConnectTimeout("timed out")

    with pytest.raises(NationalSourceUnavailableError, match="did not answer"):
        source(ok_routes(**{f"/{ID}/metadatos": error})).lookup(ID)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"<response><status><code>200</code></status></response>",
        b"[]",
        b'{"status": {}}',
        json.dumps({"data": [{"identificador": "BOE-A-2000-1", "titulo": "Otra"}]}).encode(),
        json.dumps({"data": [{"identificador": ID}]}).encode(),
    ],
)
def test_metadata_that_is_not_the_requested_norm_or_not_json_is_unavailable(body):
    with pytest.raises(NationalSourceUnavailableError):
        source(ok_routes(**{f"/{ID}/metadatos": (200, body)})).lookup(ID)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<xml/>",
        b'{"data": {"referencias": {"anteriores": ["oops"]}}}',
        b'{"data": {"referencias": {"anteriores": [{"anterior": [{"relacion": {"codigo": "426"}}]}]}}}',
    ],
)
def test_an_analysis_that_cannot_be_read_is_unavailable(body):
    with pytest.raises(NationalSourceUnavailableError):
        source(ok_routes(**{f"/{ID}/analisis": (200, body)})).lookup(ID)


def test_an_oversized_body_is_not_parsed():
    huge = b"x" * 4_000_000

    with pytest.raises(NationalSourceUnavailableError, match="larger"):
        source(ok_routes(**{f"/{ID}/metadatos": (200, huge)})).lookup(ID)


def test_an_analysis_with_no_references_is_valid_and_has_no_relations():
    body = json.dumps({"status": {"code": "200"}, "data": {"materias": []}}).encode()

    record = source(ok_routes(**{f"/{ID}/analisis": (200, body)})).lookup(ID)

    assert record.relations == {"previous": [], "next": []}


def test_a_single_relation_that_is_a_dict_and_not_a_list_is_understood():
    """La conversión a JSON del BOE da un objeto cuando hay uno solo."""
    body = json.dumps(
        {
            "data": {
                "referencias": {
                    "anteriores": {
                        "anterior": {
                            "id_norma": "DOUE-L-2009-81173",
                            "relacion": {"codigo": "426", "texto": "TRANSPONE"},
                            "texto": "la Directiva 2009/48/CE",
                        }
                    }
                }
            }
        }
    ).encode()

    record = source(ok_routes(**{f"/{ID}/analisis": (200, body)})).lookup(ID)

    assert record.relations["previous"][0]["relation_code"] == 426


# --- La publicación oficial es auxiliar: un fallo no es «no existe» -------------


@pytest.mark.parametrize(
    "answer",
    [
        (500, b""),
        (404, b""),
        (200, b"not json"),
        (200, b"x" * 4_000_000),
        httpx.ReadTimeout("slow"),
    ],
)
def test_a_summary_that_fails_keeps_the_observation_and_is_check_failed_never_absent(answer):
    record = source(ok_routes(**{"/sumario/20110831": answer})).lookup(ID)

    assert record.consolidated is True
    assert record.metadata["identificador"] == ID
    assert record.publication.state == "check_failed"
    assert record.publication.state != "absent_from_summary"


def test_a_summary_that_was_read_and_does_not_list_the_norm_is_the_only_negative_answer():
    body = json.dumps({"status": {"code": "200"}, "data": {"sumario": {"diario": []}}}).encode()

    record = source(ok_routes(**{"/sumario/20110831": (200, body)})).lookup(ID)

    assert record.publication.state == "absent_from_summary"


def test_a_denied_summary_call_is_a_failed_check_not_a_failure_of_the_observation():
    record = source(ok_routes(), meter=RecordingMeter(deny_on=OP_SUMMARY)).lookup(ID)

    assert record.publication.state == "check_failed"
    assert record.consolidated is True


def test_a_norm_without_a_publication_date_skips_the_summary():
    seen: list[httpx.Request] = []
    metadata = json.loads(META)
    del metadata["data"][0]["fecha_publicacion"]

    record = source(ok_routes(**{f"/{ID}/metadatos": (200, json.dumps(metadata).encode())}), seen=seen).lookup(ID)

    assert record.publication.state == "not_checked"
    assert len(seen) == 2


# --- Analizadores -----------------------------------------------------------------


def test_parse_metadata_returns_the_item_unchanged():
    item = parse_metadata(json.loads(META), ID)

    assert item == json.loads(META)["data"][0]


def test_parse_relations_normalises_shape_and_not_content():
    relations = parse_relations(json.loads(ANALYSIS))

    codes = {r["relation_code"] for r in relations["previous"]}
    assert {210, 426, 440, 330} <= codes
    assert {r["relation"] for r in relations["previous"]} >= {"TRANSPONE", "DEROGA"}
