import datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_auth_service
from app.auth.service import AuthService
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def auth_client(key_pair):
    _, public_key = key_pair
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

    def override_get_settings() -> Settings:
        return Settings(_env_file=None, require_auth=True, supabase_url="https://example.supabase.co")

    def override_get_auth_service() -> AuthService:
        return AuthService(
            supabase_url="https://example.supabase.co",
            audience="authenticated",
            get_signing_key=lambda token: public_key,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_auth_service] = override_get_auth_service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_auth_service, None)
        engine.dispose()


def make_token(private_key, sub: str = "user-123") -> str:
    now = datetime.datetime.now(datetime.UTC)
    return jwt.encode(
        {
            "sub": sub,
            "email": "owner@amazona.local",
            "iss": "https://example.supabase.co/auth/v1",
            "aud": "authenticated",
            "exp": now + datetime.timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
    )


def test_create_objective_requires_a_bearer_token_when_auth_is_enabled(auth_client: TestClient):
    response = auth_client.post(
        "/api/objectives", json={"title": "T", "created_by": "someone@amazona.local", "context": {}}
    )

    assert response.status_code == 401


def test_create_objective_rejects_an_invalid_token(auth_client: TestClient):
    response = auth_client.post(
        "/api/objectives",
        json={"title": "T", "created_by": "someone@amazona.local", "context": {}},
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


def test_create_objective_accepts_a_valid_token_and_uses_its_sub_as_created_by(auth_client: TestClient, key_pair):
    private_key, _ = key_pair
    token = make_token(private_key, sub="user-abc")

    response = auth_client.post(
        "/api/objectives",
        json={"title": "T", "created_by": "someone-else@amazona.local", "context": {}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    # The email claim is what a human reads in the audit trail; the sub is what
    # the row is keyed by.
    assert response.json()["created_by"] == "owner@amazona.local"


def test_read_endpoints_require_auth_too(auth_client: TestClient):
    """Hasta el Milestone 29.1 las lecturas estaban abiertas. Ya no: donde se
    exige identidad, se exige para leer igual que para escribir."""
    assert auth_client.get("/api/agents").status_code == 401


def test_liveness_and_readiness_stay_public(auth_client: TestClient):
    """Una sonda de infraestructura no puede llevar un token."""
    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/health/ready").status_code == 200
