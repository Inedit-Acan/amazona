from fastapi.testclient import TestClient

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
