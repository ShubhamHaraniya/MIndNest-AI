"""Production hardening: headers, cookies, hidden docs, refusing unsafe settings, no leaked errors.

Most of these build their own app in "production" mode and never touch the database.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mindnest_api.deps import clear_session_cookie, set_session_cookie
from mindnest_api.main import create_app
from mindnest_core.settings import get_settings
from starlette.responses import Response


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(get_settings(), "environment", "production")
    return create_app()


# ------------------------------------------------------------------ headers


def test_every_api_response_carries_safe_headers(client: TestClient) -> None:
    for path in ("/api/v1/health", "/api/v1/auth/me", "/api/v1/does-not-exist"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"
        assert "default-src 'none'" in headers["content-security-policy"]
        assert headers["cross-origin-resource-policy"] == "same-origin"
        assert "x-request-id" in headers
        assert "strict-transport-security" not in headers  # plain http in development


def test_production_adds_hsts(production: FastAPI) -> None:
    response = TestClient(production).get("/api/v1/health")
    assert response.headers["strict-transport-security"].startswith("max-age=")


def test_routes_keep_headers_they_set_themselves() -> None:
    from mindnest_api.middleware import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, hsts=False)

    @app.get("/x")
    def x() -> Response:
        return Response("hi", headers={"Cache-Control": "private, max-age=60"})

    headers = TestClient(app).get("/x").headers
    assert headers["cache-control"] == "private, max-age=60"
    assert headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------------------------ docs and schema


def test_docs_and_schema_exist_only_in_development(client: TestClient, production: FastAPI) -> None:
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/v1/openapi.json").status_code == 200

    prod = TestClient(production)
    for path in ("/api/docs", "/api/redoc", "/api/v1/openapi.json", "/docs", "/openapi.json", "/redoc"):
        assert prod.get(path).status_code == 404, path
    # The schema can still be generated in code (scripts/export_openapi.py uses this).
    assert production.openapi()["paths"]


# ------------------------------------------------------------------ cookies


def _cookie_header(environment: str, monkeypatch: pytest.MonkeyPatch, clear: bool = False) -> str:
    monkeypatch.setattr(get_settings(), "environment", environment)
    response = Response()
    clear_session_cookie(response) if clear else set_session_cookie(response, "token-value")
    return response.headers["set-cookie"].lower()


def test_session_cookie_is_locked_down_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    for clear in (False, True):
        cookie = _cookie_header("production", monkeypatch, clear)
        assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
        assert "path=/" in cookie


def test_session_cookie_works_over_plain_http_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    cookie = _cookie_header("development", monkeypatch)
    assert "httponly" in cookie and "secure" not in cookie


# ------------------------------------------------------------------ start-up checks


def test_production_refuses_to_start_with_the_development_secret(production: FastAPI) -> None:
    assert get_settings().secret_key == "dev-only-secret-change-me"
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        with TestClient(production):
            pass


# ------------------------------------------------------------------ errors and CORS


def test_unexpected_errors_do_not_leak_details() -> None:
    app = create_app()

    @app.get("/api/v1/boom")
    def boom() -> None:
        raise RuntimeError("secret-internal-detail /srv/app/db.py line 42")

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/boom")
    assert response.status_code == 500
    assert "secret-internal-detail" not in response.text
    assert "Traceback" not in response.text and "/srv/app" not in response.text


def test_other_websites_get_no_cross_origin_access(client: TestClient) -> None:
    evil = {"Origin": "https://evil.example.net"}
    response = client.get("/api/v1/health", headers=evil)
    assert "access-control-allow-origin" not in response.headers
    preflight = client.options(
        "/api/v1/auth/login",
        headers={**evil, "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_validation_errors_do_not_echo_server_internals(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": 5})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "Traceback" not in response.text
