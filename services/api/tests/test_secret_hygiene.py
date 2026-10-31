"""Secrets stay on the server: provider keys, password hashes and session tokens are never
returned, logged or exported."""

import logging

KEY = "sk-hygiene-9f8e7d6c5b4a3210"
FORBIDDEN_FIELDS = {"api_key", "ciphertext", "password_hash", "token_hash", "storage_key"}
# Request bodies may carry a key (that is how it is saved); responses never do.
REQUEST_ONLY = {"ProviderKeyIn", "ProviderSave", "ProviderIn", "KeyIn"}


def test_saved_key_appears_in_no_read_endpoint_response(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    assert user.request("PUT", "/settings/providers/openai", json={"api_key": KEY}).status_code == 200
    user.post("/subjects", json={"name": "Hygiene check"})
    for path in (
        "/auth/me",
        "/me/security",
        "/me/sessions",
        "/me/export",
        "/settings/providers",
        "/subjects",
        "/notifications",
        "/dashboard",
    ):
        response = user.get(path)
        assert response.status_code < 500, (path, response.text)
        assert KEY not in response.text, path
        assert KEY[-10:] not in response.text.replace(KEY[-4:], ""), path


def test_saved_key_is_not_written_to_the_logs(make_user, caplog):  # type: ignore[no-untyped-def]
    user = make_user()
    with caplog.at_level(logging.DEBUG):
        user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
        user.get("/settings/providers")
        user.request("PUT", "/settings/providers/openai", json={"api_key": "x"})  # a rejected one
    assert KEY not in caplog.text


def test_session_token_never_comes_back_in_a_body(anon, make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    login = anon.post("/auth/login", json={"email": user.email, "password": "correct horse battery"})
    assert login.status_code == 200
    token = login.cookies.get("mindnest_session") or user.token
    assert token and token not in login.text
    assert token not in user.get("/me/sessions").text
    assert token not in user.get("/me/export").text


def test_no_response_schema_exposes_a_secret_field(app):  # type: ignore[no-untyped-def]
    schemas = app.openapi()["components"]["schemas"]
    leaking = {
        name: sorted(FORBIDDEN_FIELDS & set(schema.get("properties", {})))
        for name, schema in schemas.items()
        if name not in REQUEST_ONLY and not name.endswith(("In", "Body", "Create", "Update", "Request"))
    }
    leaking = {name: fields for name, fields in leaking.items() if fields}
    assert not leaking, f"response models with secret fields: {leaking}"
