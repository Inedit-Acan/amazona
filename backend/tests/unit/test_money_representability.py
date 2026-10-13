"""«Representable como Money» y «cabe en la columna» (M46, Commit 5c).

Una sola regla de representabilidad (la de `Money`) y una sola lectura de la capacidad de las columnas (la de su tipo
declarado). Ninguna es un máximo comercial ni fiscal.
"""

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.core.errors import ValidationError
from app.db.models.economic_analysis import EconomicAnalysis
from app.db.models.exchange_rate import ExchangeRate
from app.db.models.external_action import ExternalAction
from app.db.numeric_capacity import (
    INTEGER_MAX,
    INTEGER_MIN,
    ValueNotStorableError,
    fits_column,
    numeric_capacity,
    require_row_fits_storage,
)
from app.money.money import INTERNAL_PLACES, AmountNotRepresentableError, Money

APP = Path(__file__).resolve().parents[2] / "app"
LARGEST = Decimal("999999999999999999999999.9999")  # 24 cifras enteras + 4 decimales = 28 = precisión de Decimal


# ----------------------------------------------------------------------- Money.can_represent


@pytest.mark.parametrize(
    "amount", [0, 20.0, 0.0001, 0.00005, 1e20, 1e23, 9.999999999999998e23, LARGEST, Decimal("0.0001")]
)
def test_can_represent_says_yes_for_what_money_holds(amount):
    assert Money.can_represent(amount) is True


