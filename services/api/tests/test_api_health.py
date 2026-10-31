from fastapi.testclient import TestClient
from mindnest_api.main import create_app


def test_health_returns_ok_and_request_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "mindnest-api", "version": "0.1.0"}
    assert response.headers["x-request-id"]


def test_request_id_from_client_is_echoed() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


def test_unknown_route_uses_error_envelope() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/nope", headers={"x-request-id": "req-1"})
    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "http_404"
    assert body["request_id"] == "req-1"
    assert set(body) == {"code", "message", "details", "request_id"}
