"""`POST /api/pipeline/runs` es idempotente con `Idempotency-Key` (hardening pre-M44, D11 fase 1).

Antes la cabecera se ignoraba: repetir la petición tras un timeout o un doble clic
creaba otra ejecución completa (medido: dos POST idénticos con la misma cabecera
dejaban 2 ejecuciones y 2 trabajos). La infraestructura existía —`Job.idempotency_key` es
única—, pero se alimentaba con `pipeline-run:{id de la ejecución recién creada}`, que
nunca puede repetirse.

Ahora la clave del cliente, con su espacio de nombres, es la del trabajo, y el trabajo
es lo primero que se escribe: la unicidad la garantiza la base de datos.

- misma clave y misma petición: la ejecución original; no se crea ni se ejecuta nada;
- misma clave y otra petición: 409;
- sin clave: obligatoria si algún proveedor puede salir del sistema; opcional solo si todos
  son simulados, y entonces cada petición es una ejecución nueva.
"""

import collections
import threading
import time

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from pg_test_support import ephemeral_postgres
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import pipeline as pipeline_api
from app.auth.actor import Actor, ActorSource, RoleName
from app.core.config import Environment, Settings, get_settings
from app.core.errors import IdempotencyConflictError, IdempotencyKeyRequiredError, ValidationError
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.job import Job
from app.db.models.pipeline_run import PipelineRun
from app.db.session import get_db
from app.integrations.ports import ProviderKind
from app.jobs.queue import JobQueue
from app.jobs.worker import Worker
from app.main import app
from app.pipeline.service import PipelineOrchestrator, PipelineRequest

BODY = {"category": "home", "sale_price": 50.0, "destination_region": "mexico"}
IDENTITY = Actor(subject="owner@amazona.local", role=RoleName.OWNER, source=ActorSource.DECLARED)
SETTINGS = Settings(_env_file=None)


def counts(db: Session) -> tuple[int, int]:
    db.expire_all()
    return db.query(PipelineRun).count(), db.query(Job).count()


# --- La política: cuándo la clave es obligatoria ---------------------------------------


@pytest.mark.parametrize("environment", [Environment.DEVELOPMENT, Environment.TEST, Environment.DEMO])
def test_with_every_provider_simulated_the_key_is_optional_outside_staging_and_production(environment):
    settings = Settings(_env_file=None, environment=environment)

    assert settings.all_providers_simulated is True
    assert settings.idempotency_key_required is False


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_in_staging_and_production_the_key_is_always_required(environment):
    assert Settings(_env_file=None, environment=environment).idempotency_key_required is True


@pytest.mark.parametrize(
    "field",
    [
        "product_intelligence_provider",
        "suppliers_provider",
        "regulatory_provider",
        "ads_provider",
        "marketplaces_provider",
        "exchange_rate_provider",
        "national_law_provider",
    ],
)
@pytest.mark.parametrize("kind", [ProviderKind.SANDBOX, ProviderKind.REAL, ProviderKind.COMPOSITE])
def test_any_provider_that_is_not_a_mock_makes_the_key_required_even_in_development(field, kind):
    settings = Settings(_env_file=None, environment=Environment.DEVELOPMENT, **{field: kind})

    assert settings.all_providers_simulated is False
    assert settings.idempotency_key_required is True


def test_the_key_is_namespaced_by_operation_and_by_who_asks():
    mine = pipeline_api._idempotency_key("abc", IDENTITY, SETTINGS)
    other = pipeline_api._idempotency_key("abc", Actor(subject="someone@else", role=RoleName.OWNER), SETTINGS)

    assert mine.startswith("pipeline-run:") and mine.endswith(":abc")
    assert mine != other  # la misma clave de dos personas no es la misma clave
    assert pipeline_api._idempotency_key(None, IDENTITY, SETTINGS) is None


def test_a_missing_key_is_refused_when_a_provider_can_reach_outside():
    real = Settings(_env_file=None, ads_provider=ProviderKind.REAL)

    for missing in (None, "", "   "):
        with pytest.raises(IdempotencyKeyRequiredError):
            pipeline_api._idempotency_key(missing, IDENTITY, real)


@pytest.mark.parametrize("bad", ["has space", "a/b", "x" * 129, "ñ", "a;b"])
def test_a_malformed_key_is_refused(bad):
    with pytest.raises(ValidationError):
        pipeline_api._idempotency_key(bad, IDENTITY, SETTINGS)


# --- Por HTTP (SQLite) -----------------------------------------------------------------


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
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def client(factory):
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
        app.dependency_overrides.pop(get_settings, None)


