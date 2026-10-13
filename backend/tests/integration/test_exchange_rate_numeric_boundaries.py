"""Fronteras numéricas de `POST /api/exchange-rates` (M46, Commit 5c): `rate` y la columna `Numeric(18, 8)`.

La API rechaza **antes de PostgreSQL** lo que la columna no puede representar. Medido en PostgreSQL real antes del
cambio: `rate >= 1e10` desbordaba (500) y `1e-9` o `4e-9` se guardaban como `0E-8`, es decir cero, violando `rate > 0`;
`1.123456789012345678` se guardaba redondeado a `1.12345679`. Ahora: 422, no se redondea.

No cambia la semántica económica de FX: `rate > 0`, la procedencia como enum y el rechazo de `unknown` siguen igual; una
cadena `"0.92"` sigue siendo el formato del contrato.
"""

import datetime
import decimal

import pytest
from numeric_boundary_support import INF, NAN, assert_clean_422, post, rows
from sqlalchemy import select

from app.db.models.exchange_rate import ExchangeRate as ExchangeRateRow
from app.db.numeric_capacity import numeric_capacity

URL = "/api/exchange-rates"
CAPACITY = numeric_capacity(ExchangeRateRow.__table__.c.rate)  # 9999999999.99999999
_DAY = [0]


def _body(rate) -> dict:
    _DAY[0] += 1
    day = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=_DAY[0])
    return {"base_currency": "USD", "quote_currency": "EUR", "rate": rate, "effective_date": day.isoformat()}


def _stored(session_factory) -> list[decimal.Decimal]:
    with session_factory() as session:
        return [row.rate for row in session.scalars(select(ExchangeRateRow))]


ACCEPTED = [
    ("string", "0.92"),
    ("float", 0.92),
    ("integer", 1),
    ("eight_decimals", "0.12345678"),
    ("smallest_positive", "0.00000001"),
    ("largest_representable", "9999999999.99999999"),
    ("capacity_from_the_column", str(CAPACITY)),
]
REJECTED = [
    ("just_above_the_largest", "10000000000"),
    ("just_above_by_one_step", str(CAPACITY + decimal.Decimal("0.00000001"))),
    ("nine_decimals", "0.123456789"),
    ("quantizes_to_zero", "0.000000001"),  # 1e-9: la columna lo guardaría como 0E-8
    ("tiny_string", "1e-30"),
    ("tiny_float", 1e-30),
    ("zero_string", "0"),
    ("zero", 0),
    ("zero_eight_decimals", "0.00000000"),
    ("negative", "-1"),
    ("negative_float", -0.92),
    ("extreme", 1e308),
    ("extreme_string", "1e308"),
    ("overflow_24", 1e24),
    ("nan", NAN),
    ("inf", INF),
    ("-inf", -INF),
    ("nan_string", "NaN"),
    ("inf_string", "Infinity"),
    ("-inf_string", "-Infinity"),
    ("bool_true", True),
    ("bool_false", False),
    ("empty_string", ""),
    ("null", None),
    ("list", [1]),
    ("object", {"a": 1}),
    ("not_a_number", "abc"),
]


@pytest.mark.parametrize("label, rate", ACCEPTED, ids=[label for label, _ in ACCEPTED])
def test_a_rate_the_column_can_hold_is_accepted_and_returned_as_sent(boundary_world, label, rate):
    """SQLite guarda `Numeric` como coma flotante y no puede conservar 18 cifras; lo que se comprueba aquí es lo que la
    API acepta y devuelve. La exactitud en la columna real se verifica en PostgreSQL (ver el handoff)."""
    client, session_factory = boundary_world

    response = post(client, URL, _body(rate))

    assert response.status_code == 201, response.text
    assert decimal.Decimal(response.json()["rate"]) == decimal.Decimal(str(rate))
    assert len(_stored(session_factory)) == 1


@pytest.mark.parametrize("label, rate", REJECTED, ids=[label for label, _ in REJECTED])
def test_J_a_rate_outside_numeric_18_8_is_a_422_before_postgresql_and_writes_nothing(boundary_world, label, rate):
    client, session_factory = boundary_world
    before = rows(session_factory)

    response = post(client, URL, _body(rate))

    assert_clean_422(response, "rate")
    assert rows(session_factory) == before
    assert _stored(session_factory) == []  # ni redondeada ni sustituida por otro valor


def test_the_limits_follow_the_column_not_a_copy_of_it():
    """Si una migración ensancha la columna, la API la sigue: los límites salen del tipo declarado."""
    from app.api.economics import ExchangeRateCreate

    metadata = ExchangeRateCreate.model_fields["rate"].metadata
    max_digits = [m.max_digits for m in metadata if getattr(m, "max_digits", None) is not None]
    decimal_places = [m.decimal_places for m in metadata if getattr(m, "decimal_places", None) is not None]
    column_type = ExchangeRateRow.__table__.c.rate.type

    assert max_digits == [column_type.precision] == [18]
    assert decimal_places == [column_type.scale] == [8]


def test_two_invalid_rates_in_a_row_are_deterministic_and_the_next_valid_one_works(boundary_world):
    client, session_factory = boundary_world
    before = rows(session_factory)

    first = post(client, URL, _body(NAN))
    second = post(client, URL, _body(NAN))

    assert_clean_422(first, "rate")
    assert first.json() == second.json()
    assert rows(session_factory) == before
    assert post(client, URL, _body("0.92")).status_code == 201
    assert [decimal.Decimal(rate["rate"]) for rate in client.get(URL).json()] == [decimal.Decimal("0.92")]


def test_the_rest_of_the_fx_rules_are_untouched(boundary_world):
    client, session_factory = boundary_world
    before = rows(session_factory)

    unknown = post(client, URL, _body("0.92") | {"provenance": "unknown"})
    third_party_without_issuer = post(client, URL, _body("0.92") | {"provenance": "third_party_verified"})
    nope = post(client, URL, _body("0.92") | {"provenance": "nope"})
    same_currency = post(client, URL, _body("0.92") | {"quote_currency": "USD"})

    assert unknown.status_code == third_party_without_issuer.status_code == nope.status_code == 422
    assert same_currency.status_code == 422
    assert "cannot be declared unknown" in unknown.json()["detail"]
    assert rows(session_factory) == before


@pytest.mark.parametrize(
    "failure", [RuntimeError("internal secret detail"), decimal.InvalidOperation("internal decimal bug")]
)
def test_M_an_internal_failure_after_valid_input_is_still_a_500_and_never_leaks(boundary_world, monkeypatch, failure):
    client, session_factory = boundary_world
    before = rows(session_factory)

    def boom(**kwargs):
        raise failure

    monkeypatch.setattr("app.api.economics.ExchangeRate", boom)

    response = post(client, URL, _body("0.92"))

    assert response.status_code == 500
    assert "internal" not in response.text
    assert rows(session_factory) == before
