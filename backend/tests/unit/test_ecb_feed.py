"""El adaptador del BCE con transporte falso (Milestone 42, ADR 0020).

Ninguna prueba toca la red. Los ficheros de `tests/fixtures/ecb/` son copias reales
de lo que el BCE publicó el 29-09-2026: el diario (atributos con comillas simples)
y tres días del histórico de 90 días (comillas dobles), que incluyen el hueco del
fin de semana (viernes 25 → lunes 28).
"""

import datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.costs.service import ApiBudgetExceededError, CallMeter
from app.integrations.fx.ecb import (
    DAILY_URL,
    HISTORY_URL,
    OP_DAILY,
    OP_HISTORY,
    USER_AGENT,
    EcbReferenceRateFeed,
    FeedUnavailableError,
    parse_reference_xml,
)
from app.money.ecb import PROVIDER_NAME

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ecb"
NOW = datetime.datetime(2026, 9, 29, 22, 0, tzinfo=datetime.UTC)
DAILY_XML = (FIXTURES / "eurofxref-daily.xml").read_text(encoding="utf-8")
HISTORY_XML = (FIXTURES / "eurofxref-hist-90d-sample.xml").read_text(encoding="utf-8")


def parse(text: str):
    return parse_reference_xml(text, source_url=DAILY_URL, retrieved_at=NOW)


def envelope(*days: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
        'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
        "<Cube>" + "".join(days) + "</Cube></gesmes:Envelope>"
    )


def day(date: str, *pairs: tuple[str, str]) -> str:
    cubes = "".join(f'<Cube currency="{c}" rate="{r}"/>' for c, r in pairs)
    return f'<Cube time="{date}">{cubes}</Cube>'


# --- Los dos ficheros reales --------------------------------------------------


def test_the_daily_file_with_single_quoted_attributes_parses():
    (only,) = parse(DAILY_XML)

    assert only.published_on == datetime.date(2026, 9, 29)
    assert only.base == "EUR"
    assert only.rates["USD"] == Decimal("1.1355")
    assert len(only.rates) == 29


def test_the_history_file_with_double_quoted_attributes_parses_newest_first():
    sets = parse(HISTORY_XML)

    assert [item.published_on for item in sets] == [
        datetime.date(2026, 9, 29),
        datetime.date(2026, 9, 28),
        datetime.date(2026, 9, 25),
    ]
    assert all(len(item.rates) == 29 for item in sets)


def test_the_weekend_has_no_rate_and_nothing_fills_it():
    """El hueco entre viernes y lunes se queda hueco: no se inventa un sábado."""
    dates = {item.published_on for item in parse(HISTORY_XML)}

    assert datetime.date(2026, 9, 26) not in dates
    assert datetime.date(2026, 9, 27) not in dates


def test_rates_are_decimals_and_keep_the_digits_the_source_published():
    (only,) = parse(DAILY_XML)

    assert all(isinstance(value, Decimal) for value in only.rates.values())
    # Cinco decimales en la libra, dos en el won… tal cual, sin redondear.
    assert only.rates["GBP"] == Decimal("0.85718")
    assert str(only.rates["IDR"]) == "20350.09"


def test_the_rate_is_the_number_of_units_per_euro_as_published():
    """`1 EUR = 1,1355 USD`. Es la convención del BCE y el conjunto la lleva
    explícita para que nadie tenga que adivinar la dirección."""
    (only,) = parse(DAILY_XML)

    assert only.base == "EUR"


