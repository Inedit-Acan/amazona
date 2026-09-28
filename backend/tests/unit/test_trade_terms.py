"""Incoterms y monedas: el vocabulario de una cotización (Milestone 39)."""

import pytest

from app.sourcing.trade_terms import (
    ACCOUNTING_CURRENCY,
    INCOTERMS,
    UnknownCurrencyError,
    UnknownIncotermError,
    comparable,
    currency_for,
    incoterm_for,
)


def test_the_eleven_incoterms_2020_are_there_and_no_more():
    assert set(INCOTERMS) == {
        "EXW",
        "FCA",
        "FAS",
        "FOB",
        "CFR",
        "CIF",
        "CPT",
        "CIP",
        "DAP",
        "DPU",
        "DDP",
    }


def test_an_incoterm_says_how_far_the_price_reaches():
    """Es la pregunta que decide si el coste logístico hay que sumarlo o ya
    está dentro."""
    assert incoterm_for("EXW").includes_main_carriage is False
    assert incoterm_for("DDP").includes_main_carriage is True
    assert incoterm_for("DDP").includes_import_duties is True
    assert incoterm_for("DAP").includes_import_duties is False


def test_case_and_spacing_do_not_invent_a_new_incoterm():
    assert incoterm_for(" ddp ").code == "DDP"


def test_a_term_that_does_not_exist_is_refused_not_stored():
    """Un `DPP` tecleado con un dedo torcido sería una condición pactada que
    nadie pactó."""
    with pytest.raises(UnknownIncotermError, match="Incoterms 2020"):
        incoterm_for("DPP")


def test_a_currency_outside_the_catalogue_is_refused():
    with pytest.raises(UnknownCurrencyError, match="known trade currency"):
        currency_for("XYZ")


def test_the_catalogue_is_extended_with_one_line():
    """Extensible a propósito, al contrario que los Incoterms."""
    assert currency_for("eur") == "euro"
    assert currency_for("USD")


def test_two_prices_in_the_same_currency_are_comparable():
    assert comparable("EUR", "eur") is True


def test_two_prices_in_different_currencies_are_not():
    assert comparable("EUR", "USD") is False


def test_two_undeclared_currencies_are_not_comparable_either():
    """Que nadie haya dicho en qué moneda está un precio no permite suponer que
    están en la misma."""
    assert comparable(None, None) is False
    assert comparable(None, "EUR") is False


def test_the_accounting_currency_is_declared_and_never_converted_into():
    assert ACCOUNTING_CURRENCY == "EUR"
