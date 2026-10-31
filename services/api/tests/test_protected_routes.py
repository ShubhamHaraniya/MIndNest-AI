"""Every route is private unless it is on the short public list below.

A new route that forgets its AuthUser dependency makes this test fail, which is the point.
"""

import re
import uuid

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/ready"),
    ("POST", "/api/v1/auth/signup"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
    # Sign in with Google: public by nature; the signed state cookie is what protects them.
    ("GET", "/api/v1/auth/providers"),
    ("GET", "/api/v1/auth/google/start"),
    ("GET", "/api/v1/auth/google/callback"),
    # The Google Calendar callback checks its signed cookie and the signed-in student itself.
    ("GET", "/api/v1/integrations/google-calendar/callback"),
}


def test_every_non_public_route_rejects_anonymous_requests(app, client):  # type: ignore[no-untyped-def]
    # Enumerate routes from the OpenAPI document rather than app.routes: it is the public
    # contract, and it does not depend on FastAPI's internal route classes.
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            method = method.upper()
            if method not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                continue
            if (method, path) in PUBLIC:
                continue
            url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
            response = client.request(method, url, json={})
            assert response.status_code == 401, f"{method} {path} answered {response.status_code}"
            checked += 1
    client.cookies.clear()
    assert checked >= 10, f"route discovery found suspiciously few protected routes ({checked})"


def test_a_garbage_session_cookie_is_rejected(client):  # type: ignore[no-untyped-def]
    response = client.get("/api/v1/auth/me", headers={"cookie": "mindnest_session=garbage"})
    client.cookies.clear()
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"
