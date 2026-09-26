import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.jobs.worker import Worker
from app.main import app

#: La fábrica de sesiones de la base que usa el cliente, para poder levantar un
#: worker contra ella: desde el Milestone 32 la API encola y el worker ejecuta.
_FACTORY: list = []


def drain(rounds: int = 12) -> None:
    db = _FACTORY[-1]()
    worker = Worker(name="test-worker")
    try:
        for _ in range(rounds):
            if worker.run_once(db) is None:
                break
    finally:
        db.close()


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


def test_get_kill_switch_defaults_to_enabled(client: TestClient):
    response = client.get("/api/pipeline/kill-switch")

    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_disabling_the_kill_switch_blocks_new_pipeline_runs(client: TestClient):
    disable_response = client.post(
        "/api/pipeline/kill-switch",
        json={"enabled": False, "reason": "incident", "actor": "ops@amazona.local"},
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False

    run_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )
    assert run_response.status_code == 423


def test_re_enabling_the_kill_switch_unblocks_pipeline_runs(client: TestClient):
    client.post("/api/pipeline/kill-switch", json={"enabled": False, "actor": "ops@amazona.local"})
    client.post("/api/pipeline/kill-switch", json={"enabled": True, "actor": "ops@amazona.local"})

    run_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )
    assert run_response.status_code == 202


def test_a_risky_run_appears_in_pending_reviews_and_can_be_approved(client: TestClient):
    run_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 0.5, "destination_region": "mexico"},
    )
    assert run_response.status_code == 202

    drain()

    run = client.get(f"/api/pipeline/runs/{run_response.json()['correlation_id']}").json()
    assert run["needs_review"] is True

    reviews = client.get("/api/pipeline/reviews").json()
    assert len(reviews) == 1
    review_id = reviews[0]["id"]
    assert reviews[0]["status"] == "PENDING"

    approve_response = client.post(
        f"/api/pipeline/reviews/{review_id}/approve", json={"actor": "owner@amazona.local"}
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "APPROVED"
    assert approve_response.json()["resolved_by"] == "owner@amazona.local"

    # No longer pending.
    assert client.get("/api/pipeline/reviews").json() == []


def test_approving_an_already_resolved_review_is_409(client: TestClient):
    run_response = client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 0.5, "destination_region": "mexico"},
    )
    drain()
    review_id = client.get("/api/pipeline/reviews").json()[0]["id"]
    client.post(f"/api/pipeline/reviews/{review_id}/reject", json={"actor": "owner@amazona.local"})

    replay_response = client.post(
        f"/api/pipeline/reviews/{review_id}/approve", json={"actor": "owner@amazona.local"}
    )

    assert replay_response.status_code == 409
    assert run_response.status_code == 202


def test_a_healthy_run_never_appears_in_pending_reviews(client: TestClient):
    client.post(
        "/api/pipeline/runs",
        json={"category": "home", "sale_price": 50.0, "destination_region": "mexico"},
    )
    drain()

    assert client.get("/api/pipeline/reviews").json() == []
