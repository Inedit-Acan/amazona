"""Dinero exacto y aritmética que se niega a mezclar monedas (Milestone 40)."""

from decimal import Decimal

import pytest

from app.money.money import (
    DISPLAY_PLACES,
    INTERNAL_PLACES,
    CurrencyMismatchError,
    Money,
    total,
)


def test_two_currencies_cannot_be_subtracted():
    """Es la salvaguarda que el Milestone 39 no tenía: allí la regla vivía en
    prosa y el código podía saltársela."""
    with pytest.raises(CurrencyMismatchError, match="exchange rate of 1.00"):
        Money.of("20", "EUR") - Money.of("4.20", "USD")


def test_two_currencies_cannot_be_added_or_compared():
    with pytest.raises(CurrencyMismatchError):
        Money.of("1", "EUR") + Money.of("1", "USD")
    with pytest.raises(CurrencyMismatchError):
        Money.of("1", "EUR") < Money.of("1", "USD")


def test_the_same_currency_operates_normally():
    assert (Money.of("20", "EUR") - Money.of("6.05", "EUR")).amount == Decimal("13.9500")


def test_decimal_arithmetic_is_exact_where_float_is_not():
    """`0.1 + 0.2` vale 0,30000000000000004 en coma flotante. Un céntimo por
    unidad son cuarenta euros en un pedido de cuatro mil."""
    assert 0.1 + 0.2 != 0.3
    assert (Money.of("0.1", "EUR") + Money.of("0.2", "EUR")).amount == Decimal("0.3000")


def test_a_float_cannot_enter_through_the_front_door():
    """`Money.of(0.1, "EUR")` parece inofensivo y arrastra el error binario
    desde el primer carácter."""
    with pytest.raises(ValueError, match="from_legacy_float"):
        Money.of(0.1, "EUR")  # type: ignore[arg-type]


def test_the_legacy_boundary_converts_by_the_decimal_representation():
    """`Decimal(0.1)` es 0,1000000000000000055511151231257827…;
    `Decimal(str(0.1))` es 0,1. La diferencia se acumula."""
    assert Money.from_legacy_float(0.1, "EUR").amount == Decimal("0.1000")
    assert Money.from_legacy_float(4.2, "EUR").amount == Decimal("4.2000")


def test_internal_precision_is_four_places():
    """Un coste logístico por unidad de 0,0042 € es real; a dos decimales sería
    cero."""
    assert INTERNAL_PLACES == 4
    assert Money.of("0.0042", "EUR").amount == Decimal("0.0042")
    assert not Money.of("0.0042", "EUR").is_zero


def test_display_rounding_is_half_up_and_only_at_the_end():
    """`ROUND_HALF_UP` y no el `ROUND_HALF_EVEN` de Python: es lo que hace una
    factura y lo que espera quien comprueba una cuenta a mano."""
    assert DISPLAY_PLACES == 2
    assert Money.of("0.125", "EUR").rounded().amount == Decimal("0.13")
    assert Money.of("0.135", "EUR").rounded().amount == Decimal("0.14")


def test_rounding_between_two_sums_is_what_the_type_avoids():
    """Sumar tres céntimos y medio tres veces da 10,5 y no 11: redondear a
    mitad de camino mete el error que se quería evitar."""
    pieces = [Money.of("0.035", "EUR")] * 3
    at_the_end = total(pieces, currency="EUR").rounded().amount
    rounded_first = sum((p.rounded().amount for p in pieces), Decimal(0))

    assert at_the_end == Decimal("0.11")
    assert rounded_first == Decimal("0.12")


def test_money_cannot_be_multiplied_by_money():
    """Euros por euros no son euros, y el tipo no sabría qué serían."""
    with pytest.raises(TypeError):
        Money.of("2", "EUR") * Money.of("3", "EUR")  # type: ignore[operator]


def test_a_scalar_factor_cannot_be_a_float_either():
    with pytest.raises(ValueError, match="Decimal"):
        Money.of("2", "EUR") * 1.5  # type: ignore[operator]


def test_multiplying_by_an_integer_is_how_an_order_is_built():
    assert (Money.of("6.40", "EUR") * 3).amount == Decimal("19.2000")


def test_a_currency_outside_the_catalogue_is_refused():
    with pytest.raises(ValueError, match="known trade currency"):
        Money.of("1", "XYZ")


def test_zero_is_declared_not_assumed():
    """Quien usa `Money.zero` está afirmando que el importe es cero. No es lo
    mismo que un coste desconocido, y por eso hay que escribirlo."""
    assert Money.zero("EUR").is_zero


def test_total_of_nothing_needs_a_currency():
    """Deducir la moneda del primer elemento daría un resultado distinto según
    el orden, y ninguno con una lista vacía."""
    assert total([], currency="EUR") == Money.zero("EUR")


def test_a_ratio_has_no_currency():
    margin = Money.of("13.95", "EUR").ratio_to(Money.of("20", "EUR"))

    assert isinstance(margin, Decimal)
    assert margin == Decimal("13.9500") / Decimal("20.0000")
