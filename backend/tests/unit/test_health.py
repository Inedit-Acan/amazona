import io
import json
import logging

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors as pg_errors
from pythonjsonlogger import json as jsonlogger
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SAPoolTimeoutError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db_health import READINESS_REASONS, classify_db_failure, exception_chain
from app.core.logging import CorrelationIdFilter
from app.db.base import Base
from app.db.session import get_db
from app.main import app

client = TestClient(app)


def test_health_returns_200_with_status_ok():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "amazona-backend"


def test_response_includes_a_correlation_id_header():
    response = client.get("/health")

    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) > 0


def test_incoming_correlation_id_is_echoed_back():
    response = client.get("/health", headers={"X-Correlation-ID": "test-correlation-id"})

    assert response.headers["X-Correlation-ID"] == "test-correlation-id"


def test_control_center_origin_is_allowed_by_cors():
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_health_detailed_returns_503_when_database_is_unreachable():
    # Forces the failure deterministically instead of relying on ambient
    # DATABASE_URL: that's unreachable in a sandbox with no Postgres
    # running, but CI's own workflow points it at a live service
    # container, so the two environments would otherwise disagree here.
    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("simulated unreachable database"))

    def override_get_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health/detailed")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    body = response.json()
    assert body["database"] == "error"
    assert body["migration"] is None


def test_health_detailed_returns_200_with_migration_version_when_database_is_reachable():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    session.execute(text("INSERT INTO alembic_version VALUES ('abc123')"))
    session.commit()

    def override_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health/detailed")
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ok"
    assert body["migration"] == "abc123"
    assert "supabase_configured" in body


# --- Observabilidad de los fallos de /health/ready y /health/detailed (M48) ------------------------------------
#
# La respuesta HTTP NO cambia (503 + cuerpo genérico). Lo que cambia es que el fallo deja un WARNING estructurado con
# campos cerrados y SIN secretos: `event`, `reason` (lista cerrada), `exception_chain` (solo nombres de clase),
# `elapsed_ms`, `pool_status` (solo enteros) y `correlation_id`. Antes del cambio el `except` descartaba la excepción
# sin dejar rastro.

SECRET_DSN = "postgresql://usuario_secreto:clave_secreta@host-secreto.example.com:5432/base_secreta"
SECRET_SQL = "SELECT columna_secreta FROM tabla_secreta WHERE token = 'valor_secreto'"
SECRETS = (
    "usuario_secreto",
    "clave_secreta",
    "host-secreto",
    "base_secreta",
    "columna_secreta",
    "tabla_secreta",
    "valor_secreto",
)
ALLOWED_EXTRA = {"event", "reason", "exception_chain", "elapsed_ms", "pool_status", "correlation_id"}


def _operational(orig: Exception) -> OperationalError:
    return OperationalError("SELECT 1", {}, orig)


def connect_timeout() -> Exception:
    return _operational(pg_errors.ConnectionTimeout("connection timeout expired"))


def auth_failure() -> Exception:
    return _operational(
        psycopg.OperationalError(
            'connection failed: connection to server at "10.0.0.5", port 5432 failed: '
            'FATAL:  password authentication failed for user "svc"'
        )
    )


def too_many_connections() -> Exception:
    return _operational(
        psycopg.OperationalError(
            'connection failed: connection to server failed: FATAL:  too many connections for role "svc"'
        )
    )


def pool_timeout() -> Exception:
    return SAPoolTimeoutError("QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00")


def connection_lost() -> Exception:
    return _operational(psycopg.OperationalError("consuming input failed: server closed the connection unexpectedly"))


def unknown_failure() -> Exception:
    return RuntimeError("algo que nadie ha visto antes")


REASON_CASES = [
    ("connect_timeout", connect_timeout),
    ("auth", auth_failure),
    ("too_many_connections", too_many_connections),
    ("pool_timeout", pool_timeout),
    ("connection_lost", connection_lost),
    ("other", unknown_failure),
]


class _FailingSession:
    def __init__(self, exc: Exception):
        self._exc = exc

    def execute(self, *args, **kwargs):
        raise self._exc


def _get(path: str, exc: Exception, headers: dict[str, str] | None = None):
    def override_get_db():
        yield _FailingSession(exc)

    app.dependency_overrides[get_db] = override_get_db
    try:
        return client.get(path, headers=headers or {})
    finally:
        app.dependency_overrides.pop(get_db, None)


def _failures(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == "readiness_failed"]


def _everything_logged(caplog) -> str:
    """Todo lo que se escribió: el texto formateado y cada atributo de cada registro (incluidos los `extra`)."""
    parts = [caplog.text]
    for record in caplog.records:
        parts.append(json.dumps(record.__dict__, default=str))
        parts.append(record.getMessage())
    return "\n".join(parts)


