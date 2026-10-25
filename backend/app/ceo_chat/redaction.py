"""Lo que ve el modelo (y lo que se guarda de una conversación) pasa antes por aquí.

El modelo no recibe contraseñas, tokens, claves, cadenas de conexión ni correos. Hay DOS defensas, y las dos hacen
falta:

1. Por **nombre de clave**: cualquier valor cuya clave se llame `password`, `token`, `api_key`, `authorization`… se
   sustituye entero.
2. Por **patrón** en el texto: un JWT, una clave `sk-…`, un `Bearer …`, una URL de conexión con contraseña, una
   asignación `password=…`, un correo.

No es un filtro de «contenido peligroso»: es una red de seguridad para que un secreto que ya esté en los datos (una
auditoría con un token pegado, un
campo libre) no llegue nunca al modelo. La defensa de verdad es que el modelo no tiene ninguna herramienta que lea
ficheros, variables de entorno ni SQL.
"""

import re
from typing import Any

REDACTED = "[redactado]"

_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|apikey|authorization|credential|service[_-]?role|dsn|database[_-]?url|private[_-]?key|cookie)",
    re.IGNORECASE,
)

#: Contadores de uso del modelo (`input_tokens`…): su nombre contiene «token», pero son números, no credenciales.
_USAGE_COUNTER = re.compile(r"(input|output|total|max_output)_tokens", re.IGNORECASE)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # URL con credenciales: postgresql+psycopg://usuario:contraseña@host/db
    (re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@[^\s]+"), "[dsn]"),
    # JWT: tres segmentos base64url, el primero empieza por «eyJ»
    (re.compile(r"eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{2,}\.[A-Za-z0-9_\-]{2,}"), "[token]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}"), "[token]"),
    # Clave de proveedor (sk-…)
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}"), "[clave]"),
    # Cabecera Bearer
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]{8,}=*"), "Bearer [token]"),
    # Asignaciones «clave = valor» / «clave: valor» con un nombre sensible
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|api[_-]?key|apikey|token|service[_-]?role[_-]?key|private[_-]?key)\b(\s*[:=]\s*)(\S+)"
        ),
        r"\1\2" + REDACTED,
    ),
    # Correos
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[correo]"),
]


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _is_secret_key(key: object) -> bool:
    return isinstance(key, str) and _USAGE_COUNTER.fullmatch(key) is None and _SENSITIVE_KEY.search(key) is not None


def redact(value: Any) -> Any:
    """Una copia redactada de `value` (cadenas, listas, diccionarios, anidados). No modifica el original."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: (REDACTED if _is_secret_key(key) else redact(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value
