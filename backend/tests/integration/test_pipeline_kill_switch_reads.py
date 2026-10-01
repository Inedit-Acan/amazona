"""Leer el kill switch no escribe (hardening pre-M44).

`GET /api/pipeline/kill-switch`, `is_enabled()` y `get_state()` llamaban a un
get-or-create que hacía `INSERT` + `flush` aunque solo se quisiera leer: cada lectura
emitía un `INSERT INTO pipeline_kill_switch` que luego se revertía, y el ActionGate o
el arranque de un pipeline dejaban la fila persistida como efecto lateral.

Lo que se protege: una lectura jamás emite `INSERT`, `UPDATE` ni `DELETE`; la ausencia
de fila significa «habilitado» exactamente igual que antes; solo la primera mutación
explícita crea la fila; y dos primeras mutaciones a la vez no crean dos filas.
"""

import datetime
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.pipeline_kill_switch import PipelineKillSwitch
from app.db.session import get_db
from app.gates.action_gate import GateOutcome, SideEffectAction
from app.gates.service import ActionGateService
from app.main import app
from app.pipeline.kill_switch import KillSwitchState, PipelineKillSwitchService

TABLE = "pipeline_kill_switch"


def capture_writes(engine) -> list[str]:
    """Anota cada sentencia de escritura que llega a la base, tal como sale del ORM."""
    writes: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(" ".join(statement.split())[:70])

    return writes


def on_kill_switch(writes: list[str]) -> list[str]:
    return [w for w in writes if TABLE in w]


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


# --- Leer no escribe --------------------------------------------------------------


def test_a_hundred_reads_of_an_empty_table_write_nothing(engine, db: Session):
    writes = capture_writes(engine)
    service = PipelineKillSwitchService(db)

    for _ in range(100):
        assert service.is_enabled() is True
        assert service.get_state() == KillSwitchState()

    assert writes == []
    assert db.query(PipelineKillSwitch).count() == 0


def test_each_new_session_reading_writes_nothing_either(engine):
    """Una petición HTTP es una sesión nueva: antes, una lectura por sesión era un INSERT por petición."""
    writes = capture_writes(engine)
    factory = sessionmaker(bind=engine)

    for _ in range(100):
        session = factory()
        try:
            PipelineKillSwitchService(session).get_state()
        finally:
            session.close()

    assert writes == []


def test_the_state_of_a_missing_row_is_the_default_and_says_it_is_not_persisted(db: Session):
    state = PipelineKillSwitchService(db).get_state()

    assert state.enabled is True
    assert state.reason is None
    assert state.updated_by is None
    assert state.persisted is False


def test_a_read_does_not_leave_a_row_behind_after_a_rollback(db: Session):
    service = PipelineKillSwitchService(db)
    service.get_state()
    db.rollback()

    assert db.query(PipelineKillSwitch).count() == 0
    assert service.is_enabled() is True


# --- Escribir es explícito, y la primera vez crea la fila --------------------------


def test_the_first_explicit_mutation_creates_exactly_one_row(engine, db: Session):
    writes = capture_writes(engine)
    service = PipelineKillSwitchService(db)

    service.disable(reason="incident", actor="ops@amazona.local", correlation_id="c-1")

    assert len([w for w in on_kill_switch(writes) if w.startswith("INSERT")]) == 1
    assert db.query(PipelineKillSwitch).count() == 1
    assert db.query(AuditLog).filter_by(correlation_id="c-1").count() == 1
    assert service.get_state() == KillSwitchState(
        enabled=False, reason="incident", updated_by="ops@amazona.local", persisted=True
    )


def test_reads_after_a_mutation_write_nothing_more(engine, db: Session):
    service = PipelineKillSwitchService(db)
    service.disable(reason="incident", actor="ops@amazona.local", correlation_id="c-1")
    writes = capture_writes(engine)

    for _ in range(100):
        assert service.is_enabled() is False
        service.get_state()

    assert writes == []


def test_a_second_mutation_reuses_the_row(engine, db: Session):
    service = PipelineKillSwitchService(db)
    service.disable(reason="incident", actor="ops@amazona.local", correlation_id="c-1")
    service.enable(actor="ops@amazona.local", correlation_id="c-2")

    assert db.query(PipelineKillSwitch).count() == 1
    assert service.is_enabled() is True


