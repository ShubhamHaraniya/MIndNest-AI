"""Checks a production settings file before the stack is started.

    python -m mindnest_core.prodcheck .env.production

It reads the file as plain KEY=VALUE lines (it never connects to anything), prints every problem
it finds and exits with status 1 if there is at least one. Warnings do not fail the check.
Secret values are never printed.
"""

import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEV_SECRET = "dev-only-secret-change-me"
# Values copied from the example files or the development stack.
KNOWN_WEAK = {
    "mindnest", "mindnest_app", "mindnest_eval", "mindnest-secret", "password", "changeme",
    "change-me", "secret", "admin", "postgres", DEV_SECRET,
}
PASSWORD_KEYS = ("POSTGRES_PASSWORD", "APP_DB_PASSWORD", "EVAL_DB_PASSWORD", "REDIS_PASSWORD")
MIN_PASSWORD = 20
MIN_SECRET_KEY = 40
URL_SAFE = re.compile(r"^[A-Za-z0-9._~-]+$")
DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
PLACEHOLDER = re.compile(r"(change[-_ ]?me|example\.com|your[-_ ]|<[^>@]*>|xxx+)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    level: str  # "error" or "warning"
    key: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.key}: {self.message}"


def parse_env(text: str) -> dict[str, str]:
    """KEY=VALUE lines. Blank lines and # comments are skipped; matching quotes are removed."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def check(env: Mapping[str, str]) -> list[Finding]:
    findings: list[Finding] = []

    def error(key: str, message: str) -> None:
        findings.append(Finding("error", key, message))

    def warn(key: str, message: str) -> None:
        findings.append(Finding("warning", key, message))

    def get(key: str) -> str:
        return env.get(key, "").strip()

    # --- domain and mail -------------------------------------------------------------------
    domain = get("DOMAIN")
    if not domain:
        error("DOMAIN", "is empty. Set the public address students will type, e.g. study.example.org.")
    elif not DOMAIN.match(domain.lower()) or domain.lower().endswith((".local", ".localhost", ".test")):
        error("DOMAIN", "must be a real domain name without http:// or a path (no localhost or IP address).")
    elif domain.lower().endswith("example.com"):
        error("DOMAIN", "still has the example value.")
    acme = get("ACME_EMAIL")
    if not acme or "@" not in acme or PLACEHOLDER.search(acme):
        error("ACME_EMAIL", "needs a real address; the certificate authority uses it for expiry notices.")

    # --- secrets -------------------------------------------------------------------------
    secret = get("SECRET_KEY")
    if not secret:
        error("SECRET_KEY", "is empty.")
    elif secret == DEV_SECRET or secret in KNOWN_WEAK or PLACEHOLDER.search(secret):
        error("SECRET_KEY", "is a development or placeholder value.")
    elif len(secret) < MIN_SECRET_KEY:
        error("SECRET_KEY", f"is too short ({len(secret)} characters); use at least {MIN_SECRET_KEY}.")

    seen: dict[str, str] = {}
    for key in (*PASSWORD_KEYS, "S3_SECRET_KEY"):
        value = get(key)
        if not value:
            error(key, "is empty.")
            continue
        if value in KNOWN_WEAK or PLACEHOLDER.search(value):
            error(key, "is a development or placeholder value.")
        elif len(value) < MIN_PASSWORD:
            error(key, f"is too short ({len(value)} characters); use at least {MIN_PASSWORD}.")
        if not URL_SAFE.match(value):
            error(key, "may only contain letters, digits and . _ ~ - (it is placed inside a connection URL). "
                       "Generate one with: openssl rand -hex 24")
        if value in seen:
            error(key, f"is the same as {seen[value]}; every credential must be different.")
        seen.setdefault(value, key)
    if secret and secret in seen:
        error("SECRET_KEY", f"is the same as {seen[secret]}; every credential must be different.")

    access = get("S3_ACCESS_KEY")
    if not access:
        error("S3_ACCESS_KEY", "is empty.")
    elif access in KNOWN_WEAK or PLACEHOLDER.search(access):
        error("S3_ACCESS_KEY", "is a development or placeholder value.")
    elif len(access) < 8:
        error("S3_ACCESS_KEY", "is too short; use at least 8 characters.")
    if not get("S3_BUCKET"):
        error("S3_BUCKET", "is empty.")

    # --- storage ---------------------------------------------------------------------------
    endpoint = get("S3_ENDPOINT_URL")
    if endpoint:
        if not endpoint.startswith("https://"):
            error("S3_ENDPOINT_URL", "must start with https:// when you use an outside storage service.")
    elif "storage" not in {p.strip() for p in get("COMPOSE_PROFILES").split(",")}:
        error("S3_ENDPOINT_URL", "is empty and COMPOSE_PROFILES does not include 'storage', "
                                 "so no file storage would be running.")

    # --- mail ------------------------------------------------------------------------------
    host = get("SMTP_HOST")
    if not host:
        error("SMTP_HOST", "is empty. Without mail nobody can verify an address or reset a password.")
    elif host in {"localhost", "127.0.0.1", "mailpit"} or PLACEHOLDER.search(host):
        error("SMTP_HOST", "points at a development mail catcher; use your mail provider's server.")
    if get("SMTP_SECURITY") not in {"starttls", "tls"}:
        error("SMTP_SECURITY", "must be 'starttls' (port 587) or 'tls' (port 465) so mail logins are encrypted.")
    for key in ("SMTP_USER", "SMTP_PASSWORD"):
        if not get(key):
            error(key, "is needed for your mail provider.")
    sender = get("MAIL_FROM")
    if not sender or "mindnest.local" in sender or "example.com" in sender or "@" not in sender:
        error("MAIL_FROM", "needs a real sender address on a domain you control.")

    # --- google ----------------------------------------------------------------------------
    gid, gsecret = get("GOOGLE_CLIENT_ID"), get("GOOGLE_CLIENT_SECRET")
    if bool(gid) != bool(gsecret):
        error("GOOGLE_CLIENT_ID", "and GOOGLE_CLIENT_SECRET must both be set, or both left empty.")
    elif gid:
        if PLACEHOLDER.search(gid) or PLACEHOLDER.search(gsecret):
            error("GOOGLE_CLIENT_ID", "or its secret still has a placeholder value.")
        if domain:
            warn("GOOGLE_CLIENT_ID", f"register https://{domain}/api/v1/auth/google/callback and "
                                     f"https://{domain}/api/v1/integrations/google-calendar/callback "
                                     "as redirect URIs in Google Cloud Console, and switch on the Google Calendar API for the project.")

    # --- agent traces ----------------------------------------------------------------------
    tracing_on = get("AGENT_TRACING").lower() in ("1", "true", "yes", "on")
    ls_key = get("LANGSMITH_API_KEY")
    if tracing_on and not ls_key:
        error("LANGSMITH_API_KEY", "is needed when AGENT_TRACING is on.")
    elif tracing_on and PLACEHOLDER.search(ls_key):
        error("LANGSMITH_API_KEY", "still has a placeholder value.")
    elif ls_key and not tracing_on:
        warn("AGENT_TRACING", "is off, so the LangSmith key is not used.")
    if get("AGENT_TRACING") and get("AGENT_TRACING").lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
        error("AGENT_TRACING", "must be true or false.")

    # --- guardrails ------------------------------------------------------------------------
    for name in ("GUARDRAILS_ENABLED", "GUARDRAILS_JUDGE"):
        if get(name) and get(name).lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
            error(name, "must be true or false.")
    if get("GUARDRAILS_ENABLED").lower() in ("0", "false", "no", "off"):
        warn("GUARDRAILS_ENABLED", "is off: messages, tool calls and answers are not checked by the safety rails.")

    # --- other ---------------------------------------------------------------------------
    model_url = get("MODEL_SERVICE_URL")
    if model_url and "localhost" in model_url:
        error("MODEL_SERVICE_URL", "points at localhost, which inside a container is the container itself.")
    if not get("BACKUP_DIR"):
        warn("BACKUP_DIR", "is empty; backups will go to ./backups next to the stack. "
                           "Copy them to another machine as well.")
    if "ENVIRONMENT" in env and get("ENVIRONMENT") != "production":
        error("ENVIRONMENT", "must be 'production' (or left out; compose sets it).")
    return findings


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m mindnest_core.prodcheck <env-file>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"{path}: file not found", file=sys.stderr)
        return 2
    findings = check(parse_env(path.read_text(encoding="utf-8")))
    for finding in findings:
        print(finding)
    errors = sum(1 for f in findings if f.level == "error")
    if errors:
        print(f"\n{errors} problem(s) to fix before going live.")
        return 1
    print("\nOK: no blocking problems found." + (" Read the warnings above." if findings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
