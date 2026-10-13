"""Fronteras numéricas de `POST /api/economics/runs` (M46, Commit 5c).

Una matriz por familia de campo (válido, cero, mínimo, negativo, `NaN`, `±Infinity`, extremo, `bool`, cadena numérica,
`null`, lista, objeto) y los casos que antes producían un 500 o un resultado silencioso:

  E. un valor enorme no representable        F. un desbordamiento derivado (precio × unidades)
  G. un resultado monetario que no cabe       H. `monthly_unit_sales_base` que daba ingresos `null` sin avisar

Todo rechazo es un 422 con cuerpo estable, sin traza, sin ninguna fila nueva y sin dejar nada a medias. Un fallo interno
de verdad (`RuntimeError`, `decimal.InvalidOperation`) sigue siendo un 500.
"""

import decimal

import pytest
from numeric_boundary_support import INF, NAN, assert_clean_422, post, product_and_quote, rows

from app.api.numeric_inputs import MIN_SALE_PRICE

URL = "/api/economics/runs"

#: campo -> (acepta cero, acepta null)
FAMILIES = {
    "sale_price": (False, False),
    "monthly_fixed_costs": (True, False),
    "monthly_unit_sales_base": (True, True),
    "payment_cost_per_unit": (True, True),
    "other_variable_cost_per_unit": (True, True),
}


def _cases(field: str) -> list[tuple[str, object]]:
    minimum = MIN_SALE_PRICE if field == "sale_price" else 0.0001
    return [
        ("normal", 20.0),
        ("zero", 0),
        ("minimum", minimum),
        ("negative", -1),
        ("nan", NAN),
        ("inf", INF),
        ("-inf", -INF),
        ("extreme", 1e308),
        ("-extreme", -1e308),
        ("bool_true", True),
        ("bool_false", False),
        ("numeric_string", "20"),
        ("empty_string", ""),
        ("null", None),
        ("list", [20]),
        ("object", {"a": 1}),
    ]


MATRIX = [(field, label, value) for field in FAMILIES for label, value in _cases(field)]


def _accepted(field: str, label: str) -> bool:
    accepts_zero, accepts_null = FAMILIES[field]
    if label == "zero":
        return accepts_zero
    if label == "null":
        return accepts_null
    return label in ("normal", "minimum")


def _body(product_id: str, quote_id: str, **overrides) -> dict:
    base = {"product_id": product_id, "supplier_quote_id": quote_id, "sale_price": 20.0, "units_per_order": 1}
    return base | overrides


@pytest.mark.parametrize("field, label, value", MATRIX, ids=[f"{f}-{label}" for f, label, _ in MATRIX])
def test_the_boundary_matrix(boundary_world, field, label, value):
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    response = post(client, URL, _body(product_id, quote_id, **{field: value}))

    if _accepted(field, label):
        assert response.status_code == 201, response.text
        return
    assert_clean_422(response, field)
    assert rows(session_factory) == before


# ------------------------------------------------------------- units_per_order (cantidad entera)


@pytest.mark.parametrize(
    "value, accepted",
    [
        (1, True),
        (3, True),
        (None, True),
        (0, False),
        (-1, False),
        (3.0, False),  # un entero estricto: 3.0 no es un `int` en el contrato
        (3.5, False),
        (True, False),
        (False, False),
        ("3", False),
        ("", False),
        ([3], False),
        ({"a": 1}, False),
        (NAN, False),
        (INF, False),
        (-INF, False),
        (10**30, False),  # F: el producto con el precio no cabe como Money
        (2**31, False),  # no cabe en un INTEGER de la base de datos
    ],
)
def test_units_per_order_matrix(boundary_world, value, accepted):
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    response = post(client, URL, _body(product_id, quote_id, units_per_order=value))

    if accepted:
        assert response.status_code == 201, response.text
        return
    assert_clean_422(response, "units_per_order")
    assert rows(session_factory) == before


# --------------------------------------------------------------- E, F, G: magnitudes que no caben


@pytest.mark.parametrize("field", ["sale_price", "monthly_fixed_costs", "payment_cost_per_unit"])
def test_E_a_huge_amount_that_money_cannot_represent_is_a_422_and_writes_nothing(boundary_world, field):
    """Antes: `decimal.InvalidOperation` suelto ⇒ 500."""
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    response = post(client, URL, _body(product_id, quote_id, **{field: 1e24}))

    assert_clean_422(response, field)
    assert rows(session_factory) == before


def test_F_two_valid_amounts_whose_product_overflows_are_a_422_and_write_nothing(boundary_world):
    """Un precio de 5e23 cabe; con tres unidades por pedido el importe del pedido (1,5e24) no. Antes: 500."""
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    alone = post(client, URL, _body(product_id, quote_id, sale_price=5e23, units_per_order=1))
    together = post(client, URL, _body(product_id, quote_id, sale_price=5e23, units_per_order=3))

    assert_clean_422(alone)  # el precio solo ya produce un margen que la columna no guarda: G
    assert_clean_422(together)
    assert rows(session_factory) == before


