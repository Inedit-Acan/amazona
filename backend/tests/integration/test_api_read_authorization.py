"""Milestone 29.1: quién puede LEER qué, comprobado sobre HTTP.

Mismo patrón que test_api_authorization.py para las mutadoras: todas las rutas
de lectura están inventariadas, y `test_the_inventory_covers_every_read_route`
falla si alguien añade un GET sin decidir a qué categoría pertenece.
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
from app.db.models.role import Role
from app.db.models.user import User
from app.db.session import get_db
from app.main import app

SUPABASE_URL = "https://example.supabase.co"

#: Públicas: una sonda de infraestructura no puede llevar un token.
PUBLIC_ROUTES = ["/health", "/health/ready"]

#: Diagnóstico del despliegue. Autenticado: junto con la versión del esquema y
#: el entorno, la lista de dominios simulados describe dónde el sistema
#: funciona con datos inventados.
DIAGNOSTIC_ROUTES = ["/health/detailed"]

#: La auditoría: identidad de quién hizo qué. Categoría propia.
AUDIT_ROUTES = ["/api/audit"]

#: Datos de negocio. Los siete roles pueden leerlos.
BUSINESS_ROUTES = [
    "/api/agents",
    "/api/agent-executions",
    "/api/approvals",
    "/api/cfo/runs",
    "/api/cfo/runs/cid-1",
    "/api/decisions?project_id=proj-1",
    "/api/decisions/dec-1",
    "/api/ecommerce/runs/cid-1",
    "/api/economics/analyses/timeseries",
    "/api/economics/runs/cid-1",
    "/api/incidents",
    "/api/legal/runs/cid-1",
    "/api/marketing/runs/cid-1",
    "/api/marketplace/runs/cid-1",
    "/api/operations/runs/cid-1",
    "/api/pipeline/kill-switch",
    "/api/pipeline/reviews",
    "/api/pipeline/runs",
    "/api/pipeline/runs/cid-1",
    "/api/products",
    "/api/products/p-1/campaigns",
    "/api/products/p-1/economics",
    "/api/products/p-1/legal",
    "/api/products/p-1/marketplace-listings",
    "/api/products/p-1/operations",
    "/api/products/p-1/storefronts",
    "/api/products/p-1/suppliers",
    "/api/projects",
    "/api/projects/proj-1",
    "/api/research/runs/cid-1",
    "/api/sourcing/runs/cid-1",
    "/api/tasks?project_id=proj-1",
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


def build_client(session_factory, public_key, environment: Environment) -> TestClient:
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_get_settings() -> Settings:
        return Settings(
            _env_file=None,
            environment=environment,
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
    return TestClient(app)


@pytest.fixture()
def client(session_factory, key_pair):
    _, public_key = key_pair
    try:
        yield build_client(session_factory, public_key, Environment.PRODUCTION)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def development_client(session_factory, key_pair):
    _, public_key = key_pair
    try:
        yield build_client(session_factory, public_key, Environment.DEVELOPMENT)
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
    found: list[APIRoute] = []
    for route in getattr(router, "routes", []):
        if isinstance(route, APIRoute):
            found.append(route)
        else:
            nested = getattr(route, "original_router", None) or (route if hasattr(route, "routes") else None)
            if nested is not None:
                found.extend(_api_routes(nested))
    return found


# --- El inventario no se queda atrás -----------------------------------------


def test_the_inventory_covers_every_read_route():
    """Un GET nuevo obliga a decidir su categoría. Es la diferencia entre una
    política y una costumbre."""
    actual = {
        route.path
        for route in _api_routes(app)
        for method in route.methods
        if method == "GET"
    }
    declared = {
        "/health",
        "/health/ready",
        "/health/detailed",
        "/api/audit",
        "/api/agents",
        "/api/agent-executions",
        "/api/approvals",
        "/api/cfo/runs",
        "/api/cfo/runs/{correlation_id}",
        "/api/decisions",
        "/api/decisions/{decision_id}",
        "/api/ecommerce/runs/{correlation_id}",
        "/api/economics/analyses/timeseries",
        "/api/economics/runs/{correlation_id}",
        "/api/incidents",
        "/api/legal/runs/{correlation_id}",
        "/api/marketing/runs/{correlation_id}",
        "/api/marketplace/runs/{correlation_id}",
        "/api/operations/runs/{correlation_id}",
        "/api/pipeline/kill-switch",
        "/api/pipeline/reviews",
        "/api/pipeline/runs",
        "/api/pipeline/runs/{correlation_id}",
        "/api/products",
        "/api/products/{product_id}/campaigns",
        "/api/products/{product_id}/economics",
        "/api/products/{product_id}/legal",
        "/api/products/{product_id}/marketplace-listings",
        "/api/products/{product_id}/operations",
        "/api/products/{product_id}/storefronts",
        "/api/products/{product_id}/suppliers",
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/research/runs/{correlation_id}",
        "/api/sourcing/runs/{correlation_id}",
        "/api/tasks",
    }

    assert actual == declared
    assert len(BUSINESS_ROUTES) + len(AUDIT_ROUTES) + len(DIAGNOSTIC_ROUTES) + len(PUBLIC_ROUTES) == len(declared)


# --- Público -----------------------------------------------------------------


@pytest.mark.parametrize("path", PUBLIC_ROUTES)
def test_probes_answer_without_a_token(client, path):
    assert client.get(path).status_code == 200


def test_the_public_probes_reveal_nothing_about_the_deployment(client):
    """Ni versión del esquema, ni entorno, ni proveedores: eso es huella
    dactilar del despliegue."""
    for path in PUBLIC_ROUTES:
        body = client.get(path).json()
        assert "migration" not in body
        assert "environment" not in body
        assert "providers" not in body
        assert "supabase_configured" not in body


def test_readiness_reports_degraded_when_the_database_is_gone(session_factory, key_pair):
    _, public_key = key_pair

    class UnreachableSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("database unreachable")

    def broken_db():
        yield UnreachableSession()

    client = build_client(session_factory, public_key, Environment.PRODUCTION)
    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}


# --- 401: sin identidad no se lee -------------------------------------------


@pytest.mark.parametrize("path", BUSINESS_ROUTES + AUDIT_ROUTES + DIAGNOSTIC_ROUTES)
def test_no_read_route_answers_without_a_token(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", BUSINESS_ROUTES + AUDIT_ROUTES + DIAGNOSTIC_ROUTES)
def test_no_read_route_accepts_an_invalid_token(client, path):
    assert client.get(path, headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401


# --- Negocio: los siete roles ------------------------------------------------


@pytest.mark.parametrize("path", BUSINESS_ROUTES)
def test_viewer_reads_every_business_route(client, key_pair, path):
    private_key, _ = key_pair
    response = client.get(path, headers={"Authorization": f"Bearer {token_for(private_key, RoleName.VIEWER)}"})

    # 404 es una respuesta legítima para un id que no existe: lo que importa es
    # que no sea 401 ni 403.
    assert response.status_code in (200, 404), f"{path} -> {response.status_code}"


@pytest.mark.parametrize("role", list(RoleName))
def test_every_role_reads_the_catalogue(client, key_pair, role):
    private_key, _ = key_pair

    response = client.get("/api/products", headers={"Authorization": f"Bearer {token_for(private_key, role)}"})

    assert response.status_code == 200


@pytest.mark.parametrize("role", list(RoleName))
def test_every_role_reads_the_diagnostics(client, key_pair, role):
    private_key, _ = key_pair

    response = client.get(
        "/health/detailed", headers={"Authorization": f"Bearer {token_for(private_key, role)}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == Environment.PRODUCTION
    assert "providers" in body


# --- Auditoría: más estrecha -------------------------------------------------


@pytest.mark.parametrize("role", [RoleName.OWNER, RoleName.ADMIN, RoleName.REVIEWER])
def test_the_audit_trail_is_readable_by_its_three_roles(client, key_pair, role):
    private_key, _ = key_pair

    response = client.get("/api/audit", headers={"Authorization": f"Bearer {token_for(private_key, role)}"})

    assert response.status_code == 200


@pytest.mark.parametrize("role", [RoleName.VIEWER, RoleName.OPERATOR, RoleName.ANALYST, RoleName.SYSTEM])
def test_the_audit_trail_is_denied_to_everyone_else(client, key_pair, role):
    private_key, _ = key_pair
    headers = {"Authorization": f"Bearer {token_for(private_key, role)}"}

    assert client.get("/api/audit", headers=headers).status_code == 403
    # …pero siguen leyendo el negocio: la restricción es de categoría, no del rol.
    assert client.get("/api/products", headers=headers).status_code == 200


def test_a_user_without_a_role_reads_nothing(client, key_pair, session_factory):
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

    assert client.get("/api/products", headers={"Authorization": f"Bearer {token}"}).status_code == 403


# --- Desarrollo no cambia ----------------------------------------------------


@pytest.mark.parametrize("path", ["/api/products", "/api/audit", "/health/detailed", "/health/ready"])
def test_development_keeps_every_read_open(development_client, path):
    """El entorno del propietario se comporta como antes del Milestone 29.1."""
    assert development_client.get(path).status_code == 200