# --- Lo que no se acepta ------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "",
        "this is not xml",
        "<a><b></a>",
        envelope(),
        envelope(day("2026-09-29")),
        envelope(day("not-a-date", ("USD", "1.1"))),
        envelope(day("2026-09-29", ("USD", "abc"))),
        envelope(day("2026-09-29", ("USD", "0"))),
        envelope(day("2026-09-29", ("USD", "-1.2"))),
        envelope(day("2026-09-29", ("USD", "NaN"))),
        envelope(day("2026-09-29", ("USD", "Infinity"))),
        envelope(day("2026-09-29", ("usd", "1.1"))),
        envelope(day("2026-09-29", ("US", "1.1"))),
        envelope(day("2026-09-29", ("USD", "1.1"), ("USD", "1.2"))),
        envelope(day("2026-09-29", ("USD", "1.1")), day("2026-09-29", ("GBP", "0.8"))),
        '<!DOCTYPE x [<!ENTITY a "b">]><Cube time="2026-09-29"><Cube currency="USD" rate="1.1"/></Cube>',
    ],
)
def test_anything_unexpected_fails_loudly_instead_of_yielding_a_partial_result(body):
    with pytest.raises(FeedUnavailableError):
        parse(body)


def test_a_bad_day_makes_the_whole_file_fail_not_just_that_day():
    body = envelope(day("2026-09-29", ("USD", "1.1")), day("2026-09-28", ("USD", "oops")))

    with pytest.raises(FeedUnavailableError):
        parse(body)


# --- La descarga --------------------------------------------------------------


class RecordingMeter(CallMeter):
    def __init__(self, deny: bool = False) -> None:
        self.deny = deny
        self.calls: list[tuple[str, str, int]] = []

    def authorise(self, *, provider: str, operation: str, units: int = 1) -> None:
        self.calls.append((provider, operation, units))
        if self.deny:
            raise ApiBudgetExceededError("denied")


def client_for(status=200, body=DAILY_XML, seen=None, error=None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if error is not None:
            raise error
        content = body.encode("utf-8") if isinstance(body, str) else body
        return httpx.Response(status, content=content)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_daily_fetch_is_one_metered_request_with_an_identified_agent():
    seen: list[httpx.Request] = []
    meter = RecordingMeter()

    result = EcbReferenceRateFeed(client_for(seen=seen), meter=meter, now=NOW).fetch_daily()

    assert len(seen) == 1
    assert str(seen[0].url) == DAILY_URL
    assert seen[0].headers["user-agent"] == USER_AGENT
    assert meter.calls == [(PROVIDER_NAME, OP_DAILY, 1)]
    assert result.retrieved_at == NOW
    assert result.source_url == DAILY_URL


def test_the_history_fetch_uses_its_own_file_and_operation():
    seen: list[httpx.Request] = []
    meter = RecordingMeter()

    sets = EcbReferenceRateFeed(client_for(body=HISTORY_XML, seen=seen), meter=meter).fetch_history()

    assert str(seen[0].url) == HISTORY_URL
    assert meter.calls == [(PROVIDER_NAME, OP_HISTORY, 1)]
    assert len(sets) == 3


def test_a_denied_call_never_reaches_the_network():
    seen: list[httpx.Request] = []

    with pytest.raises(ApiBudgetExceededError):
        EcbReferenceRateFeed(client_for(seen=seen), meter=RecordingMeter(deny=True)).fetch_daily()

    assert seen == []


@pytest.mark.parametrize("status", [404, 429, 500, 503])
def test_a_non_200_answer_is_unavailable_not_no_change(status):
    with pytest.raises(FeedUnavailableError, match=str(status)):
        EcbReferenceRateFeed(client_for(status=status)).fetch_daily()


def test_a_network_failure_is_unavailable():
    error = httpx.ConnectTimeout("timed out")

    with pytest.raises(FeedUnavailableError):
        EcbReferenceRateFeed(client_for(error=error)).fetch_daily()


def test_an_oversized_body_is_not_parsed():
    with pytest.raises(FeedUnavailableError, match="larger"):
        EcbReferenceRateFeed(client_for(body="x" * 2_000_000)).fetch_daily()


def test_a_non_utf8_body_is_unavailable():
    with pytest.raises(FeedUnavailableError, match="UTF-8"):
        EcbReferenceRateFeed(client_for(body=b"\xff\xfe\x00")).fetch_daily()


def test_the_daily_file_must_carry_exactly_one_day():
    with pytest.raises(FeedUnavailableError, match="one day"):
        EcbReferenceRateFeed(client_for(body=HISTORY_XML)).fetch_daily()