def test_a_duplicate_row_for_the_same_switch_cannot_exist(db: Session):
    """Antes la tabla no tenía restricción única por nombre y los lectores desempataban por antigüedad; desde la ADR
    0026 la base de datos no admite el duplicado, así que no hay nada que desempatar."""
    now = datetime.datetime.now(datetime.UTC)
    db.add(PipelineKillSwitch(id="b", name="pipeline-default", enabled=True, created_at=now, updated_at=now))
    db.commit()

    db.add(
        PipelineKillSwitch(id="z", name="pipeline-default", enabled=False, reason="x", created_at=now, updated_at=now)
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    assert PipelineKillSwitchService(db).is_enabled() is True


# --- Los consumidores siguen comportándose igual ------------------------------------


def test_the_action_gate_reads_the_kill_switch_without_creating_it(engine, db: Session):
    writes = capture_writes(engine)

    decision = ActionGateService(db).evaluate(SideEffectAction.ACTIVATE_ADS, amount=10.0)

    assert decision.outcome is GateOutcome.ALLOW
    assert on_kill_switch(writes) == []
    assert db.query(PipelineKillSwitch).count() == 0


def test_a_disabled_switch_still_denies_through_the_action_gate(db: Session):
    PipelineKillSwitchService(db).disable(reason="incident", actor="ops@amazona.local", correlation_id="c-1")

    decision = ActionGateService(db).evaluate(SideEffectAction.ACTIVATE_ADS, amount=10.0)

    assert decision.outcome is GateOutcome.DENY
    assert any("kill switch is off" in reason for reason in decision.reasons)


@pytest.fixture()
def client(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_a_hundred_gets_of_the_endpoint_write_nothing_and_answer_the_default(engine, client: TestClient):
    writes = capture_writes(engine)

    for _ in range(100):
        response = client.get("/api/pipeline/kill-switch")
        assert response.status_code == 200
        assert response.json() == {"enabled": True, "reason": None, "updated_by": None}

    assert writes == []


def test_the_endpoint_post_then_get_keeps_its_contract(engine, client: TestClient):
    posted = client.post(
        "/api/pipeline/kill-switch", json={"enabled": False, "reason": "incident", "actor": "ops@amazona.local"}
    )
    assert posted.status_code == 200
    writes = capture_writes(engine)

    got = client.get("/api/pipeline/kill-switch")

    assert got.json()["enabled"] is False
    assert got.json()["reason"] == "incident"
    assert writes == []


# --- Dos primeras mutaciones a la vez no crean dos filas ---------------------------


def _postgres_engine_or_skip():
    url = get_settings().database_url
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not a PostgreSQL URL")
    # Este test ESCRIBE (y limpia): solo contra una base local o efímera, nunca contra una real.
    if make_url(url).host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("this test writes rows: it only runs against a local or ephemeral PostgreSQL")
    engine = create_engine(url, connect_args={"connect_timeout": 3}, pool_size=12)
    try:
        with engine.connect() as connection:
            connection.execute(text(f"SELECT 1 FROM {TABLE} LIMIT 1"))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"no reachable PostgreSQL at DATABASE_URL: {exc}")
    except Exception as exc:  # the table is missing: the schema was not migrated here
        engine.dispose()
        pytest.skip(f"{TABLE} is not available in this database: {exc}")
    return engine


def test_concurrent_first_mutations_create_a_single_row_on_postgresql():
    engine = _postgres_engine_or_skip()
    name = f"test-concurrent-{uuid.uuid4().hex[:12]}"
    workers = 8
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []

    def first_mutation(index: int) -> None:
        session = Session(engine)
        try:
            barrier.wait(timeout=10)
            PipelineKillSwitchService(session, name=name).disable(
                reason=f"worker {index}", actor="test@amazona.local", correlation_id=f"{name}-{index}"
            )
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(exc)
        finally:
            session.close()

    try:
        threads = [threading.Thread(target=first_mutation, args=(i,)) for i in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        with Session(engine) as check:
            rows = check.query(PipelineKillSwitch).filter_by(name=name).all()
            assert errors == []
            assert len(rows) == 1
            assert check.query(AuditLog).filter(AuditLog.correlation_id.like(f"{name}-%")).count() == workers
    finally:
        with Session(engine) as cleanup:
            cleanup.query(AuditLog).filter(AuditLog.correlation_id.like(f"{name}-%")).delete(synchronize_session=False)
            cleanup.query(PipelineKillSwitch).filter_by(name=name).delete(synchronize_session=False)
            cleanup.commit()
        engine.dispose()
