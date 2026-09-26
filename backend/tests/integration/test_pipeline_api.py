"""La API del pipeline, ya asíncrona (Milestone 32, ADR 0010).

`POST /api/pipeline/runs` **encola**: responde 202 con la ejecución en QUEUED y
sus nueve pasos en PENDING, y quien la ejecuta es un worker. Por eso estas pruebas
vacían la cola con el worker de verdad entre encolar y comprobar el resultado.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.jobs.worker import Worker
from app.main import app

#: La fábrica de sesiones de la base que usa el cliente de la prueba, para poder
#: levantar un worker contra ella.
_FACTORY: list = []


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    _FACTORY.append(session_factory)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        _FACTORY.clear()
        engine.dispose()


def drain(rounds: int = 12) -> None:
    """Ejecuta lo que la API solo encoló, con el worker del runtime."""
    db = _FACTORY[-1]()
    worker = Worker(name="test-worker")
    try:
        for _ in range(rounds):
            if worker.run_once(db) is None:
                break
    finally:
        db.close()


def enqueue(client: TestClient, **overrides) -> dict:
    payload = {"category": "home", "sale_price": 50.0, "destination_region": "mexico"}
    payload.update(overrides)
    response = client.post("/api/pipeline/runs", json=payload)
    assert response.status_code == 202, response.text
    return response.json()


def test_creating_a_run_queues_it_instead_of_executing_it(client: TestClient):
    body = enqueue(client)

    assert body["status"] == "QUEUED"
    assert body["product_id"] is None
    assert body["job_id"] is not None
    assert set(body["steps"].keys()) == {
        "research",
        "sourcing",
        "economics",
        "legal",
        "ecommerce",
        "marketplace",
        "marketing",
        "operations",
        "cfo",
    }
    assert {step["step_status"] for step in body["steps"].values()} == {"PENDING"}


def test_the_queued_job_is_visible_in_the_job_api(client: TestClient):
    body = enqueue(client)

    job = client.get(f"/api/jobs/{body['job_id']}").json()

    assert job["type"] == "pipeline.run"
    assert job["status"] == "QUEUED"
    assert job["correlation_id"] == body["correlation_id"]


def test_a_worker_completes_all_nine_steps(client: TestClient):
    body = enqueue(client)

    drain()

    run = client.get(f"/api/pipeline/runs/{body['correlation_id']}").json()
    assert run["status"] == "COMPLETED"
    assert run["product_id"] is not None
    assert {step["step_status"] for step in run["steps"].values()} == {"COMPLETED"}
    assert all(step["entity_id"] for step in run["steps"].values())


def test_the_run_detail_lists_every_attempt_of_every_step(client: TestClient):
    body = enqueue(client)
    drain()

    run = client.get(f"/api/pipeline/runs/{body['correlation_id']}").json()

    assert len(run["attempts"]) == 9
    assert {attempt["status"] for attempt in run["attempts"]} == {"COMPLETED"}
    assert {attempt["job_id"] for attempt in run["attempts"]} == {body["job_id"]}
    assert {attempt["step"] for attempt in run["attempts"]} == set(run["steps"].keys())


def test_a_run_is_partial_for_an_unknown_category(client: TestClient):
    body = enqueue(client, category="does-not-exist")

    drain()

    run = client.get(f"/api/pipeline/runs/{body['correlation_id']}").json()
    assert run["status"] == "PARTIAL"
    assert run["failed_step"] == "research"
    assert run["steps"]["research"]["step_status"] == "FAILED"
    assert run["steps"]["cfo"]["step_status"] == "SKIPPED"


def test_get_pipeline_run_404s_for_an_unknown_correlation_id(client: TestClient):
    response = client.get("/api/pipeline/runs/does-not-exist")

    assert response.status_code == 404


def test_list_pipeline_runs_returns_existing_runs_most_recent_first(client: TestClient):
    first = enqueue(client)
    second = enqueue(client, category="electronics")

    response = client.get("/api/pipeline/runs")

    assert response.status_code == 200
    correlation_ids = [item["correlation_id"] for item in response.json()]
    assert correlation_ids.index(second["correlation_id"]) < correlation_ids.index(first["correlation_id"])
    # Y cada una llega con sus pasos, en una sola consulta.
    assert all(len(item["steps"]) == 9 for item in response.json())


def test_cancelling_a_queued_run_stops_it_and_its_job(client: TestClient):
    body = enqueue(client)

    response = client.post(f"/api/pipeline/runs/{body['correlation_id']}/cancel", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert client.get(f"/api/jobs/{body['job_id']}").json()["status"] == "CANCELLED"

    drain()

    run = client.get(f"/api/pipeline/runs/{body['correlation_id']}").json()
    assert run["status"] == "CANCELLED"
    assert {step["step_status"] for step in run["steps"].values()} == {"PENDING"}


def test_cancelling_a_finished_run_is_409(client: TestClient):
    body = enqueue(client)
    drain()

    response = client.post(f"/api/pipeline/runs/{body['correlation_id']}/cancel", json={})

    assert response.status_code == 409


def test_a_cancelled_run_can_be_resumed_and_then_completes(client: TestClient):
    body = enqueue(client)
    client.post(f"/api/pipeline/runs/{body['correlation_id']}/cancel", json={})

    response = client.post(f"/api/pipeline/runs/{body['correlation_id']}/resume", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "QUEUED"

    drain()

    assert client.get(f"/api/pipeline/runs/{body['correlation_id']}").json()["status"] == "COMPLETED"


def test_resuming_a_completed_run_without_naming_a_step_is_409(client: TestClient):
    body = enqueue(client)
    drain()

    response = client.post(f"/api/pipeline/runs/{body['correlation_id']}/resume", json={})

    assert response.status_code == 409


def test_resuming_a_completed_run_from_a_named_step_redoes_that_step(client: TestClient):
    body = enqueue(client)
    drain()
    before = client.get(f"/api/pipeline/runs/{body['correlation_id']}").json()["steps"]

    response = client.post(
        f"/api/pipeline/runs/{body['correlation_id']}/resume", json={"from_step": "economics"}
    )
    assert response.status_code == 200
    assert response.json()["steps"]["economics"]["step_status"] == "PENDING"
    assert response.json()["steps"]["sourcing"]["step_status"] == "COMPLETED"

    drain()

    after = client.get(f"/api/pipeline/runs/{body['correlation_id']}").json()["steps"]
    assert after["sourcing"]["entity_id"] == before["sourcing"]["entity_id"]
    assert after["economics"]["entity_id"] != before["economics"]["entity_id"]


def test_resuming_from_an_unknown_step_is_404(client: TestClient):
    body = enqueue(client)
    client.post(f"/api/pipeline/runs/{body['correlation_id']}/cancel", json={})

    response = client.post(
        f"/api/pipeline/runs/{body['correlation_id']}/resume", json={"from_step": "accounting"}
    )

    assert response.status_code == 404
