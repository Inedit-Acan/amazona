"""Antigüedad por tasa y fallback entre proveedores (Milestone 42, ADR 0020)."""

import datetime
from decimal import Decimal

import pytest

from app.core.errors import ValidationError
from app.money.money import Money
from app.money.rates import (
    MAX_RATE_AGE_DAYS,
    ExchangeRate,
    StaleRateError,
    convert,
)
from app.money.resolver import CompositeExchangeRateProvider
from app.money.serialization import conversion_to_json
from app.sourcing.provenance import SupplierFactProvenance

FRIDAY = datetime.date(2026, 9, 25)
MONDAY = datetime.date(2026, 9, 28)
TODAY = datetime.date(2026, 9, 29)


def rate(**kwargs) -> ExchangeRate:
    defaults = {
        "base_currency": "EUR",
        "quote_currency": "USD",
        "rate": Decimal("1.1355"),
        "effective_date": TODAY,
        "source": "ecb:eurofxref",
        "provenance": SupplierFactProvenance.THIRD_PARTY_VERIFIED,
        "declared_by": "European Central Bank",
        "max_age_days": 7,
    }
    return ExchangeRate(**{**defaults, **kwargs})


def test_a_rate_keeps_the_thirty_day_window_of_milestone_40_by_default():
    manual = ExchangeRate(
        base_currency="USD",
        quote_currency="EUR",
        rate=Decimal("0.92"),
        effective_date=TODAY,
        source="manual:owner",
    )

    assert manual.max_age_days == MAX_RATE_AGE_DAYS == 30


@pytest.mark.parametrize("days", [0, -1, 31, 90])
def test_a_window_outside_one_to_thirty_days_is_refused(days):
    with pytest.raises(ValidationError):
        rate(max_age_days=days)


def test_the_effective_date_of_a_weekend_rate_is_the_fridays_and_it_is_three_days_old():
    friday_rate = rate(effective_date=FRIDAY)

    assert friday_rate.age_in_days(MONDAY) == 3
    assert friday_rate.is_acceptable_on(MONDAY)
    assert friday_rate.effective_date == FRIDAY


@pytest.mark.parametrize(
    ("age", "acceptable"), [(0, True), (1, True), (7, True), (8, False)]
)
def test_an_ecb_rate_is_acceptable_within_its_seven_day_window(age, acceptable):
    aged = rate(effective_date=TODAY - datetime.timedelta(days=age))

    assert aged.is_acceptable_on(TODAY) is acceptable


def test_a_rate_from_the_future_is_never_acceptable():
    assert not rate(effective_date=TODAY + datetime.timedelta(days=1)).is_acceptable_on(TODAY)


def test_converting_with_an_eight_day_old_ecb_rate_fails_as_stale():
    old = rate(effective_date=TODAY - datetime.timedelta(days=8))

    with pytest.raises(StaleRateError, match="7-day window"):
        convert(Money.of("10", "EUR"), to="USD", rate=old, on=TODAY)


def test_a_manual_rate_of_twenty_days_still_converts():
    manual = ExchangeRate(
        base_currency="USD",
        quote_currency="EUR",
        rate=Decimal("0.92"),
        effective_date=TODAY - datetime.timedelta(days=20),
        source="manual:owner",
    )

    assert convert(Money.of("10", "USD"), to="EUR", rate=manual, on=TODAY).converted_amount


def test_using_an_ecb_rate_backwards_is_recorded_as_inverted_with_its_dates():
    conversion = convert(Money.of("11.355", "USD"), to="EUR", rate=rate(), on=TODAY)

    assert conversion.direction.value == "inverted"
    assert conversion.pair == "EUR/USD"
    assert conversion.effective_date == TODAY
    assert conversion.converted_amount == Decimal("10")


def test_the_ingestion_date_travels_with_the_conversion_only_when_known():
    ingested = datetime.datetime(2026, 9, 29, 14, 5, tzinfo=datetime.UTC)
    with_date = convert(
        Money.of("11.355", "USD"), to="EUR", rate=rate(ingested_at=ingested), on=TODAY
    )
    without = convert(Money.of("11.355", "USD"), to="EUR", rate=rate(), on=TODAY)

    assert conversion_to_json(with_date)["ingested_at"] == ingested.isoformat()
    assert "ingested_at" not in conversion_to_json(without)
    assert conversion_to_json(with_date)["provenance"] == "third_party_verified"
    assert conversion_to_json(with_date)["source"] == "ecb:eurofxref"


# --- El compuesto salta las fuentes no aceptables -----------------------------


class Fixed:
    def __init__(self, name: str, answer: ExchangeRate | None) -> None:
        self.name = name
        self.answer = answer
        self.asked = 0

    def rate_for(self, *, base, quote, on):
        self.asked += 1
        return self.answer


def manual(age_days: int) -> ExchangeRate:
    return ExchangeRate(
        base_currency="USD",
        quote_currency="EUR",
        rate=Decimal("0.92"),
        effective_date=TODAY - datetime.timedelta(days=age_days),
        source="manual:owner",
    )


def ask(*sources) -> ExchangeRate | None:
    return CompositeExchangeRateProvider(list(sources)).rate_for(
        base="USD", quote="EUR", on=TODAY
    )


def test_a_fresh_manual_rate_wins_over_the_ecb():
    chosen = ask(Fixed("manual", manual(2)), Fixed("ecb", rate()))

    assert chosen.source == "manual:owner"


def test_a_stale_manual_rate_does_not_shadow_a_fresh_ecb_reference():
    """El fallo latente de M40: la primera que contestaba ganaba, aunque
    estuviera caducada, y el análisis quedaba no evaluable con una tasa buena
    detrás."""
    chosen = ask(Fixed("manual", manual(40)), Fixed("ecb", rate()))

    assert chosen.source == "ecb:eurofxref"


def test_a_stale_ecb_rate_falls_through_to_the_next_acceptable_source():
    stale_ecb = rate(effective_date=TODAY - datetime.timedelta(days=9))
    fixture = manual(0)

    assert ask(Fixed("ecb", stale_ecb), Fixed("fixture", fixture)) is fixture


def test_when_nothing_is_acceptable_the_first_answer_comes_back_so_it_is_rejected_as_stale():
    """«Hay tasa y es vieja» no debe confundirse con «no hay tasa»."""
    old_manual = manual(40)
    chosen = ask(Fixed("manual", old_manual), Fixed("ecb", rate(effective_date=TODAY - datetime.timedelta(days=9))))

    assert chosen is old_manual
    with pytest.raises(StaleRateError):
        convert(Money.of("1", "USD"), to="EUR", rate=chosen, on=TODAY)


def test_a_future_dated_rate_is_skipped():
    future = manual(-1)

    assert ask(Fixed("manual", future), Fixed("ecb", rate())).source == "ecb:eurofxref"


def test_no_source_means_no_rate():
    assert ask(Fixed("a", None), Fixed("b", None)) is None
