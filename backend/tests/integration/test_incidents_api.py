import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

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
        engine.dispose()


def test_list_incidents_returns_empty_list_when_none_reported(client: TestClient):
    response = client.get("/api/incidents")

    assert response.status_code == 200
    assert response.json() == []


def test_create_incident_persists_and_returns_it_open(client: TestClient):
    response = client.post(
        "/api/incidents",
        json={
            "title": "Backend unreachable",
            "description": "health/detailed timing out",
            "severity": "HIGH",
            "actor": "oncall@amazona.local",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["resolved_at"] is None
    assert body["severity"] == "HIGH"

    listed = client.get("/api/incidents").json()
    assert any(i["id"] == body["id"] for i in listed)


def test_create_incident_rejects_an_unknown_severity(client: TestClient):
    response = client.post(
        "/api/incidents",
        json={"title": "x", "severity": "APOCALYPTIC", "actor": "oncall@amazona.local"},
    )

    assert response.status_code == 422


def test_resolve_incident_marks_it_resolved_with_a_timestamp(client: TestClient):
    created = client.post(
        "/api/incidents",
        json={"title": "Backend unreachable", "severity": "CRITICAL", "actor": "oncall@amazona.local"},
    ).json()

    response = client.post(f"/api/incidents/{created['id']}/resolve", json={"actor": "oncall@amazona.local"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESOLVED"
    assert body["resolved_at"] is not None


def test_resolve_incident_twice_conflicts(client: TestClient):
    created = client.post(
        "/api/incidents",
        json={"title": "Backend unreachable", "severity": "LOW", "actor": "oncall@amazona.local"},
    ).json()
    client.post(f"/api/incidents/{created['id']}/resolve", json={"actor": "oncall@amazona.local"})

    response = client.post(f"/api/incidents/{created['id']}/resolve", json={"actor": "oncall@amazona.local"})

    assert response.status_code == 409


def test_resolve_incident_404s_for_an_unknown_id(client: TestClient):
    response = client.post("/api/incidents/does-not-exist/resolve", json={"actor": "oncall@amazona.local"})

    assert response.status_code == 404


def test_create_incident_audits_the_report(client: TestClient):
    created = client.post(
        "/api/incidents",
        json={"title": "Backend unreachable", "severity": "MEDIUM", "actor": "oncall@amazona.local"},
    ).json()

    audit = client.get("/api/audit").json()
    assert any(e["action"] == "incident.create" and e["resource"] == f"incident:{created['id']}" for e in audit)