@pytest.mark.parametrize(
    "amount",
    [
        1e24,
        1e25,
        1e308,
        Decimal("1e24"),
        LARGEST + 1,
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_can_represent_says_no_for_what_money_cannot_hold_or_is_not_an_amount(amount):
    assert Money.can_represent(amount) is False


def test_can_represent_is_exactly_what_the_constructor_does():
    """No es una copia de la regla: si el constructor acepta un importe, `can_represent` también, y al revés."""
    for amount in (Decimal("5"), LARGEST, LARGEST + 1, Decimal("1e24"), Decimal("1e30")):
        try:
            Money(amount=amount, currency="EUR")
            constructed = True
        except AmountNotRepresentableError:
            constructed = False
        assert Money.can_represent(amount) is constructed


def test_a_finite_amount_too_large_is_a_validation_error_that_does_not_repeat_it():
    with pytest.raises(AmountNotRepresentableError) as caught:
        Money(amount=Decimal("1e30"), currency="EUR")

    assert isinstance(caught.value, ValidationError)
    assert "1e30" not in str(caught.value).lower() and "1E+30" not in str(caught.value)


def test_two_valid_amounts_whose_product_does_not_fit_fail_in_the_open():
    price = Money.of("500000000000000000000000", "EUR")  # 5e23: cabe

    with pytest.raises(AmountNotRepresentableError):
        price * 3  # 1.5e24: no cabe


def test_the_representable_range_comes_from_money_not_from_a_literal():
    """La consecuencia técnica (importes < 1e24 con precisión 28) se documenta, no se escribe en el código."""
    pattern = re.compile(r"1e\+?24|10\s*\*\*\s*24", re.IGNORECASE)
    offenders = [
        str(path.relative_to(APP)) for path in APP.rglob("*.py") if pattern.search(_code_without_comments(path))
    ]
    assert offenders == []
    assert INTERNAL_PLACES == 4  # si cambia, cambia lo representable y esta prueba obliga a releer la regla


def _code_without_comments(path: Path) -> str:
    """El código sin comentarios `#` ni docstrings: los documentos pueden nombrar 1e24; el código no."""
    text = re.sub(r'""".*?"""', "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


# ------------------------------------- InvalidOperation: solo la causa «importe demasiado grande» se traduce


def test_an_invalid_operation_that_is_not_an_oversized_amount_is_not_translated():
    """`sNaN` hace que `quantize` lance `InvalidOperation` y NO es un importe finito demasiado grande: sigue siendo
    un fallo visible, no un error de validación."""
    with pytest.raises(InvalidOperation):
        Money._quantize(Decimal("sNaN"), Decimal("0.0001"))


def test_only_the_oversized_finite_amount_is_translated():
    with pytest.raises(AmountNotRepresentableError):
        Money._quantize(Decimal("1e40"), Decimal("0.0001"))


def test_an_invalid_operation_from_elsewhere_inside_decimal_code_passes_through(monkeypatch):
    """Si algo interno lanza `InvalidOperation` al construir un `Money`, no se disfraza de validación."""

    def internal_bug(value, exponent):
        raise InvalidOperation("internal bug unrelated to the amount")

    monkeypatch.setattr(Money, "_quantize", staticmethod(internal_bug))

    with pytest.raises(InvalidOperation):
        Money(amount=Decimal("1"), currency="EUR")


# ---------------------------------------------------------------- capacidad de las columnas del modelo


def test_the_capacity_is_read_from_the_declared_columns():
    assert numeric_capacity(EconomicAnalysis.__table__.c.contribution_margin_per_unit) == Decimal("99999999.9999")
    assert numeric_capacity(ExternalAction.__table__.c.amount) == Decimal("9999999999.99")
    assert numeric_capacity(ExchangeRate.__table__.c.rate) == Decimal("9999999999.99999999")


def test_an_unbounded_column_has_no_capacity():
    assert numeric_capacity(EconomicAnalysis.__table__.c.sale_price) is None  # Float
    assert numeric_capacity(EconomicAnalysis.__table__.c.correlation_id) is None  # String


def test_a_value_fits_up_to_the_capacity_and_not_one_step_beyond():
    column = EconomicAnalysis.__table__.c.contribution_margin_per_unit

    assert fits_column(Decimal("99999999.9999"), column)
    assert fits_column(Decimal("-99999999.9999"), column)
    assert not fits_column(Decimal("100000000.0000"), column)
    assert not fits_column(Decimal("99999999.99995"), column)  # redondea a 100000000.0000
    assert fits_column(Decimal("99999999.99994"), column)  # redondea a 99999999.9999


def test_none_and_unbounded_types_always_fit_and_non_finite_never_do():
    column = EconomicAnalysis.__table__.c.contribution_margin_per_unit

    assert fits_column(None, column)
    assert fits_column(1e300, EconomicAnalysis.__table__.c.sale_price)
    assert not fits_column(Decimal("NaN"), column)
    assert not fits_column(float("inf"), column)


def test_an_integer_column_is_the_width_of_the_database_integer():
    column = EconomicAnalysis.__table__.c.units_per_order

    assert fits_column(INTEGER_MAX, column) and fits_column(INTEGER_MIN, column)
    assert not fits_column(INTEGER_MAX + 1, column)
    assert not fits_column(INTEGER_MIN - 1, column)


def _analysis(**overrides) -> EconomicAnalysis:
    fields = dict(
        product_id="p",
        supplier_quote_id="q",
        sale_price=20.0,
        monthly_fixed_costs=500.0,
        recommendation="GO",
        confidence=0.5,
        correlation_id="c",
        data={},
    )
    return EconomicAnalysis(**(fields | overrides))


def test_a_row_that_fits_passes_and_one_that_does_not_fails_without_naming_internals():
    require_row_fits_storage(_analysis(contribution_margin_per_unit=Decimal("99999999.9999"), units_per_order=3))

    with pytest.raises(ValueNotStorableError) as caught:
        require_row_fits_storage(_analysis(contribution_margin_per_unit=Decimal("100000000")))

    assert isinstance(caught.value, ValidationError)
    message = str(caught.value)
    assert "contribution" not in message and "economic_analyses" not in message and "Numeric" not in message


def test_an_integer_that_does_not_fit_the_column_is_refused_before_writing():
    with pytest.raises(ValueNotStorableError):
        require_row_fits_storage(_analysis(units_per_order=INTEGER_MAX + 1))


def test_the_column_types_this_relies_on_are_numeric_and_integer():
    """Si alguien cambia una columna a `Float`, la comprobación deja de acotarla: esta prueba lo hace visible."""
    assert isinstance(EconomicAnalysis.__table__.c.contribution_margin_per_unit.type, sa.Numeric)
    assert isinstance(EconomicAnalysis.__table__.c.units_per_order.type, sa.Integer)