def post(client: TestClient, body: dict | None = None, key: str | None = "retry-1"):
    headers = {"Idempotency-Key": key} if key is not None else {}
    return client.post("/api/pipeline/runs", json=body if body is not None else BODY, headers=headers)


def test_the_same_key_and_the_same_request_return_the_original_run(client: TestClient, factory):
    first = post(client)
    second = post(client)

    assert (first.status_code, second.status_code) == (202, 202)
    assert second.json() == first.json()
    assert "idempotency-replayed" not in first.headers
    assert second.headers["Idempotency-Replayed"] == "true"
    with factory() as db:
        assert counts(db) == (1, 1)


def test_defaults_spelled_out_or_omitted_are_the_same_request(client: TestClient, factory):
    explicit = {**BODY, "market": "us", "daily_budget": 20.0, "max_results": 5, "certification_available": False}
    first = post(client, BODY)
    second = post(client, dict(reversed(list(explicit.items()))))

    assert second.json()["correlation_id"] == first.json()["correlation_id"]
    with factory() as db:
        assert counts(db) == (1, 1)


def test_the_same_key_with_a_different_request_is_a_conflict_and_creates_nothing(client: TestClient, factory):
    first = post(client)

    second = post(client, {**BODY, "sale_price": 99.0})

    assert second.status_code == 409
    assert "different request" in second.json()["detail"]
    assert first.json()["correlation_id"] not in second.text  # no se filtra la ejecución ajena
    with factory() as db:
        assert counts(db) == (1, 1)


def test_different_keys_are_different_requests(client: TestClient, factory):
    a = post(client, key="key-a")
    b = post(client, key="key-b")

    assert a.json()["correlation_id"] != b.json()["correlation_id"]
    with factory() as db:
        assert counts(db) == (2, 2)


def test_without_a_key_and_with_every_provider_simulated_each_request_is_a_new_run(client: TestClient, factory):
    """Permitido porque es simulado: un duplicado no le hace nada a nadie fuera del sistema."""
    post(client, key=None)
    post(client, key=None)

    with factory() as db:
        assert counts(db) == (2, 2)


def test_without_a_key_when_a_provider_is_real_the_request_is_refused_and_nothing_is_created(
    client: TestClient, factory
):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, ads_provider=ProviderKind.REAL)

    response = post(client, key=None)

    assert response.status_code == 428
    assert "Idempotency-Key" in response.json()["detail"]
    with factory() as db:
        assert counts(db) == (0, 0)


def test_with_a_key_a_request_is_accepted_even_when_a_provider_is_real(client: TestClient, factory):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, ads_provider=ProviderKind.REAL)

    assert post(client, key="real-1").status_code == 202


def test_a_malformed_key_is_a_422(client: TestClient):
    assert post(client, key="not valid!").status_code == 422


def test_retrying_after_a_timeout_does_not_run_the_work_twice(client: TestClient, factory):
    """La primera respuesta se perdió (timeout): el servidor sí llegó a aceptar la ejecución y un
    worker la ejecutó. El reintento recibe esa misma ejecución, ya terminada, y no se ejecuta nada."""
    post(client)  # la respuesta «se pierde»
    with factory() as db:
        worker = Worker(name="test-worker", settings=Settings(_env_file=None, reconciliation_enabled=False))
        for _ in range(12):
            if worker.run_once(db) is None:
                break
        run = db.query(PipelineRun).one()
        assert run.status == "COMPLETED"
        attempts = db.query(Job).one().attempt

    retry = post(client)

    assert retry.status_code == 202
    assert retry.json()["status"] == "COMPLETED"
    assert retry.headers["Idempotency-Replayed"] == "true"
    with factory() as db:
        assert counts(db) == (1, 1)
        assert db.query(Job).one().attempt == attempts  # nadie lo volvió a ejecutar


def test_a_retry_of_something_already_accepted_is_not_blocked_by_the_kill_switch(client: TestClient):
    first = post(client)
    client.post(
        "/api/pipeline/kill-switch", json={"enabled": False, "reason": "incident", "actor": "ops@amazona.local"}
    )

    retry = post(client)
    another = post(client, key="new-key")

    assert retry.status_code == 202 and retry.json()["correlation_id"] == first.json()["correlation_id"]
    assert another.status_code == 423  # una petición nueva sí se bloquea


# --- La garantía es de la base de datos (PostgreSQL) ----------------------------------


def create(session: Session, body: dict, key: str | None):
    response = Response()
    run = pipeline_api.create_pipeline_run(
        pipeline_api.PipelineRunCreate(**body), response, session, IDENTITY, SETTINGS, key
    )
    return run, response.headers.get("Idempotency-Replayed") == "true"


