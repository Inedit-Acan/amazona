"""La API de trabajos (Milestone 31), incluida su autorización.

Encolar es una acción que hace trabajar al sistema, así que no la tiene todo el
mundo; mirar la cola es lectura de negocio y sí.
"""

import datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.actor import RoleName
from app.auth.dependencies import get_auth_service
from app.auth.service import AuthService
from app.core.config import Environment, Settings, get_settings
from app.db.base import Base
from app.db.models.job import Job
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_db
from app.jobs.handlers import DIAGNOSTIC_ECHO
from app.jobs.schemas import JobStatus
from app.main import app

SUPABASE_URL = "https://example.supabase.co"
USERS: dict[RoleName, str] = {role: f"sub-{role.value.lower()}" for role in RoleName}


@pytest.fixture()
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as seed:
        for role in RoleName:
            seed.add(Role(id=f"role-{role.value.lower()}", name=role.value))
        seed.flush()
        for role, subject in USERS.items():
            seed.add(
                User(
                    email=f"{role.value.lower()}@amazona.local",
                    role_id=f"role-{role.value.lower()}",
                    subject=subject,
                )
            )
        seed.commit()
    yield factory
    engine.dispose()


@pytest.fixture()
def client(session_factory, key_pair):
    _, public_key = key_pair

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        environment=Environment.PRODUCTION,
        supabase_url=SUPABASE_URL,
        supabase_anon_key="anon-key",
        cors_origins=["https://kova.example"],
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(
        supabase_url=SUPABASE_URL, audience="authenticated", get_signing_key=lambda token: public_key
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def headers_for(private_key, role: RoleName) -> dict[str, str]:
    now = datetime.datetime.now(datetime.UTC)
    token = jwt.encode(
        {
            "sub": USERS[role],
            "email": f"{role.value.lower()}@amazona.local",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "aud": "authenticated",
            "exp": now + datetime.timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


# --- Encolar -----------------------------------------------------------------


def test_enqueuing_creates_a_queued_job_without_running_it(client, key_pair, session_factory):
    private_key, _ = key_pair

    response = client.post(
        "/api/jobs",
        json={"type": DIAGNOSTIC_ECHO, "payload": {"hola": "mundo"}},
        headers=headers_for(private_key, RoleName.OPERATOR),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == JobStatus.QUEUED
    assert body["attempt"] == 0
    # La identidad verificada, no un nombre del cuerpo.
    assert body["created_by"] == "operator@amazona.local"
    with session_factory() as db:
        assert db.query(Job).count() == 1


def test_an_unknown_type_is_rejected_on_the_spot(client, key_pair):
    """Mejor un 404 al que llama que un trabajo que muere en la cola."""
    private_key, _ = key_pair

    response = client.post(
        "/api/jobs",
        json={"type": "nope.does-not-exist"},
        headers=headers_for(private_key, RoleName.OPERATOR),
    )

    assert response.status_code == 404
    assert "no handler registered" in response.json()["detail"]


def test_the_same_idempotency_key_returns_the_same_job(client, key_pair, session_factory):
    private_key, _ = key_pair
    headers = headers_for(private_key, RoleName.OPERATOR)
    body = {"type": DIAGNOSTIC_ECHO, "idempotency_key": "k-1"}

    first = client.post("/api/jobs", json=body, headers=headers).json()
    second = client.post("/api/jobs", json=body, headers=headers).json()

    assert first["id"] == second["id"]
    with session_factory() as db:
        assert db.query(Job).count() == 1


# --- Leer --------------------------------------------------------------------


def test_the_detail_shows_attempts_and_the_event_trail(client, key_pair):
    private_key, _ = key_pair
    created = client.post(
        "/api/jobs", json={"type": DIAGNOSTIC_ECHO}, headers=headers_for(private_key, RoleName.OPERATOR)
    ).json()

    detail = client.get(f"/api/jobs/{created['id']}", headers=headers_for(private_key, RoleName.VIEWER)).json()

    assert detail["attempts"] == []
    assert [e["kind"] for e in detail["events"]] == ["enqueued"]


def test_jobs_can_be_filtered_by_status(client, key_pair):
    private_key, _ = key_pair
    headers = headers_for(private_key, RoleName.OPERATOR)
    client.post("/api/jobs", json={"type": DIAGNOSTIC_ECHO}, headers=headers)

    queued = client.get("/api/jobs?status=QUEUED", headers=headers).json()
    completed = client.get("/api/jobs?status=COMPLETED", headers=headers).json()

    assert len(queued) == 1
    assert completed == []


def test_the_known_types_are_published(client, key_pair):
    private_key, _ = key_pair

    types = client.get("/api/jobs/types", headers=headers_for(private_key, RoleName.VIEWER)).json()["types"]

    assert DIAGNOSTIC_ECHO in types
    assert "research.run" in types


# --- Cancelar y reencolar ----------------------------------------------------


def test_a_job_can_be_cancelled(client, key_pair):
    private_key, _ = key_pair
    headers = headers_for(private_key, RoleName.OPERATOR)
    created = client.post("/api/jobs", json={"type": DIAGNOSTIC_ECHO}, headers=headers).json()

    response = client.post(f"/api/jobs/{created['id']}/cancel", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.CANCELLED


def test_a_cancelled_job_can_be_requeued(client, key_pair):
    private_key, _ = key_pair
    headers = headers_for(private_key, RoleName.OPERATOR)
    created = client.post("/api/jobs", json={"type": DIAGNOSTIC_ECHO}, headers=headers).json()
    client.post(f"/api/jobs/{created['id']}/cancel", headers=headers)

    response = client.post(f"/api/jobs/{created['id']}/requeue", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.QUEUED


def test_cancelling_something_that_does_not_exist_is_a_404(client, key_pair):
    private_key, _ = key_pair

    response = client.post("/api/jobs/nope/cancel", headers=headers_for(private_key, RoleName.OPERATOR))

    assert response.status_code == 404


# --- Autorización ------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/jobs", "/api/jobs/types", "/api/jobs/anything"])
def test_reading_the_queue_needs_identity(client, path):
    assert client.get(path).status_code == 401


def test_enqueuing_needs_identity(client):
    assert client.post("/api/jobs", json={"type": DIAGNOSTIC_ECHO}).status_code == 401


@pytest.mark.parametrize("role", [RoleName.OWNER, RoleName.ADMIN, RoleName.OPERATOR, RoleName.SYSTEM])
def test_the_roles_that_may_enqueue(client, key_pair, role):
    private_key, _ = key_pair

    response = client.post(
        "/api/jobs", json={"type": DIAGNOSTIC_ECHO}, headers=headers_for(private_key, role)
    )

    assert response.status_code == 201


@pytest.mark.parametrize("role", [RoleName.VIEWER, RoleName.ANALYST, RoleName.REVIEWER])
def test_the_roles_that_may_not_enqueue_can_still_watch(client, key_pair, role):
    """Ver lo que hace el sistema no es lo mismo que hacerle trabajar."""
    private_key, _ = key_pair
    headers = headers_for(private_key, role)

    assert client.post("/api/jobs", json={"type": DIAGNOSTIC_ECHO}, headers=headers).status_code == 403
    assert client.get("/api/jobs", headers=headers).status_code == 200


@pytest.mark.parametrize("role", [RoleName.VIEWER, RoleName.ANALYST, RoleName.REVIEWER])
def test_the_same_roles_may_not_cancel_or_requeue(client, key_pair, role):
    private_key, _ = key_pair
    owner = headers_for(private_key, RoleName.OWNER)
    created = client.post("/api/jobs", json={"type": DIAGNOSTIC_ECHO}, headers=owner).json()
    headers = headers_for(private_key, role)

    assert client.post(f"/api/jobs/{created['id']}/cancel", headers=headers).status_code == 403
    assert client.post(f"/api/jobs/{created['id']}/requeue", headers=headers).status_code == 403
