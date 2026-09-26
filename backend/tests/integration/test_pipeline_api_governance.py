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


# --- Las puertas del ActionGate (Milestone 33) ------------------------------

#: Economía NO_GO de verdad: el precio no cubre ni el coste, así que publicar
#: deja de ser automático.
NEEDS_APPROVAL = {"category": "home", "sale_price": 0.5, "destination_region": "mexico"}
#: Legal NO_GO de verdad: categoría restringida en la UE sin certificación.
LEGAL_NO_GO = {
    "category": "accessories",
    "sale_price": 50.0,
    "destination_region": "mexico",
    "market": "eu",
}


def test_a_gate_asks_in_the_same_tray_as_the_reviews(client: TestClient):
    created = client.post("/api/pipeline/runs", json=NEEDS_APPROVAL).json()

    drain()

    run = client.get(f"/api/pipeline/runs/{created['correlation_id']}").json()
    assert run["status"] == "WAITING_APPROVAL"
    assert run["steps"]["ecommerce"]["step_status"] == "WAITING_APPROVAL"

    reviews = client.get("/api/pipeline/reviews").json()
    assert len(reviews) == 1
    assert reviews[0]["kind"] == "ACTION_GATE"
    assert reviews[0]["step"] == "ecommerce"
    assert reviews[0]["action"] == "publish_product"


def test_approving_over_http_continues_the_run(client: TestClient):
    created = client.post("/api/pipeline/runs", json=NEEDS_APPROVAL).json()
    drain()
    review_id = client.get("/api/pipeline/reviews").json()[0]["id"]

    response = client.post(f"/api/pipeline/reviews/{review_id}/approve", json={"actor": "owner@amazona.local"})
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"

    # Aprobar ya la ha puesto de nuevo en cola: no hay que acordarse de reanudar.
    run = client.get(f"/api/pipeline/runs/{created['correlation_id']}").json()
    assert run["status"] == "QUEUED"

    drain()

    run = client.get(f"/api/pipeline/runs/{created['correlation_id']}").json()
    assert run["steps"]["ecommerce"]["step_status"] == "COMPLETED"


def test_rejecting_over_http_denies_that_step_and_the_chain_goes_on(client: TestClient):
    created = client.post("/api/pipeline/runs", json=NEEDS_APPROVAL).json()
    drain()
    review_id = client.get("/api/pipeline/reviews").json()[0]["id"]

    client.post(f"/api/pipeline/reviews/{review_id}/reject", json={"actor": "owner@amazona.local"})
    drain()

    run = client.get(f"/api/pipeline/runs/{created['correlation_id']}").json()
    assert run["steps"]["ecommerce"]["step_status"] == "DENIED"
    assert "rejected" in run["steps"]["ecommerce"]["error"]


def test_a_legal_no_go_never_reaches_the_tray_because_nobody_can_authorise_it(client: TestClient):
    """Un veto no se firma: la ejecución termina con sus acciones denegadas y lo
    que llega a la bandeja es la revisión post-hoc, no una puerta."""
    created = client.post("/api/pipeline/runs", json=LEGAL_NO_GO).json()

    drain()

    run = client.get(f"/api/pipeline/runs/{created['correlation_id']}").json()
    assert run["status"] == "COMPLETED"
    assert run["steps"]["marketing"]["step_status"] == "DENIED"

    kinds = {review["kind"] for review in client.get("/api/pipeline/reviews").json()}
    assert kinds == {"POST_HOC"}


def test_the_denials_are_queryable_in_the_audit_trail(client: TestClient):
    created = client.post("/api/pipeline/runs", json=LEGAL_NO_GO).json()
    drain()

    entries = client.get("/api/audit", params={"correlation_id": created["correlation_id"]}).json()

    denials = [entry for entry in entries if entry["action"] == "action_gate.deny"]
    assert len(denials) == 3
    assert all(entry["after"]["outcome"] == "DENY" for entry in denials)
