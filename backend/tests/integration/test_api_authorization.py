"""Milestone 29 acceptance criteria, exercised over HTTP in a production-shaped
environment.

Every mutating route in the API appears in MUTATING_ROUTES. A route added later
without a thought for who may call it will fail `test_the_route_table_covers_every_mutating_route`.
"""

import datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.actor import RoleName
from app.auth.dependencies import get_auth_service
from app.auth.service import AuthService
from app.core.config import Environment, Settings, get_settings
from app.db.base import Base
from app.db.models.audit import AuditLog
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.permissions.policies import ApiAction

SUPABASE_URL = "https://example.supabase.co"

#: (method, path, body, action). The body only has to be good enough to reach
#: the dependency: FastAPI resolves dependencies before validating it, so a 401
#: or a 403 wins over a 422.
MUTATING_ROUTES: list[tuple[str, str, dict, ApiAction]] = [
    ("POST", "/api/objectives", {"title": "T", "created_by": "x", "context": {}}, ApiAction.OBJECTIVE_WRITE),
    ("POST", "/api/objectives/obj-1/run", {}, ApiAction.OBJECTIVE_WRITE),
    ("POST", "/api/approvals/ap-1/approve", {"actor": "x"}, ApiAction.APPROVAL_RESOLVE),
    ("POST", "/api/approvals/ap-1/reject", {"actor": "x"}, ApiAction.APPROVAL_RESOLVE),
    ("POST", "/api/research/runs", {"category": "c", "keywords": [], "max_results": 1}, ApiAction.AGENT_RUN),
    ("POST", "/api/sourcing/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/economics/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/legal/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/ecommerce/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/marketplace/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/marketing/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/operations/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/cfo/runs", {}, ApiAction.AGENT_RUN),
    ("POST", "/api/pipeline/runs", {}, ApiAction.PIPELINE_RUN),
    # Reanudar y cancelar son la misma acción que arrancar: quien puede poner al
    # sistema a trabajar puede continuar y parar lo que ya empezó (Milestone 32).
    ("POST", "/api/pipeline/runs/cid-1/resume", {}, ApiAction.PIPELINE_RUN),
    ("POST", "/api/pipeline/runs/cid-1/cancel", {}, ApiAction.PIPELINE_RUN),
    ("POST", "/api/pipeline/reviews/rev-1/approve", {"actor": "x"}, ApiAction.REVIEW_RESOLVE),
    ("POST", "/api/pipeline/reviews/rev-1/reject", {"actor": "x"}, ApiAction.REVIEW_RESOLVE),
    ("POST", "/api/pipeline/kill-switch", {"enabled": True, "actor": "x"}, ApiAction.KILL_SWITCH_WRITE),
    ("POST", "/api/incidents", {"title": "T", "severity": "LOW", "actor": "x"}, ApiAction.INCIDENT_WRITE),
    ("POST", "/api/incidents/inc-1/resolve", {"actor": "x"}, ApiAction.INCIDENT_WRITE),
    ("POST", "/api/jobs", {"type": "diagnostic.echo"}, ApiAction.JOB_WRITE),
    ("POST", "/api/jobs/job-1/cancel", {}, ApiAction.JOB_WRITE),
    ("POST", "/api/jobs/job-1/requeue", {}, ApiAction.JOB_WRITE),
]

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

    # What the Milestone 29 migration seeds, plus one user per role.
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

    def override_get_settings() -> Settings:
        return Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            supabase_url=SUPABASE_URL,
            supabase_anon_key="anon-key",
            cors_origins=["https://kova.example"],
        )

    def override_get_auth_service() -> AuthService:
        return AuthService(
            supabase_url=SUPABASE_URL, audience="authenticated", get_signing_key=lambda token: public_key
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_auth_service] = override_get_auth_service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def token_for(private_key, role: RoleName) -> str:
    now = datetime.datetime.now(datetime.UTC)
    return jwt.encode(
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


def _api_routes(router) -> list[APIRoute]:
    """Every APIRoute reachable from the app.

    `include_router` does not flatten its routes into `app.routes` in this
    FastAPI version: each included router stays wrapped in a `_IncludedRouter`
    that exposes the real one as `original_router`, so this walks down."""
    found: list[APIRoute] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            found.append(route)
        else:
            nested = getattr(route, "original_router", None) or (route if hasattr(route, "routes") else None)
            if nested is not None:
                found.extend(_api_routes(nested))
    return found


def call(client: TestClient, route, token: str | None = None):
    method, path, body, _ = route
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.request(method, path, json=body, headers=headers)


# --- El inventario no se queda atrás -----------------------------------------


def test_the_route_table_covers_every_mutating_route():
    """A new POST/PUT/PATCH/DELETE must be added to MUTATING_ROUTES, which is
    the same as saying: it must be given an ApiAction."""
    declared = {(method, path) for method, path, _, _ in MUTATING_ROUTES}
    actual = {
        (method, route.path)
        for route in _api_routes(app)
        for method in route.methods
        if method in {"POST", "PUT", "PATCH", "DELETE"}
    }
    # The table uses concrete ids; compare on the templated form.
    templated = {
        ("POST", "/api/objectives"),
        ("POST", "/api/objectives/{objective_id}/run"),
        ("POST", "/api/approvals/{approval_id}/approve"),
        ("POST", "/api/approvals/{approval_id}/reject"),
        ("POST", "/api/research/runs"),
        ("POST", "/api/sourcing/runs"),
        ("POST", "/api/economics/runs"),
        ("POST", "/api/legal/runs"),
        ("POST", "/api/ecommerce/runs"),
        ("POST", "/api/marketplace/runs"),
        ("POST", "/api/marketing/runs"),
        ("POST", "/api/operations/runs"),
        ("POST", "/api/cfo/runs"),
        ("POST", "/api/pipeline/runs"),
        ("POST", "/api/pipeline/runs/{correlation_id}/resume"),
        ("POST", "/api/pipeline/runs/{correlation_id}/cancel"),
        ("POST", "/api/pipeline/reviews/{review_id}/approve"),
        ("POST", "/api/pipeline/reviews/{review_id}/reject"),
        ("POST", "/api/pipeline/kill-switch"),
        ("POST", "/api/incidents"),
        ("POST", "/api/incidents/{incident_id}/resolve"),
        ("POST", "/api/jobs"),
        ("POST", "/api/jobs/{job_id}/cancel"),
        ("POST", "/api/jobs/{job_id}/requeue"),
    }
    assert actual == templated
    assert len(declared) == len(templated)


# --- 401: sin identidad no se muta ------------------------------------------


@pytest.mark.parametrize("route", MUTATING_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
def test_no_mutating_route_runs_without_a_token(client, route):
    assert call(client, route).status_code == 401


@pytest.mark.parametrize("route", MUTATING_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
def test_no_mutating_route_accepts_an_invalid_token(client, route):
    assert call(client, route, token="not-a-real-token").status_code == 401


# --- 403: el rol decide ------------------------------------------------------


@pytest.mark.parametrize("route", MUTATING_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
def test_viewer_cannot_mutate_anything(client, key_pair, route):
    private_key, _ = key_pair

    assert call(client, route, token=token_for(private_key, RoleName.VIEWER)).status_code == 403


def test_analyst_cannot_use_the_kill_switch(client, key_pair):
    private_key, _ = key_pair
    kill_switch = next(r for r in MUTATING_ROUTES if r[3] is ApiAction.KILL_SWITCH_WRITE)

    assert call(client, kill_switch, token=token_for(private_key, RoleName.ANALYST)).status_code == 403


def test_operator_cannot_use_the_kill_switch(client, key_pair):
    private_key, _ = key_pair
    kill_switch = next(r for r in MUTATING_ROUTES if r[3] is ApiAction.KILL_SWITCH_WRITE)

    assert call(client, kill_switch, token=token_for(private_key, RoleName.OPERATOR)).status_code == 403


def test_operator_cannot_resolve_approvals(client, key_pair):
    private_key, _ = key_pair
    approval = next(r for r in MUTATING_ROUTES if r[3] is ApiAction.APPROVAL_RESOLVE)

    assert call(client, approval, token=token_for(private_key, RoleName.OPERATOR)).status_code == 403


def test_reviewer_cannot_start_a_pipeline(client, key_pair):
    private_key, _ = key_pair
    pipeline = next(r for r in MUTATING_ROUTES if r[3] is ApiAction.PIPELINE_RUN)

    assert call(client, pipeline, token=token_for(private_key, RoleName.REVIEWER)).status_code == 403


def test_a_valid_token_for_someone_with_no_role_is_denied(client, key_pair, session_factory):
    """Authenticated is not the same as authorized: an account that exists but
    has no role assigned can do nothing."""
    private_key, _ = key_pair
    with session_factory() as db:
        db.add(User(email="nobody@amazona.local", role_id=None, subject="sub-nobody"))
        db.commit()

    now = datetime.datetime.now(datetime.UTC)
    token = jwt.encode(
        {
            "sub": "sub-nobody",
            "email": "nobody@amazona.local",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "aud": "authenticated",
            "exp": now + datetime.timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
    )

    assert call(client, MUTATING_ROUTES[0], token=token).status_code == 403


# --- Lo que sí se permite ----------------------------------------------------


@pytest.mark.parametrize("role", [RoleName.OWNER, RoleName.ADMIN])
def test_owner_and_admin_hold_the_kill_switch(client, key_pair, role):
    private_key, _ = key_pair
    response = client.post(
        "/api/pipeline/kill-switch",
        json={"enabled": False, "reason": "drill", "actor": "someone-else@example.com"},
        headers={"Authorization": f"Bearer {token_for(private_key, role)}"},
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_analyst_can_run_an_analysis_agent(client, key_pair):
    private_key, _ = key_pair
    response = client.post(
        "/api/research/runs",
        json={"category": "hydration", "keywords": ["bottle"], "max_results": 2},
        headers={"Authorization": f"Bearer {token_for(private_key, RoleName.ANALYST)}"},
    )

    assert response.status_code == 201


def test_operator_can_open_an_incident(client, key_pair):
    private_key, _ = key_pair
    response = client.post(
        "/api/incidents",
        json={"title": "Backend slow", "severity": "LOW", "actor": "someone-else@example.com"},
        headers={"Authorization": f"Bearer {token_for(private_key, RoleName.OPERATOR)}"},
    )

    assert response.status_code == 201


# --- La auditoría no se puede falsear ---------------------------------------


def test_the_audited_actor_is_the_token_not_the_body(client, key_pair, session_factory):
    """Plan maestro §P0.3: an `actor` sent by the frontend is ignored in
    production, and the audit row records the role and that it was verified."""
    private_key, _ = key_pair
    client.post(
        "/api/pipeline/kill-switch",
        json={"enabled": False, "reason": "drill", "actor": "impersonated@attacker.example"},
        headers={"Authorization": f"Bearer {token_for(private_key, RoleName.ADMIN)}"},
    )

    with session_factory() as db:
        entry = db.query(AuditLog).filter(AuditLog.action.like("pipeline_kill_switch.%")).one()

    assert entry.actor == "admin@amazona.local"
    assert entry.actor != "impersonated@attacker.example"
    assert entry.actor_role == RoleName.ADMIN
    assert entry.actor_source == "token"


def test_an_incident_records_the_verified_identity(client, key_pair, session_factory):
    private_key, _ = key_pair
    client.post(
        "/api/incidents",
        json={"title": "T", "severity": "HIGH", "actor": "impersonated@attacker.example"},
        headers={"Authorization": f"Bearer {token_for(private_key, RoleName.OPERATOR)}"},
    )

    with session_factory() as db:
        entry = db.query(AuditLog).filter_by(action="incident.create").one()

    assert entry.actor == "operator@amazona.local"
    assert entry.actor_role == RoleName.OPERATOR
    assert entry.actor_source == "token"


# --- Lectura -----------------------------------------------------------------
#
# La política completa de lectura vive en test_api_read_authorization.py; aquí
# solo queda la comprobación de que dejó de estar abierta.


def test_read_endpoints_are_no_longer_open(client):
    assert client.get("/api/agents").status_code == 401
    assert client.get("/api/incidents").status_code == 401