def race(engine, calls: list[tuple[dict, str | None]]) -> list[tuple[str, str | None, bool]]:
    barrier = threading.Barrier(len(calls))
    results: list[tuple[str, str | None, bool]] = []
    lock = threading.Lock()

    def worker(body: dict, key: str | None) -> None:
        with Session(engine) as session:
            try:
                barrier.wait(timeout=10)
                run, replayed = create(session, body, key)
                outcome = ("ok", run.correlation_id, replayed)
            except Exception as exc:  # noqa: BLE001 - lo que le pasó a cada petición es el dato
                outcome = (type(exc).__name__, None, False)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=call) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def test_eight_simultaneous_identical_requests_create_exactly_one_run_and_one_job():
    with ephemeral_postgres() as engine:
        for trial in range(6):
            key = f"race-{trial}"
            results = race(engine, [(BODY, key)] * 8)

            assert collections.Counter(outcome for outcome, _, _ in results) == {"ok": 8}
            assert len({correlation for _, correlation, _ in results}) == 1  # todas, la misma ejecución
            assert sum(replayed for _, _, replayed in results) == 7
            with Session(engine) as db:
                assert counts(db) == (trial + 1, trial + 1)
                enqueued = db.query(AuditLog).filter_by(action="pipeline.enqueue").count()
                assert enqueued == trial + 1


def test_simultaneous_requests_with_the_same_key_and_different_bodies_create_one_run():
    with ephemeral_postgres() as engine:
        for trial in range(6):
            other = {**BODY, "sale_price": 99.0}
            results = race(engine, [(BODY, f"mix-{trial}")] * 4 + [(other, f"mix-{trial}")] * 4)

            outcomes = collections.Counter(outcome for outcome, _, _ in results)
            assert set(outcomes) <= {"ok", "IdempotencyConflictError"}
            assert len({correlation for outcome, correlation, _ in results if outcome == "ok"}) == 1
            with Session(engine) as db:
                assert counts(db) == (trial + 1, trial + 1)


def test_without_a_key_simultaneous_requests_are_independent_runs():
    with ephemeral_postgres() as engine:
        results = race(engine, [(BODY, None)] * 5)

        assert collections.Counter(outcome for outcome, _, _ in results) == {"ok": 5}
        assert len({correlation for _, correlation, _ in results}) == 5
        with Session(engine) as db:
            assert counts(db) == (5, 5)


def test_losing_the_race_for_a_key_does_not_roll_back_the_losers_pending_work():
    """S1 inserta el trabajo con la clave y todavía no confirma; S2 añade otra fila a su
    transacción y encola con la misma clave, así que su insert espera a S1. Cuando S1 confirma,
    el insert de S2 falla: debe deshacerse **solo ese insert** (SAVEPOINT) y conservar lo demás.
    Con un rollback completo, la fila de auditoría de S2 habría desaparecido."""
    with ephemeral_postgres() as engine:
        s1 = Session(engine)
        JobQueue(s1).enqueue(job_type="noop", payload={"who": "s1"}, idempotency_key="k-1", commit=False)
        result: dict = {}

        def second() -> None:
            with Session(engine) as s2:
                s2.add(AuditLog(actor="s2", action="s2.pending", resource="r", correlation_id="c"))
                job = JobQueue(s2).enqueue(job_type="noop", payload={"who": "s2"}, idempotency_key="k-1", commit=False)
                result["payload"] = job.payload
                s2.commit()

        thread = threading.Thread(target=second)
        thread.start()
        time.sleep(1.0)  # S2 ya está esperando a la clave
        s1.commit()
        s1.close()
        thread.join(timeout=30)

        assert result["payload"] == {"who": "s1"}  # S2 se quedó con el trabajo del ganador
        with Session(engine) as db:
            assert db.query(Job).filter_by(idempotency_key="k-1").count() == 1
            assert db.query(AuditLog).filter_by(action="s2.pending").count() == 1  # su trabajo sobrevive


def test_a_keyed_request_is_independent_of_runs_created_without_a_client_key(factory):
    """Una ejecución sin clave del cliente usa una clave derivada de su propio id: una clave nueva
    nunca la devuelve, y repetir esa clave con otro cuerpo es un conflicto."""
    with factory() as db:
        orchestrator = PipelineOrchestrator(db)
        orchestrator.enqueue_run(PipelineRequest(**BODY))

        _, replayed = orchestrator.enqueue_or_replay(PipelineRequest(**BODY), idempotency_key="pipeline-run:x:y")

        assert replayed is False
        assert counts(db) == (2, 2)
        with pytest.raises(IdempotencyConflictError):
            orchestrator.enqueue_or_replay(
                PipelineRequest(**{**BODY, "sale_price": 1.0}), idempotency_key="pipeline-run:x:y"
            )