def test_A_a_healthy_database_answers_200_and_logs_no_readiness_failure(caplog):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(bind=engine)

    def override_get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.get("/health/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not _failures(caplog)


@pytest.mark.parametrize(("reason", "make"), REASON_CASES, ids=[r for r, _ in REASON_CASES])
def test_B_to_G_each_failure_is_503_with_the_same_public_body_and_one_structured_warning(reason, make, caplog):
    with caplog.at_level(logging.WARNING):
        response = _get("/health/ready", make())

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}
    failures = _failures(caplog)
    assert len(failures) == 1
    record = failures[0]
    assert record.levelno == logging.WARNING
    assert record.reason == reason
    assert record.reason in READINESS_REASONS


def test_the_warning_carries_exactly_the_allowed_closed_fields(caplog):
    with caplog.at_level(logging.WARNING):
        _get("/health/ready", connect_timeout())

    record = _failures(caplog)[0]
    assert record.event == "readiness_failed"
    assert record.exception_chain == "OperationalError -> ConnectionTimeout"
    assert isinstance(record.elapsed_ms, int)
    assert record.elapsed_ms >= 0
    assert isinstance(record.pool_status, dict)
    assert all(isinstance(v, int) for v in record.pool_status.values())
    # ningún otro atributo propio se ha colado en el registro
    standard = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}
    assert {k for k in record.__dict__ if k not in standard} == ALLOWED_EXTRA


def test_the_correlation_id_of_the_request_is_in_the_warning(caplog):
    with caplog.at_level(logging.WARNING):
        response = _get("/health/ready", pool_timeout(), headers={"X-Correlation-ID": "corr-health-1"})

    assert response.headers["X-Correlation-ID"] == "corr-health-1"
    assert _failures(caplog)[0].correlation_id == "corr-health-1"


def test_the_helper_sets_the_correlation_id_itself_it_does_not_depend_on_a_handler_filter():
    """Un handler del propio logger ve el registro ANTES que los de la raíz (y su filtro): el campo ya viene puesto."""
    from app.core import db_health
    from app.core.logging import set_correlation_id

    seen: list[object] = []

    class _Spy(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(getattr(record, "correlation_id", "AUSENTE"))

    spy = _Spy(level=logging.WARNING)
    logger = logging.getLogger("app.core.db_health")
    logger.addHandler(spy)
    try:
        set_correlation_id("corr-direct-7")
        db_health.log_db_health_failure("GET /health/ready", connect_timeout(), 0.0)
    finally:
        logger.removeHandler(spy)

    assert seen == ["corr-direct-7"]


def test_the_json_line_the_app_writes_has_the_fields_and_no_secret(caplog):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(CorrelationIdFilter())
    handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        with caplog.at_level(logging.WARNING):
            _get(
                "/health/ready",
                _operational(psycopg.OperationalError(f"FATAL: password authentication failed {SECRET_DSN}")),
            )
    finally:
        root.removeHandler(handler)

    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    entry = next(item for item in lines if item.get("event") == "readiness_failed")
    assert entry["levelname"] == "WARNING"
    assert entry["reason"] == "auth"
    assert entry["exception_chain"] == "OperationalError -> OperationalError"
    assert {"elapsed_ms", "pool_status", "correlation_id"} <= set(entry)
    assert not any(secret in stream.getvalue() for secret in SECRETS)


def test_H_no_secret_from_a_connection_string_in_the_exception_reaches_the_logs(caplog):
    exc = _operational(
        psycopg.OperationalError(
            f"connection failed: could not connect using {SECRET_DSN}: password authentication failed"
        )
    )
    with caplog.at_level(logging.DEBUG):
        response = _get("/health/ready", exc)

    assert response.status_code == 503
    logged = _everything_logged(caplog)
    assert "postgresql://" not in logged
    for secret in SECRETS:
        assert secret not in logged, secret
    assert _failures(caplog)[0].reason == "auth"  # se clasificó leyendo el mensaje, pero el mensaje no sale


def test_H2_a_secret_in_a_plain_exception_message_is_not_logged_either(caplog):
    with caplog.at_level(logging.DEBUG):
        _get("/health/ready", RuntimeError(f"fallo con {SECRET_DSN}"))

    logged = _everything_logged(caplog)
    for secret in SECRETS:
        assert secret not in logged, secret
    assert _failures(caplog)[0].reason == "other"


def test_I_the_sql_and_its_parameters_are_not_logged(caplog):
    exc = OperationalError(SECRET_SQL, {"token": "valor_secreto"}, psycopg.OperationalError("connection is lost"))
    with caplog.at_level(logging.DEBUG):
        response = _get("/health/ready", exc)

    assert response.status_code == 503
    logged = _everything_logged(caplog)
    for fragment in ("SELECT columna_secreta", "columna_secreta", "tabla_secreta", "valor_secreto", "token"):
        assert fragment not in logged, fragment


def test_a_failure_while_logging_never_changes_the_response(monkeypatch):
    def exploding(*args, **kwargs):
        raise RuntimeError("el log ha fallado")

    monkeypatch.setattr(logging.getLogger("app.core.db_health"), "warning", exploding)
    response = _get("/health/ready", connect_timeout())

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}


