"""Conversión explícita y trazable, o ninguna (Milestone 40, ADR 0018)."""

import datetime
from decimal import Decimal

import pytest

from app.money.money import Money
from app.money.rates import (
    MAX_RATE_AGE_DAYS,
    ExchangeRate,
    NoRateAvailableError,
    RateDirection,
    StaleRateError,
    convert,
)
from app.money.serialization import conversion_to_json
from app.sourcing.provenance import SupplierFactProvenance

TODAY = datetime.date(2026, 9, 29)


def rate(**kwargs) -> ExchangeRate:
    defaults = {
        "base_currency": "USD",
        "quote_currency": "EUR",
        "rate": Decimal("0.92"),
        "effective_date": TODAY,
        "source": "manual:owner",
    }
    return ExchangeRate(**{**defaults, **kwargs})


def test_a_conversion_keeps_the_ten_fields_that_make_it_auditable():
    conversion = convert(Money.of("4.20", "USD"), to="EUR", rate=rate(), on=TODAY)

    stored = conversion_to_json(conversion)
    assert stored == {
        "source_currency": "USD",
        "source_amount": "4.2000",
        "target_currency": "EUR",
        "converted_amount": "3.8640",
        "rate": "0.92",
        "pair": "USD/EUR",
        "direction": "direct",
        "effective_date": "2026-09-29",
        "source": "manual:owner",
        "provenance": "declared",
    }


def test_the_pair_says_which_way_round_it_goes():
    """Sin el par y la dirección, «1,08» puede ser dólares por euro o euros por
    dólar, y entre las dos lecturas hay un 16 %."""
    assert rate().pair == "USD/EUR"


def test_a_rate_used_backwards_says_so():
    """Invertir no es gratis: los diferenciales de compra y venta no son
    simétricos, y quien audite el número tiene que poder verlo."""
    conversion = convert(Money.of("10", "EUR"), to="USD", rate=rate(), on=TODAY)

    assert conversion.direction is RateDirection.INVERTED
    assert conversion.pair == "USD/EUR"
    assert conversion.converted.amount == Decimal("10.8696")


def test_a_direct_rate_is_marked_direct():
    assert convert(Money.of("1", "USD"), to="EUR", rate=rate(), on=TODAY).direction is (
        RateDirection.DIRECT
    )


def test_a_stale_rate_is_refused():
    """Una tasa de hace meses es peor que no tener ninguna: tiene aspecto de
    dato."""
    old = rate(effective_date=TODAY - datetime.timedelta(days=MAX_RATE_AGE_DAYS + 1))

    with pytest.raises(StaleRateError, match="looks like data and is not"):
        convert(Money.of("1", "USD"), to="EUR", rate=old, on=TODAY)


def test_a_rate_inside_the_window_is_accepted():
    fresh = rate(effective_date=TODAY - datetime.timedelta(days=MAX_RATE_AGE_DAYS))

    assert convert(Money.of("1", "USD"), to="EUR", rate=fresh, on=TODAY).converted.amount


def test_a_rate_from_the_future_is_refused():
    """Convertir hoy con el cambio de mañana es leer la respuesta antes del
    examen."""
    with pytest.raises(ValueError, match="in the future"):
        convert(
            Money.of("1", "USD"),
            to="EUR",
            rate=rate(effective_date=TODAY + datetime.timedelta(days=1)),
            on=TODAY,
        )


def test_a_rate_for_another_pair_does_not_apply():
    """No se busca una tasa «parecida»: se dice que no hay."""
    with pytest.raises(NoRateAvailableError, match="does not apply"):
        convert(
            Money.of("1", "GBP"),
            to="EUR",
            rate=rate(),
            on=TODAY,
        )


def test_there_is_no_one_to_one_anywhere():
    """No existe camino que convierta sin tasa. El único modo de no convertir
    es no llamar a `convert`, y entonces el análisis es no evaluable."""
    with pytest.raises(ValueError, match="not a conversion"):
        convert(Money.of("1", "EUR"), to="EUR", rate=rate(), on=TODAY)


def test_a_rate_must_be_a_decimal_and_positive():
    with pytest.raises(ValueError, match="Decimal"):
        rate(rate=0.92)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive"):
        rate(rate=Decimal("0"))


def test_a_rate_between_a_currency_and_itself_is_not_a_rate():
    with pytest.raises(ValueError, match="needs no conversion"):
        rate(base_currency="EUR", quote_currency="EUR")


def test_a_rate_nobody_stands_behind_cannot_exist():
    """Una tasa sin procedencia es la suposición 1:1 dando un rodeo."""
    with pytest.raises(ValueError, match="1:1 assumption"):
        rate(provenance=SupplierFactProvenance.UNKNOWN)


def test_third_party_verification_needs_an_issuer():
    with pytest.raises(ValueError, match="name the issuer"):
        rate(provenance=SupplierFactProvenance.THIRD_PARTY_VERIFIED)