def test_G_a_monetary_result_that_does_not_fit_what_is_stored_is_a_422_before_writing(boundary_world):
    """`Money` representa 1e9, pero el margen por unidad se guarda en `Numeric(12, 4)` (ocho cifras enteras): en
    PostgreSQL era un 500 al escribir. Aquí se rechaza antes, con el mismo resultado en SQLite y en PostgreSQL."""
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    response = post(client, URL, _body(product_id, quote_id, sale_price=2e8))

    assert_clean_422(response)
    assert "too large to be stored" in response.json()["detail"]
    assert "numeric" not in response.text.lower() and "economic_analyses" not in response.text
    assert rows(session_factory) == before


def test_G_the_boundary_is_exact_what_fits_is_accepted(boundary_world):
    client, _ = boundary_world
    product_id, quote_id = product_and_quote(client)

    inside = post(client, URL, _body(product_id, quote_id, sale_price=9.9e7))
    outside = post(client, URL, _body(product_id, quote_id, sale_price=2e8))

    assert inside.status_code == 201
    assert outside.status_code == 422


# ------------------------------------------------------ H: el ingreso nulo en silencio ya no existe


def test_H_a_huge_but_finite_sales_volume_fails_in_the_open_instead_of_returning_null_revenue(boundary_world):
    """Antes: `monthly_unit_sales_base = 1e308` ⇒ 201 con `monthly_revenue = null` y `monthly_profit = null` dentro
    de un análisis «con éxito» (el `inf` de coma flotante se serializaba como `null`). Ahora: 422 y nada guardado."""
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    response = post(client, URL, _body(product_id, quote_id, monthly_unit_sales_base=1e308))

    assert_clean_422(response, "monthly_unit_sales_base")
    assert "cannot be represented as money" in response.json()["detail"]
    assert rows(session_factory) == before


def test_H_every_scenario_is_checked_not_just_the_base_one(boundary_world):
    """Con un volumen base de 4e22 y un precio de 20, el escenario base (8e23) cabe y el optimista (1,04e24) no."""
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    response = post(client, URL, _body(product_id, quote_id, monthly_unit_sales_base=4e22))

    assert_clean_422(response)
    assert "optimistic" in response.json()["detail"]
    assert rows(session_factory) == before


def test_H_a_large_volume_that_money_can_represent_gives_real_numbers_not_nulls(boundary_world):
    client, _ = boundary_world
    product_id, quote_id = product_and_quote(client)

    response = post(client, URL, _body(product_id, quote_id, monthly_unit_sales_base=1e20))

    assert response.status_code == 201
    for scenario in response.json()["data"]["scenarios"].values():
        assert isinstance(scenario["monthly_revenue"], float)
        assert isinstance(scenario["monthly_profit"], float)
        assert isinstance(scenario["monthly_unit_sales"], float)


# ----------------------------------------------------------------- orden, determinismo, fallos internos


def test_several_wrong_fields_are_reported_together_by_the_shared_precondition(boundary_world):
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    response = post(
        client, URL, _body(product_id, quote_id, sale_price=0, monthly_fixed_costs=-1, monthly_unit_sales_base=-5)
    )

    assert_clean_422(response, "sale_price", "monthly_fixed_costs", "monthly_unit_sales_base", named=True)
    assert rows(session_factory) == before


def test_two_invalid_calls_in_a_row_are_deterministic_and_the_next_valid_one_works(boundary_world):
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    first = post(client, URL, _body(product_id, quote_id, sale_price=NAN))
    second = post(client, URL, _body(product_id, quote_id, sale_price=NAN))

    assert_clean_422(first, "sale_price", named=True)
    assert first.status_code == second.status_code and first.json() == second.json()
    assert rows(session_factory) == before

    valid = post(client, URL, _body(product_id, quote_id))
    assert valid.status_code == 201
    assert rows(session_factory)["economic_analyses"] == before["economic_analyses"] + 1


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("internal secret detail"),
        decimal.InvalidOperation("internal decimal bug"),
        OverflowError("internal"),
    ],
)
def test_M_an_internal_failure_after_valid_input_is_still_a_500_and_never_leaks(boundary_world, monkeypatch, failure):
    """Ni siquiera un `InvalidOperation` interno se disfraza de error del cliente: solo el importe finito demasiado
    grande de `Money` es una propiedad de la entrada."""
    client, session_factory = boundary_world
    product_id, quote_id = product_and_quote(client)
    before = rows(session_factory)

    def boom(self, **kwargs):
        raise failure

    monkeypatch.setattr("app.economics.service.EconomicAnalysisService.run_analysis", boom)

    response = post(client, URL, _body(product_id, quote_id))

    assert response.status_code == 500
    assert "internal" not in response.text
    assert type(failure).__name__ not in response.text
    assert rows(session_factory) == before
