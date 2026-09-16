from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app

client = TestClient(app)


def test_health_returns_200_with_status_ok():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "amazona-backend"


def test_response_includes_a_correlation_id_header():
    response = client.get("/health")

    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) > 0


def test_incoming_correlation_id_is_echoed_back():
    response = client.get("/health", headers={"X-Correlation-ID": "test-correlation-id"})

    assert response.headers["X-Correlation-ID"] == "test-correlation-id"


def test_control_center_origin_is_allowed_by_cors():
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_health_detailed_returns_503_when_database_is_unreachable():
    # Forces the failure deterministically instead of relying on ambient
    # DATABASE_URL: that's unreachable in a sandbox with no Postgres
    # running, but CI's own workflow points it at a live service
    # container, so the two environments would otherwise disagree here.
    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("simulated unreachable database"))

    def override_get_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health/detailed")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    body = response.json()
    assert body["database"] == "error"
    assert body["migration"] is None


def test_health_detailed_returns_200_with_migration_version_when_database_is_reachable():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    session.execute(text("INSERT INTO alembic_version VALUES ('abc123')"))
    session.commit()

    def override_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health/detailed")
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["database"] == "ok"
    assert body["migration"] == "abc123"
    assert "supabase_configured" in body
