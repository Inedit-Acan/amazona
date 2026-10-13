"""El cuerpo de un 422 de esquema no puede romper al serializarse y no cambia por accidente (M46, Commit 5c).

El manejador global de `RequestValidationError` conserva el contrato de FastAPI (422, `{"detail": [...]}`, mismos
`type`, `loc`, `msg`, `ctx`) y solo sanea `input`/`ctx`: un `NaN`/`Infinity` pasa a texto y un eco enorme se acota.
Estas pruebas demuestran las dos mitades: que arregla lo roto y que no toca lo que ya funcionaba.
"""

import asyncio
import json

import pytest
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, StrictFloat, ValidationError
from starlette.requests import Request

from app.api.validation_body import MAX_ECHOED_CHARS, MAX_ECHOED_JSON_CHARS, safe_validation_errors
from app.main import request_validation_handler

NAN, INF = float("nan"), float("inf")


class Sample(BaseModel):
    price: StrictFloat = Field(ge=0.5)
    count: int = Field(default=1, ge=1, le=20)
    name: str = "x"
    tags: list[str] = []
    when: float | None = None


def _errors(**payload) -> list[dict]:
    try:
        Sample(**payload)
    except ValidationError as exc:
        return exc.errors()
    raise AssertionError("expected a validation error")


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _bodies(errors: list[dict]) -> tuple[dict, dict]:
    """El cuerpo del manejador por defecto de FastAPI y el nuestro, para los mismos errores."""
    exc = RequestValidationError(errors)
    default = asyncio.run(request_validation_exception_handler(_request(), exc))
    ours = asyncio.run(request_validation_handler(_request(), exc))
    assert default.status_code == ours.status_code == 422
    return json.loads(default.body), json.loads(ours.body)


# --------------------------------------------------- lo que ya funcionaba no cambia (regresión de contrato)


@pytest.mark.parametrize(
    "payload",
    [
        {"price": 0.1},  # greater_than_equal
        {"price": "abc"},  # float_type
        {"price": None},
        {"price": True},
        {"price": [1]},
        {"price": 1.0, "count": 0},
        {"price": 1.0, "count": 21},
        {"price": 1.0, "count": "abc"},
        {"price": 1.0, "count": 3.5},
        {"price": 1.0, "name": 5},
        {"price": 1.0, "tags": "x"},
        {"price": 1.0, "tags": [1, 2]},
        {"count": 3},  # campo obligatorio ausente
        {"price": 0.1, "count": 0, "name": 5},  # varios errores a la vez, en orden
    ],
)
def test_ordinary_schema_errors_are_byte_for_byte_the_ones_fastapi_gives(payload):
    default, ours = _bodies(_errors(**payload))

    assert ours == default


def test_the_error_keeps_type_loc_msg_input_and_ctx():
    default, ours = _bodies(_errors(price=0.1))
    error = ours["detail"][0]

    assert error["type"] == "greater_than_equal"
    assert error["loc"] == ["price"]
    assert "greater than or equal to 0.5" in error["msg"]
    assert error["input"] == 0.1
    assert error["ctx"] == {"ge": 0.5}
    assert ours == default


# ------------------------------------------------------------------------- lo que estaba roto: NaN / Infinity


@pytest.mark.parametrize("value, text", [(NAN, "NaN"), (INF, "Infinity"), (-INF, "-Infinity")])
def test_a_non_finite_echo_is_written_as_text_instead_of_breaking_the_response(value, text):
    errors = _errors(price=1.0, count=value)  # un float no entero ⇒ error con `input` no finito
    exc = RequestValidationError(errors)

    # Lo que pasaba: el manejador por defecto no puede construir la respuesta (JSON no escribe NaN) ⇒ 500.
    with pytest.raises(ValueError):
        asyncio.run(request_validation_exception_handler(_request(), exc))

    ours = asyncio.run(request_validation_handler(_request(), exc))
    body = json.loads(ours.body, parse_constant=_reject_constant)
    assert ours.status_code == 422
    assert body["detail"][0]["input"] == text
    assert body["detail"][0]["loc"] == ["count"]
    assert body["detail"][0]["type"] == errors[0]["type"]
    assert body["detail"][0]["msg"] == errors[0]["msg"]


def _reject_constant(name: str):
    raise AssertionError(f"the body contains the non-JSON constant {name}")


def test_a_non_finite_inside_a_container_or_ctx_is_also_written_as_text():
    sanitised = safe_validation_errors(
        [{"type": "x", "loc": ["a"], "msg": "m", "input": [1.0, NAN, {"k": -INF}], "ctx": {"limit": INF}}]
    )

    assert sanitised == [
        {"type": "x", "loc": ["a"], "msg": "m", "input": [1.0, "NaN", {"k": "-Infinity"}], "ctx": {"limit": "Infinity"}}
    ]
    json.dumps(sanitised, allow_nan=False)


def test_only_input_and_ctx_are_touched():
    original = [{"type": "t", "loc": ["a", 0], "msg": "message", "url": "https://x", "input": NAN, "ctx": {}}]

    sanitised = safe_validation_errors(original)

    assert sanitised[0]["type"] == "t" and sanitised[0]["loc"] == ["a", 0]
    assert sanitised[0]["msg"] == "message" and sanitised[0]["url"] == "https://x"
    assert original[0]["input"] is NAN or original[0]["input"] != original[0]["input"]  # no muta el original


# ---------------------------------------------------------------------------- no refleja cuerpos enormes


def test_a_long_string_echo_is_cut_and_a_normal_one_is_not():
    short = "x" * MAX_ECHOED_CHARS
    long = "x" * (MAX_ECHOED_CHARS * 40)

    assert safe_validation_errors([{"input": short}])[0]["input"] == short
    cut = safe_validation_errors([{"input": long}])[0]["input"]
    assert len(cut) < len(long) and len(cut) <= MAX_ECHOED_CHARS + 3 and cut.startswith("x" * MAX_ECHOED_CHARS)


def test_a_huge_container_echo_is_replaced_by_a_mark_and_a_small_one_is_kept():
    small = {"a": 1, "b": [1, 2, 3]}
    huge = list(range(MAX_ECHOED_JSON_CHARS))

    assert safe_validation_errors([{"input": small}])[0]["input"] == small
    marked = safe_validation_errors([{"input": huge}])[0]["input"]
    assert isinstance(marked, str) and "not echoed" in marked and len(marked) < 100


def test_a_normal_error_is_not_cut_or_marked():
    default, ours = _bodies(_errors(price=1.0, name=5))

    assert ours == default


# ------------------------------------------------------------- no captura nada más, no devuelve trazas


def test_the_handler_is_registered_only_for_request_validation_errors():
    from app.main import app

    handlers = app.exception_handlers
    assert RequestValidationError in handlers
    assert Exception not in handlers  # no hay un «todo error ⇒ 422»
