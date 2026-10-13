"""Fronteras numéricas de `POST /api/pipeline/runs` (M46, Commit 5c).

`sale_price` y `monthly_fixed_costs` tienen la misma semántica que en `POST /api/economics/runs` (el pipeline se los
pasa tal cual a `run_analysis`) y pasan por **las mismas** precondiciones: aquí se demuestra la paridad, valor a valor.
`daily_budget` (importe de gasto) y `max_results` (1..20, como research y sourcing) son solo del pipeline.

Antes el pipeline no validaba nada: `NaN`, un precio de 0, un presupuesto negativo o `1e308` se encolaban (202) y el
worker fallaba después; con un presupuesto que no cabía en su columna dejaba el run atascado en `RUNNING`
(`PendingRollbackError`). Ahora el valor que el worker no sabe procesar **no llega al worker**.
"""

import decimal

import pytest
from numeric_boundary_support import INF, NAN, assert_clean_422, drain, post, product_and_quote, rows
from sqlalchemy import select

from app.api.numeric_inputs import MAX_RESULTS_MAX, MAX_RESULTS_MIN, MIN_SALE_PRICE
from app.db.models.external_action import ExternalAction
from app.db.models.pipeline_run import PipelineRun
from app.db.numeric_capacity import numeric_capacity

URL = "/api/pipeline/runs"
BODY = {"category": "home", "sale_price": 50.0, "destination_region": "mexico"}

#: campo -> acepta cero
MONEY_FIELDS = {"sale_price": False, "monthly_fixed_costs": True, "daily_budget": True}

#: El mayor presupuesto diario que cabe donde se guarda el gasto (`Numeric(12, 2)`).
SPEND_CAPACITY = float(numeric_capacity(ExternalAction.__table__.c.amount))


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


MATRIX = [(field, label, value) for field in MONEY_FIELDS for label, value in _cases(field)]


def _accepted(field: str, label: str) -> bool:
    if label == "zero":
        return MONEY_FIELDS[field]
    return label in ("normal", "minimum")


def _statuses(session_factory) -> list[str]:
    with session_factory() as session:
        return [run.status for run in session.scalars(select(PipelineRun))]


@pytest.mark.parametrize("field, label, value", MATRIX, ids=[f"{f}-{label}" for f, label, _ in MATRIX])
def test_the_money_boundary_matrix(boundary_world, field, label, value):
    client, session_factory = boundary_world
    before = rows(session_factory)

    response = post(client, URL, BODY | {field: value})

    if _accepted(field, label):
        assert response.status_code == 202, response.text
        return
    assert_clean_422(response, field)
    assert rows(session_factory) == before  # ni run, ni pasos, ni trabajo en cola


@pytest.mark.parametrize(
    "value, accepted",
    [
        (MAX_RESULTS_MIN, True),
        (3, True),
        (MAX_RESULTS_MAX, True),
        (0, False),  # K
        (-1, False),
        (MAX_RESULTS_MAX + 1, False),  # L
        (10**30, False),
        (3.0, False),
        (3.5, False),
        (True, False),
        (False, False),
        ("3", False),
        ("", False),
        (None, False),
        ([3], False),
        ({"a": 1}, False),
        (NAN, False),
        (INF, False),
        (-INF, False),
    ],
)
def test_max_results_is_one_to_twenty_and_a_strict_integer(boundary_world, value, accepted):
    client, session_factory = boundary_world
    before = rows(session_factory)

    response = post(client, URL, BODY | {"max_results": value})

    if accepted:
        assert response.status_code == 202, response.text
        return
    assert_clean_422(response, "max_results")
    assert rows(session_factory) == before


def test_max_results_has_one_source_of_truth_shared_with_research_and_sourcing(boundary_world):
    client, _ = boundary_world

    assert (MAX_RESULTS_MIN, MAX_RESULTS_MAX) == (1, 20)
    for url, body in (
        ("/api/research/runs", {"category": "home"}),
        ("/api/sourcing/runs", {"product_id": "x", "category": "home", "destination_region": "mexico"}),
    ):
        assert_clean_422(post(client, url, body | {"max_results": MAX_RESULTS_MAX + 1}), "max_results")
        assert_clean_422(post(client, url, body | {"max_results": MAX_RESULTS_MIN - 1}), "max_results")


# --------------------------------------------------------------------------- daily_budget (gasto)


def test_I_the_daily_budget_boundary_is_what_the_spend_column_holds(boundary_world):
    """Antes: un presupuesto por encima de `Numeric(12, 2)` se encolaba (202) y en PostgreSQL el worker fallaba con
    `PendingRollbackError`, dejando el run en `RUNNING`."""
    client, session_factory = boundary_world
    before = rows(session_factory)

    inside = post(client, URL, BODY | {"daily_budget": SPEND_CAPACITY})
    just_above = post(client, URL, BODY | {"daily_budget": SPEND_CAPACITY + 0.01})
    far_above = post(client, URL, BODY | {"daily_budget": 1e15})

    assert inside.status_code == 202
    assert_clean_422(just_above, "daily_budget", named=True)
    assert_clean_422(far_above, "daily_budget", named=True)
    assert "stored as spend" in just_above.json()["detail"]
    assert rows(session_factory)["pipeline_runs"] == before["pipeline_runs"] + 1  # solo la válida


