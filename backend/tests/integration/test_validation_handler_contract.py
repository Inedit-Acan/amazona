"""El manejador global de `RequestValidationError`, de extremo a extremo (M46, Commit 5c).

Arregla una sola cosa —un `NaN`/`Infinity` repetido en el cuerpo de un 422 lo convertía en un 500— y demuestra aquí
que no altera el contrato de lo que ya funcionaba, que no captura otros errores y que no devuelve cuerpos enormes.
"""

import json

from numeric_boundary_support import INF, NAN, assert_clean_422, post, rows

from app.api.validation_body import MAX_ECHOED_CHARS

RESEARCH = "/api/research/runs"


def test_an_ordinary_schema_error_keeps_the_exact_shape_fastapi_gives(boundary_world):
    client, _ = boundary_world

    response = post(client, RESEARCH, {"category": "home", "max_results": 0})

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "greater_than_equal",
                "loc": ["body", "max_results"],
                "msg": "Input should be greater than or equal to 1",
                "input": 0,
                "ctx": {"ge": 1},
            }
        ]
    }


def test_a_missing_field_and_a_wrong_type_keep_their_shape(boundary_world):
    client, _ = boundary_world

    missing = post(client, RESEARCH, {})
    wrong = post(client, RESEARCH, {"category": 5})

    assert missing.json()["detail"][0]["type"] == "missing"
    assert missing.json()["detail"][0]["loc"] == ["body", "category"]
    assert wrong.json()["detail"][0]["type"] == "string_type"
    assert wrong.json()["detail"][0]["input"] == 5


def test_a_nan_echoed_in_a_422_used_to_break_the_response_and_is_now_text(boundary_world):
    """Antes: 500. `max_results` es un entero con restricción: un `NaN` falla y el error repite el `NaN`."""
    client, session_factory = boundary_world
    before = rows(session_factory)

    for value, text in ((NAN, "NaN"), (INF, "Infinity"), (-INF, "-Infinity")):
        response = post(client, RESEARCH, {"category": "home", "max_results": value})

        assert_clean_422(response, "max_results")
        error = response.json()["detail"][0]
        assert error["input"] == text
        assert error["loc"] == ["body", "max_results"] and error["type"] and error["msg"]
    assert rows(session_factory) == before


def test_a_huge_echo_is_bounded(boundary_world):
    client, _ = boundary_world

    response = post(client, RESEARCH, {"category": ["x" * 50_000] * 40})

    assert_clean_422(response, "category")
    assert len(response.content) < 4_000
    assert "not echoed" in json.dumps(response.json())


def test_a_long_string_in_a_wrong_type_is_cut_not_reflected_in_full(boundary_world):
    client, _ = boundary_world

    response = post(client, RESEARCH, {"category": "home", "max_results": "y" * 100_000})

    assert_clean_422(response, "max_results")
    echoed = response.json()["detail"][0]["input"]
    assert isinstance(echoed, str) and len(echoed) <= MAX_ECHOED_CHARS + 3


def test_the_other_handlers_are_untouched(boundary_world):
    client, _ = boundary_world

    missing = client.get("/api/pipeline/runs/does-not-exist")
    domain = post(client, "/api/exchange-rates", {"base_currency": "USD", "quote_currency": "USD", "rate": "0.9",
                                                  "effective_date": "2026-01-01"})

    assert missing.status_code == 404 and set(missing.json()) == {"detail"}
    assert isinstance(missing.json()["detail"], str)
    assert domain.status_code == 422 and isinstance(domain.json()["detail"], str)  # ValidationError de dominio
