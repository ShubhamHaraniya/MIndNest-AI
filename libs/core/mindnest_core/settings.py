"""Application settings, read from environment variables and an optional .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MindNest AI"
    environment: str = "development"

    # Runtime connection: the app role, which is subject to row-level security.
    database_url: str = "postgresql+asyncpg://mindnest_app:mindnest_app@localhost:5432/mindnest"
    # Owner connection: used only by migrations and test fixtures.
    migration_database_url: str = "postgresql+asyncpg://mindnest:mindnest@localhost:5432/mindnest"

    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "mindnest"
    s3_secret_key: str = "mindnest-secret"
    s3_bucket: str = "mindnest-materials"

    model_service_url: str = "http://localhost:8100"
    # Must match the vector(1024) column in migration 0001 (BGE-M3 dense vectors).
    embedding_dim: int = 1024

    cors_origins: list[str] = ["http://localhost:3000"]

    # Where links in emails point. The web app proxies /api to the API, so one origin serves both.
    web_base_url: str = "http://localhost:3000"

    # Outgoing mail. Development uses Mailpit (web UI at http://localhost:8025), which accepts
    # any mail over plain SMTP and never delivers it.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "MindNest AI <no-reply@mindnest.local>"
    # A real mail provider needs a login and an encrypted connection. "starttls" suits port 587,
    # "tls" suits port 465, "none" is for Mailpit in development.
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_security: str = "none"

    # Uploads and ingestion (M2).
    max_upload_mb: int = 50
    max_ocr_pages: int = 100
    ocr_languages: str = "eng+hin+guj"
    # BGE-M3 reads at most 512 tokens; Hindi and Gujarati use more tokens per character than
    # English, so chunks stay well under that limit in characters.
    chunk_max_chars: int = 800
    chunk_overlap_chars: int = 120
    embed_batch_size: int = 16

    # Chat (M3).
    retrieval_candidates: int = 30
    retrieval_top_k: int = 6
    chat_history_messages: int = 12
    chat_rate_per_minute: int = 20
    llm_timeout_seconds: float = 120.0
    # Encrypts the API keys users paste into Settings (Fernet, key derived from this value).
    # The default is for local development only; the API refuses to start outside development
    # until it is changed. Changing it later makes every stored key unreadable.
    secret_key: str = "dev-only-secret-change-me"

    # Agents (LangGraph). One run is one student message; these keep a run from looping or hanging.
    agent_max_steps: int = 60  # LangGraph recursion limit: graph steps in one run
    agent_max_output_tokens: int = 4096
    agent_run_timeout_seconds: float = 180.0
    agent_max_tool_calls: int = 8
    # LangSmith traces. Off unless agent_tracing is true AND a key is set. Traces hold MASKED text
    # only (personal data and key-shaped strings are removed before anything leaves the server).
    # Leave the standard LANGSMITH_TRACING variable unset: the app never relies on it.
    agent_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "mindnest-ai"

    # NeMo Guardrails around every chat run: rules on the message, on each tool call and result,
    # and on the answer. The student's own model is asked only about messages the rules cannot
    # settle (a possible jailbreak, a possible self-harm message), with this timeout.
    guardrails_enabled: bool = True
    guardrails_judge: bool = True
    guardrails_judge_timeout_seconds: float = 8.0

    # Sign in with Google. Leave the client id empty to switch the button off. Create the OAuth
    # client in Google Cloud Console (see docs/runbooks/google-oauth.md); its redirect URI must be
    # exactly google_redirect_uri.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""  # empty = {web_base_url}/api/v1/auth/google/callback
    # Google Calendar sync uses the same OAuth client with a second redirect URI.
    google_calendar_redirect_uri: str = ""  # empty = {web_base_url}/api/v1/integrations/google-calendar/callback
    # The calendar MCP server: the only service that talks to Google Calendar. The API sends it
    # one short-lived token per call (see mindnest_core.mcptoken).
    calendar_mcp_url: str = "http://calendar-mcp:8765/mcp"
    calendar_mcp_token_ttl_seconds: float = 60.0
    calendar_mcp_timeout_seconds: float = 45.0

    session_cookie_name: str = "mindnest_session"
    session_ttl_days: int = 14
    verify_token_ttl_hours: int = 48
    reset_token_ttl_minutes: int = 60


def tracing_enabled(settings: Settings) -> bool:
    return bool(settings.agent_tracing and settings.langsmith_api_key)


def google_enabled(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def google_redirect(settings: Settings) -> str:
    return settings.google_redirect_uri or f"{settings.web_base_url.rstrip('/')}/api/v1/auth/google/callback"


def google_calendar_redirect(settings: Settings) -> str:
    return settings.google_calendar_redirect_uri or (
        f"{settings.web_base_url.rstrip('/')}/api/v1/integrations/google-calendar/callback"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