@pytest.mark.parametrize("budget", [NAN, INF, -INF, -1, -1e308, 1e308, SPEND_CAPACITY + 0.01, 1e15])
def test_I_an_invalid_daily_budget_never_reaches_the_worker(boundary_world, budget):
    client, session_factory = boundary_world
    drain(session_factory)  # el planificador del worker crea sus trabajos periódicos la primera vez: fuera de la medida
    before = rows(session_factory)

    response = post(client, URL, BODY | {"daily_budget": budget})
    drain(session_factory)

    assert_clean_422(response, "daily_budget", named=True)
    assert rows(session_factory) == before
    assert _statuses(session_factory) == []  # ningún run, ni en RUNNING ni en ningún otro estado


def test_no_run_is_left_running_after_invalid_and_valid_requests_are_mixed(boundary_world):
    client, session_factory = boundary_world
    post(client, URL, BODY | {"daily_budget": NAN})
    post(client, URL, BODY | {"daily_budget": 1e308})
    post(client, URL, BODY | {"sale_price": 0})
    valid = post(client, URL, BODY | {"daily_budget": 0})
    at_the_limit = post(client, URL, BODY | {"daily_budget": SPEND_CAPACITY})
    drain(session_factory)
    drain(session_factory)

    assert valid.status_code == at_the_limit.status_code == 202
    statuses = _statuses(session_factory)
    assert len(statuses) == 2
    assert "RUNNING" not in statuses and "QUEUED" not in statuses
    assert statuses == ["COMPLETED", "COMPLETED"]


# ------------------------------------------------------------------ paridad con economics, valor a valor


@pytest.mark.parametrize("field", ["sale_price", "monthly_fixed_costs"])
@pytest.mark.parametrize(
    "value",
    [0, -1, NAN, INF, -INF, 1e24, 1e308, -1e308, True, False, "20", "", None, [1], {"a": 1}],
    ids=[
        "0", "-1", "nan", "inf", "-inf", "1e24", "1e308", "-1e308",
        "true", "false", "str", "empty", "null", "list", "obj",
    ],
)
def test_the_shared_fields_get_exactly_the_same_answer_from_economics_and_the_pipeline(boundary_world, field, value):
    client, _ = boundary_world
    product_id, quote_id = product_and_quote(client)
    economics_body = {"product_id": product_id, "supplier_quote_id": quote_id, "sale_price": 20.0, "units_per_order": 1}

    pipeline = post(client, URL, BODY | {field: value})
    economics = post(client, "/api/economics/runs", economics_body | {field: value})

    # El cuerpo es idéntico: mismo tipo de error, mismo `loc` (`["body", campo]`) y, en las reglas de dominio, el mismo
    # mensaje.
    if economics.status_code == 201:  # los casos aceptados en ambos
        assert pipeline.status_code == 202
        return
    assert pipeline.status_code == economics.status_code == 422
    assert pipeline.json() == economics.json()


def test_the_pipeline_uses_the_same_precondition_function_as_economics():
    import inspect

    from app.api import economics, pipeline

    assert "require_amounts(" in inspect.getsource(economics.create_economic_analysis_run)
    assert "require_amounts(" in inspect.getsource(pipeline.create_pipeline_run)


# --------------------------------------------------------------- orden, determinismo, fallos internos


def test_two_invalid_calls_in_a_row_are_deterministic_and_the_next_valid_one_runs_to_completion(boundary_world):
    client, session_factory = boundary_world
    before = rows(session_factory)

    first = post(client, URL, BODY | {"daily_budget": NAN})
    second = post(client, URL, BODY | {"daily_budget": NAN})

    assert_clean_422(first, "daily_budget", named=True)
    assert first.json() == second.json()
    assert rows(session_factory) == before

    valid = post(client, URL, BODY)
    assert valid.status_code == 202
    drain(session_factory)
    run = client.get(f"/api/pipeline/runs/{valid.json()['correlation_id']}").json()
    assert run["status"] == "COMPLETED"


@pytest.mark.parametrize(
    "failure", [RuntimeError("internal secret detail"), decimal.InvalidOperation("internal decimal bug")]
)
def test_M_an_internal_failure_after_valid_input_is_still_a_500_and_never_leaks(boundary_world, monkeypatch, failure):
    client, session_factory = boundary_world
    before = rows(session_factory)

    def boom(self, *args, **kwargs):
        raise failure

    monkeypatch.setattr("app.pipeline.service.PipelineOrchestrator.enqueue_or_replay", boom)

    response = post(client, URL, BODY)

    assert response.status_code == 500
    assert "internal" not in response.text
    assert rows(session_factory) == before