def test_J_health_detailed_keeps_its_503_contract_and_now_logs_the_same_event(caplog):
    with caplog.at_level(logging.WARNING):
        response = _get("/health/detailed", auth_failure())

    assert response.status_code == 503
    body = response.json()
    assert set(body) == {"database", "migration", "supabase_configured"}
    assert body["database"] == "error"
    assert body["migration"] is None
    failures = _failures(caplog)
    assert len(failures) == 1
    assert failures[0].reason == "auth"
    assert not any(secret in _everything_logged(caplog) for secret in SECRETS)


def test_J2_health_detailed_without_failure_logs_nothing_and_keeps_its_200_body(caplog):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(bind=engine)
    seed = factory()
    seed.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    seed.execute(text("INSERT INTO alembic_version VALUES ('zzz')"))
    seed.commit()

    def override_get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.get("/health/detailed")
    finally:
        app.dependency_overrides.pop(get_db, None)
        seed.close()
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.json()["migration"] == "zzz"
    assert not _failures(caplog)


@pytest.mark.parametrize(("reason", "make"), REASON_CASES, ids=[r for r, _ in REASON_CASES])
def test_classify_db_failure_maps_each_family_to_its_reason(reason, make):
    assert classify_db_failure(make()) == reason


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (pg_errors.InvalidPassword("x"), "auth"),
        (pg_errors.InvalidAuthorizationSpecification("x"), "auth"),
        (pg_errors.TooManyConnections("x"), "too_many_connections"),
        (_operational(psycopg.OperationalError("FATAL: sorry, too many clients already")), "too_many_connections"),
        (
            _operational(
                psycopg.OperationalError("FATAL: max clients reached in session mode - limited to pool_size: 15")
            ),
            "too_many_connections",
        ),
        (pg_errors.ConnectionTimeout("x"), "connect_timeout"),
        (pg_errors.AdminShutdown("x"), "connection_lost"),
        (pg_errors.CrashShutdown("x"), "connection_lost"),
        (pg_errors.ConnectionDoesNotExist("x"), "connection_lost"),
        (pg_errors.ConnectionFailure("x"), "connection_lost"),
        (_operational(psycopg.OperationalError("SSL SYSCALL error: EOF detected")), "connection_lost"),
        (_operational(psycopg.OperationalError("connection failed: Connection refused")), "connection_lost"),
        (ConnectionResetError("reset"), "connection_lost"),
        (TimeoutError("socket timeout"), "other"),
        (ValueError("no es de base de datos"), "other"),
    ],
)
def test_classify_db_failure_known_classes_and_controlled_fragments(exc, reason):
    assert classify_db_failure(exc) == reason


def test_classify_db_failure_follows_the_chained_cause():
    try:
        try:
            raise pg_errors.ConnectionTimeout("connection timeout expired")
        except Exception as inner:
            raise RuntimeError("envuelto") from inner
    except RuntimeError as outer:
        assert classify_db_failure(outer) == "connect_timeout"


def test_classify_db_failure_never_returns_free_text_and_survives_odd_input():
    weird = [
        RuntimeError(SECRET_DSN),
        Exception(),
        KeyboardInterrupt(),
        _operational(psycopg.OperationalError(SECRET_DSN)),
    ]
    for exc in weird:
        assert classify_db_failure(exc) in READINESS_REASONS


def test_exception_chain_is_only_class_names_and_terminates_on_cycles():
    exc = _operational(pg_errors.ConnectionTimeout(f"timeout {SECRET_DSN}"))
    chain = exception_chain(exc)
    assert chain == "OperationalError -> ConnectionTimeout"
    assert all(secret not in chain for secret in SECRETS)

    a, b = RuntimeError("a"), ValueError("b")
    a.__cause__, b.__cause__ = b, a
    assert exception_chain(a) == "RuntimeError -> ValueError"


def test_elapsed_ms_is_the_time_since_the_check_started_in_milliseconds(caplog, monkeypatch):
    from app.core import db_health

    monkeypatch.setattr(db_health.time, "perf_counter", lambda: 12.5)
    with caplog.at_level(logging.WARNING):
        db_health.log_db_health_failure("GET /health/ready", connect_timeout(), 11.0)

    assert _failures(caplog)[0].elapsed_ms == 1500


def test_pool_status_is_only_integers_and_never_the_url():
    from app.core.db_health import pool_status

    status = pool_status()
    assert all(isinstance(v, int) for v in status.values())
    assert set(status) <= {"size", "checked_in", "checked_out", "overflow"}


def test_the_closed_list_of_reasons_is_exactly_the_agreed_one():
    assert READINESS_REASONS == (
        "connect_timeout",
        "auth",
        "too_many_connections",
        "pool_timeout",
        "connection_lost",
        "other",
    )
