import secrets
from pathlib import Path

import pytest
from mindnest_core.prodcheck import DEV_SECRET, check, main, parse_env


def good() -> dict[str, str]:
    return {
        "DOMAIN": "study.myschool.org",
        "ACME_EMAIL": "admin@myschool.org",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "APP_DB_PASSWORD": secrets.token_hex(24),
        "EVAL_DB_PASSWORD": secrets.token_hex(24),
        "REDIS_PASSWORD": secrets.token_hex(24),
        "S3_ACCESS_KEY": secrets.token_hex(8),
        "S3_SECRET_KEY": secrets.token_hex(24),
        "S3_BUCKET": "mindnest-materials",
        "COMPOSE_PROFILES": "storage,models",
        "SMTP_HOST": "smtp.mailprovider.net",
        "SMTP_PORT": "587",
        "SMTP_SECURITY": "starttls",
        "SMTP_USER": "apikey",
        "SMTP_PASSWORD": secrets.token_hex(16),
        "MAIL_FROM": "MindNest AI <no-reply@myschool.org>",
        "BACKUP_DIR": "/srv/backups",
    }


def errors(env: dict[str, str]) -> dict[str, str]:
    return {f.key: f.message for f in check(env) if f.level == "error"}


def test_a_complete_file_has_no_errors() -> None:
    assert errors(good()) == {}


@pytest.mark.parametrize(
    "key,value",
    [
        ("SECRET_KEY", DEV_SECRET),
        ("SECRET_KEY", "short"),
        ("SECRET_KEY", ""),
        ("POSTGRES_PASSWORD", "mindnest"),
        ("APP_DB_PASSWORD", "tooshort"),
        ("REDIS_PASSWORD", ""),
        ("EVAL_DB_PASSWORD", "has/slash+and@signs-in-it-1234567890"),
        ("S3_SECRET_KEY", "mindnest-secret"),
        ("S3_ACCESS_KEY", "mindnest"),
        ("DOMAIN", "localhost"),
        ("DOMAIN", "https://study.myschool.org"),
        ("DOMAIN", "192.168.1.5"),
        ("DOMAIN", "app.example.com"),
        ("ACME_EMAIL", ""),
        ("SMTP_HOST", "mailpit"),
        ("SMTP_SECURITY", "none"),
        ("SMTP_PASSWORD", ""),
        ("MAIL_FROM", "MindNest AI <no-reply@mindnest.local>"),
        ("MODEL_SERVICE_URL", "http://localhost:8100"),
        ("ENVIRONMENT", "development"),
    ],
)
def test_each_unsafe_value_is_rejected(key: str, value: str) -> None:
    env = good()
    env[key] = value
    assert key in errors(env)


def test_reused_credentials_are_rejected() -> None:
    env = good()
    env["APP_DB_PASSWORD"] = env["POSTGRES_PASSWORD"]
    assert "APP_DB_PASSWORD" in errors(env)
    env = good()
    env["SECRET_KEY"] = env["S3_SECRET_KEY"] * 3
    assert "SECRET_KEY" not in errors(env)  # different value, fine
    env["SECRET_KEY"] = env["S3_SECRET_KEY"]
    assert "SECRET_KEY" in errors(env)


def test_storage_needs_either_the_bundled_service_or_https_endpoint() -> None:
    env = good()
    env["COMPOSE_PROFILES"] = "models"
    assert "S3_ENDPOINT_URL" in errors(env)
    env["S3_ENDPOINT_URL"] = "http://s3.provider.net"
    assert "S3_ENDPOINT_URL" in errors(env)
    env["S3_ENDPOINT_URL"] = "https://s3.provider.net"
    assert errors(env) == {}


def test_google_pair_must_be_complete() -> None:
    env = good()
    env["GOOGLE_CLIENT_ID"] = "1234-abc.apps.googleusercontent.com"
    assert "GOOGLE_CLIENT_ID" in errors(env)
    env["GOOGLE_CLIENT_SECRET"] = "GOCSPX-realvalue"
    assert errors(env) == {}
    warnings = [f for f in check(env) if f.level == "warning"]
    assert any("study.myschool.org/api/v1/auth/google/callback" in w.message for w in warnings)


def test_secret_values_are_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = good()
    env["SECRET_KEY"] = "leaky-" + "q" * 10  # too short
    path = tmp_path / ".env.production"
    path.write_text("\n".join(f"{k}={v}" for k, v in env.items()))
    assert main(["prodcheck", str(path)]) == 1
    out = capsys.readouterr().out
    assert "SECRET_KEY" in out and "leaky-" not in out


def test_main_ok_and_usage(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "env"
    path.write_text("# comment\n" + "\n".join(f'{k}="{v}"' for k, v in good().items()) + "\n")
    assert main(["prodcheck", str(path)]) == 0
    assert main(["prodcheck"]) == 2
    assert main(["prodcheck", str(tmp_path / "missing")]) == 2
    assert "OK" in capsys.readouterr().out


def test_parse_env() -> None:
    parsed = parse_env("# c\n\nA=1\nB = 'two words' \nC=\"x\"\nbad line\nD=a=b\n")
    assert parsed == {"A": "1", "B": "two words", "C": "x", "D": "a=b"}


def test_the_shipped_example_file_fails_until_filled_in() -> None:
    example = Path(__file__).resolve().parents[3] / ".env.production.example"
    if not example.exists():
        pytest.skip("example file not present")
    found = errors(parse_env(example.read_text(encoding="utf-8")))
    assert "SECRET_KEY" in found and "DOMAIN" in found


def test_langsmith_tracing_needs_a_key() -> None:
    env = good()
    env["AGENT_TRACING"] = "true"
    assert "LANGSMITH_API_KEY" in errors(env)
    env["LANGSMITH_API_KEY"] = "change-me"
    assert "LANGSMITH_API_KEY" in errors(env)
    env["LANGSMITH_API_KEY"] = "lsv2_pt_realvalue1234"
    assert errors(env) == {}
    env["AGENT_TRACING"] = "maybe"
    assert "AGENT_TRACING" in errors(env)
    env["AGENT_TRACING"] = "false"
    assert errors(env) == {}
    assert any(f.key == "AGENT_TRACING" for f in check(env) if f.level == "warning")


def test_guardrail_settings_are_checked() -> None:
    env = good()
    assert "GUARDRAILS_ENABLED" not in {f.key for f in check(env)}
    env["GUARDRAILS_ENABLED"] = "maybe"
    assert "GUARDRAILS_ENABLED" in errors(env)
    env["GUARDRAILS_ENABLED"] = "false"
    assert errors(env) == {}  # allowed, but loudly noted
    assert any(f.key == "GUARDRAILS_ENABLED" and f.level == "warning" for f in check(env))
    env = good()
    env["GUARDRAILS_JUDGE"] = "yes please"
    assert "GUARDRAILS_JUDGE" in errors(env)
