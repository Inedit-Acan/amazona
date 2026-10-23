"""Observabilidad SEGURA de los fallos de base de datos en las sondas `/health/ready` y `/health/detailed` (M48).

Antes, esas sondas hacían `except Exception: return 503` y descartaban la excepción: un 503 aislado no dejaba ninguna
pista de si fue un timeout de conexión, un límite del pooler, una autenticación, un pool agotado o una conexión caída.
Ahora el fallo deja UN `WARNING` estructurado. La respuesta HTTP no cambia (503 con el mismo cuerpo genérico).

Campos del registro (cerrados): `event` (`readiness_failed`), `reason` (lista cerrada `READINESS_REASONS`),
`exception_chain` (solo NOMBRES de clase, p. ej. `OperationalError -> ConnectionTimeout`), `elapsed_ms`, `pool_status`
(solo enteros) y `correlation_id`.

Lo que NUNCA se registra: el mensaje de la excepción (`str`/`repr`), la URL o el DSN, la contraseña, el usuario,
el host, el SQL ni sus parámetros. El mensaje SÍ se lee, pero solo para clasificar con fragmentos fijos
(`_FRAGMENTS`); nada de lo leído sale del proceso. Lo que no se reconoce es `other`: jamás se devuelve texto
arbitrario de una excepción.
"""

import logging
import time

from psycopg import errors as pg_errors
from sqlalchemy import exc as sa_exc

from app.core.logging import get_correlation_id
from app.db.session import get_engine

logger = logging.getLogger(__name__)

EVENT = "readiness_failed"

#: La lista cerrada de razones. Cualquier otra cosa es `other`.
READINESS_REASONS = (
    "connect_timeout",
    "auth",
    "too_many_connections",
    "pool_timeout",
    "connection_lost",
    "other",
)

_MAX_CHAIN = 6

#: Por clase (lo más fiable). `psycopg` no rellena `sqlstate` en los fallos de conexión: no basta con él.
_AUTH_CLASSES = (pg_errors.InvalidPassword, pg_errors.InvalidAuthorizationSpecification)
_LOST_CLASSES = (
    pg_errors.AdminShutdown,
    pg_errors.CrashShutdown,
    pg_errors.ConnectionFailure,
    pg_errors.ConnectionException,
    pg_errors.ConnectionDoesNotExist,
    sa_exc.DisconnectionError,
    ConnectionError,  # incluye ConnectionResetError, ConnectionRefusedError y BrokenPipeError
)

#: Fragmentos FIJOS, en minúsculas, para los errores de conexión de `psycopg`/libpq que llegan como un
#: `OperationalError` genérico (sin clase propia ni `sqlstate`). Se evalúan en este orden. Solo sirven para ELEGIR una
#: razón: nunca se devuelven ni se registran.
_FRAGMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "too_many_connections",
        (
            "too many connections",
            "too many clients",
            "max clients reached",
            "remaining connection slots",
            "emaxconnsession",
            "connection limit",
        ),
    ),
    ("auth", ("password authentication failed", "authentication failed")),
    ("connect_timeout", ("timeout expired",)),
    (
        "connection_lost",
        (
            "server closed the connection unexpectedly",
            "connection is lost",
            "connection already closed",
            "eof detected",
            "ssl syscall error",
            "connection refused",
            "connection reset",
            "terminating connection",
            "could not translate host name",
            "network is unreachable",
            "connection not open",
        ),
    ),
)


def _walk(exc: BaseException) -> list[BaseException]:
    """La excepción y sus causas encadenadas (`orig`, `__cause__`, `__context__`), sin ciclos y con tope."""
    seen: set[int] = set()
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN:
        seen.add(id(current))
        chain.append(current)
        nxt = getattr(current, "orig", None)
        if not isinstance(nxt, BaseException):
            nxt = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        current = nxt
    return chain


def exception_chain(exc: BaseException) -> str:
    """Solo nombres de clase, de la más externa a la causa: `OperationalError -> ConnectionTimeout`. Nunca mensajes."""
    return " -> ".join(type(item).__name__ for item in _walk(exc))


def _messages(chain: list[BaseException]) -> list[str]:
    out: list[str] = []
    for item in chain:
        try:
            out.append(str(item).lower())
        except Exception:  # noqa: BLE001 - un `__str__` roto no puede romper la sonda
            continue
    return out


def classify_db_failure(exc: BaseException) -> str:
    """La razón (de `READINESS_REASONS`) de un fallo de base de datos. Función pura: no escribe nada y NUNCA devuelve
    texto de la excepción. Orden: pool agotado, autenticación, límite de conexiones, timeout de conexión, conexión
    caída; luego, fragmentos fijos para los `OperationalError` genéricos de libpq. Lo que no se reconoce es `other`."""
    chain = _walk(exc)
    if any(isinstance(item, sa_exc.TimeoutError) for item in chain):
        return "pool_timeout"
    if any(isinstance(item, _AUTH_CLASSES) for item in chain):
        return "auth"
    if any(isinstance(item, pg_errors.TooManyConnections) for item in chain):
        return "too_many_connections"
    if any(isinstance(item, pg_errors.ConnectionTimeout) for item in chain):
        return "connect_timeout"
    if any(isinstance(item, _LOST_CLASSES) for item in chain) or any(
        isinstance(item, sa_exc.DBAPIError) and item.connection_invalidated for item in chain
    ):
        return "connection_lost"
    messages = _messages(chain)
    for reason, fragments in _FRAGMENTS:
        if any(fragment in message for message in messages for fragment in fragments):
            return reason
    return "other"


def pool_status() -> dict[str, int]:
    """Métricas del pool del engine, solo enteros (tamaño, en pool, en uso, desbordamiento). Sin URL ni credenciales.
    Un pool que no expone alguna métrica (p. ej. el de pruebas con SQLite) simplemente no la incluye."""
    try:
        pool = get_engine().pool
    except Exception:  # noqa: BLE001
        return {}
    status: dict[str, int] = {}
    for key, method_name in (
        ("size", "size"),
        ("checked_in", "checkedin"),
        ("checked_out", "checkedout"),
        ("overflow", "overflow"),
    ):
        method = getattr(pool, method_name, None)
        if callable(method):
            try:
                status[key] = int(method())
            except Exception:  # noqa: BLE001
                continue
    return status


def log_db_health_failure(check: str, exc: BaseException, started: float) -> None:
    """Registra el fallo de una sonda: `check` es una constante como `GET /health/ready` y `started` el
    `time.perf_counter()` previo a la consulta. Nunca lanza: si el registro fallase, el 503 de la sonda no cambia."""
    try:
        logger.warning(
            f"{check}: database check failed",
            extra={
                "event": EVENT,
                "reason": classify_db_failure(exc),
                "exception_chain": exception_chain(exc),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "pool_status": pool_status(),
                "correlation_id": get_correlation_id(),
            },
        )
    except Exception:  # noqa: BLE001 - observabilidad: nunca debe cambiar la respuesta de la sonda
        return


__all__ = [
    "EVENT",
    "READINESS_REASONS",
    "classify_db_failure",
    "exception_chain",
    "log_db_health_failure",
    "pool_status",
]
