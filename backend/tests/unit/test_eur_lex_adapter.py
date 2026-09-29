"""El adaptador de EUR-Lex/Cellar con transporte falso (Milestone 41, ADR 0019).

Ninguna prueba toca la red. La respuesta de ejemplo reproduce la forma real que
devolvió Cellar para la Directiva 2014/35 el 29-09-2026: **dos** fechas de entrada
en vigor y el fin de validez `9999-12-31`.
"""

import datetime
import json

import httpx
import pytest

from app.core.errors import ValidationError
from app.costs.service import ApiBudgetExceededError, CallMeter
from app.integrations.regulatory.eur_lex import (
    OPERATION,
    PROVIDER_NAME,
    USER_AGENT,
    AnchorUnavailableError,
    EurLexCellarSource,
    validate_celex,
)

NOW = datetime.datetime(2026, 9, 29, 12, 0, tzinfo=datetime.UTC)
CDM = "http://publications.europa.eu/ontology/cdm#"


def row(prop: str, value: str) -> dict:
    return {"p": {"type": "uri", "value": CDM + prop}, "o": {"type": "literal", "value": value}}


LVD_2014_35 = [
    row("resource_legal_in-force", "1"),
    row("resource_legal_date_entry-into-force", "2016-04-20"),
    row("resource_legal_date_entry-into-force", "2014-04-18"),
    row("resource_legal_date_end-of-validity", "9999-12-31"),
    row("resource_legal_eli", "http://data.europa.eu/eli/dir/2014/35/oj"),
    row("work_date_document", "2014-02-26"),
    row(
        "work_has_resource-type",
        "http://publications.europa.eu/resource/authority/resource-type/DIR",
    ),
]


def transport(bindings=None, status=200, body=None, capture=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        if body is not None:
            return httpx.Response(status, content=body)
        return httpx.Response(status, json={"results": {"bindings": bindings or []}})

    return httpx.MockTransport(handler)


class RecordingMeter(CallMeter):
    def __init__(self, deny: bool = False) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self._deny = deny

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        self.calls.append((provider, operation, units))
        if self._deny:
            raise ApiBudgetExceededError("denied by the meter")


def source(mock_transport, meter=None) -> EurLexCellarSource:
    return EurLexCellarSource(
        httpx.Client(transport=mock_transport), meter=meter or RecordingMeter(), now=NOW
    )


def test_it_reads_existence_dates_type_and_eli_as_the_source_gives_them():
    anchor = source(transport(LVD_2014_35)).lookup("32014L0035")

    assert anchor.found is True
    assert anchor.in_force is True
    assert anchor.act_type_code == "DIR"
    assert anchor.eli == "http://data.europa.eu/eli/dir/2014/35/oj"
    assert anchor.document_date == "2014-02-26"
    assert anchor.retrieved_at == NOW
    assert anchor.provider == PROVIDER_NAME


def test_two_entry_into_force_dates_are_kept_and_none_is_chosen():
    anchor = source(transport(LVD_2014_35)).lookup("32014L0035")

    assert anchor.entry_into_force == ("2014-04-18", "2016-04-20")


def test_the_9999_end_of_validity_is_kept_raw_without_interpretation():
    anchor = source(transport(LVD_2014_35)).lookup("32014L0035")

    assert anchor.end_of_validity == "9999-12-31"


def test_conflicting_end_dates_are_not_resolved_by_picking_one():
    rows = [*LVD_2014_35, row("resource_legal_date_end-of-validity", "2030-01-01")]

    anchor = source(transport(rows)).lookup("32014L0035")

    assert anchor.end_of_validity is None
    assert sorted(anchor.raw["resource_legal_date_end-of-validity"]) == ["2030-01-01", "9999-12-31"]


def test_everything_the_source_returned_is_kept_as_evidence():
    anchor = source(transport(LVD_2014_35)).lookup("32014L0035")

    assert anchor.raw["resource_legal_in-force"] == ["1"]
    assert anchor.raw["work_date_document"] == ["2014-02-26"]


def test_an_act_the_source_does_not_know_is_not_found_not_an_error():
    anchor = source(transport([])).lookup("32099R9999")

    assert anchor.found is False
    assert anchor.in_force is None


def test_an_in_force_flag_the_source_did_not_state_stays_absent():
    rows = [r for r in LVD_2014_35 if "in-force" not in r["p"]["value"]]

    anchor = source(transport(rows)).lookup("32014L0035")

    assert anchor.found is True
    assert anchor.in_force is None


def test_a_zero_in_force_flag_is_read_as_not_in_force():
    rows = [row("resource_legal_in-force", "0"), *LVD_2014_35[1:]]

    assert source(transport(rows)).lookup("32014L0035").in_force is False


# --- Fallos: no hay ancla, y no se inventa ----------------------------------


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_an_http_failure_is_unavailable_not_not_found(status):
    with pytest.raises(AnchorUnavailableError):
        source(transport(status=status)).lookup("32014L0035")


def test_a_body_that_is_not_json_is_unavailable():
    with pytest.raises(AnchorUnavailableError):
        source(transport(body=b"<html>maintenance</html>")).lookup("32014L0035")


def test_a_json_of_an_unexpected_shape_is_unavailable():
    with pytest.raises(AnchorUnavailableError):
        source(transport(body=json.dumps({"oops": True}).encode())).lookup("32014L0035")


def test_a_network_error_is_unavailable():
    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(AnchorUnavailableError):
        source(httpx.MockTransport(boom)).lookup("32014L0035")


# --- El identificador se valida antes de salir -------------------------------


@pytest.mark.parametrize(
    "bad",
    ['32014L0035" } ; DROP', "hello", "12014L0035", "32014L035", "", "32014l0035x", "3201400035"],
)
def test_a_malformed_celex_never_reaches_the_source(bad):
    calls: list = []
    meter = RecordingMeter()

    with pytest.raises(ValidationError):
        source(transport(LVD_2014_35, capture=calls), meter).lookup(bad)

    assert calls == []
    assert meter.calls == []


def test_a_celex_is_normalised_but_not_reinterpreted():
    assert validate_celex(" 32014l0035 ") == "32014L0035"


# --- Coste: se autoriza antes de salir ---------------------------------------


def test_the_call_is_authorised_with_the_meter_before_leaving():
    meter = RecordingMeter()

    source(transport(LVD_2014_35), meter).lookup("32014L0035")

    assert meter.calls == [(PROVIDER_NAME, OPERATION, 1)]


def test_a_denied_call_never_reaches_the_network():
    calls: list = []

    with pytest.raises(ApiBudgetExceededError):
        source(transport(LVD_2014_35, capture=calls), RecordingMeter(deny=True)).lookup("32014L0035")

    assert calls == []


def test_the_request_is_an_anonymous_get_with_an_identifying_user_agent():
    calls: list[httpx.Request] = []

    source(transport(LVD_2014_35, capture=calls)).lookup("32014L0035")

    (request,) = calls
    assert request.method == "GET"
    assert request.url.host == "publications.europa.eu"
    assert request.headers["user-agent"] == USER_AGENT
    assert "authorization" not in request.headers
    assert "32014L0035" in str(request.url)
