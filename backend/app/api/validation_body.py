"""El cuerpo de un 422 de esquema, seguro de serializar (M46, Commit 5c).

FastAPI responde a un fallo de esquema con `{"detail": exc.errors()}` y cada error repite el valor recibido en `input`.
Si ese valor es `NaN` o `±Infinity` (el JSON de Starlette los acepta al leer), `JSONResponse` no puede escribirlo
(`allow_nan=False`) y la respuesta que debía ser un 422 sale como un **500**. Pasaba con cualquier campo numérico con
restricción, en cualquier endpoint.

Este módulo conserva el cuerpo exactamente como lo da FastAPI (mismo `type`, `loc`, `msg`, `ctx`, mismo orden) y solo
cambia, **en `input` y `ctx`**, dos cosas que no se pueden o no se deben reflejar:
  * un `NaN`/`Infinity`/`-Infinity` pasa a su nombre como texto;
  * un eco demasiado grande se recorta (una cadena) o se sustituye por una marca (un objeto o una lista), para no
    devolver al cliente un cuerpo arbitrariamente grande.
Los límites de eco son técnicos, no de negocio; los valores normales no se tocan. No captura excepciones ni cambia el
código HTTP.
"""

import json
import math
from collections.abc import Sequence
from typing import Any

#: Cuántos caracteres de una cadena recibida se repiten como máximo en un error.
MAX_ECHOED_CHARS = 256
#: Cuántos caracteres de JSON puede ocupar un objeto o lista recibidos para repetirse en un error.
MAX_ECHOED_JSON_CHARS = 1024


def _name_of_non_finite(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


def _safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return _name_of_non_finite(value)
    if isinstance(value, str):
        return value if len(value) <= MAX_ECHOED_CHARS else value[:MAX_ECHOED_CHARS] + "..."
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def _echo(value: Any) -> Any:
    """Lo que se repite de un valor recibido: seguro de serializar y de tamaño acotado."""
    safe = _safe(value)
    if isinstance(safe, (dict, list)):
        try:
            size = len(json.dumps(safe, default=str))
        except (TypeError, ValueError):
            size = MAX_ECHOED_JSON_CHARS + 1
        if size > MAX_ECHOED_JSON_CHARS:
            return f"<{type(value).__name__} of {len(value)} items, not echoed>"
    return safe


def safe_validation_errors(errors: Sequence[Any]) -> list[Any]:
    """`exc.errors()` con `input` y `ctx` seguros; el resto de cada error, intacto."""
    cleaned = []
    for error in errors:
        if not isinstance(error, dict):
            cleaned.append(error)
            continue
        item = dict(error)
        if "input" in item:
            item["input"] = _echo(item["input"])
        if isinstance(item.get("ctx"), dict):
            item["ctx"] = {key: _echo(value) for key, value in item["ctx"].items()}
        cleaned.append(item)
    return cleaned
