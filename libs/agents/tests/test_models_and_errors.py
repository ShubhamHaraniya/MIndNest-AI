"""The chat-model factory and error mapping. No network: keys are fake and nothing is called."""

import pytest
from mindnest_agents.errors import AgentError, error_code
from mindnest_agents.models import SUPPORTED_PROVIDERS, build_chat_model

FAKE_KEY = "fake-key-for-tests-123456"


@pytest.mark.parametrize(
    ("provider", "model", "class_name"),
    [
        ("anthropic", "claude-sonnet-5-5", "ChatAnthropic"),
        ("openai", "gpt-6-luna", "ChatOpenAI"),
        ("gemini", "gemini-3.8-flash", "ChatGoogleGenerativeAI"),
        ("groq", "openai/gpt-oss-20b", "ChatGroq"),
    ],
)
def test_each_provider_builds_its_own_chat_model(provider: str, model: str, class_name: str) -> None:
    llm = build_chat_model(provider, model, FAKE_KEY)
    assert type(llm).__name__ == class_name
    assert (getattr(llm, "model", None) or getattr(llm, "model_name", None)) == model


def test_factory_supports_exactly_the_providers_in_settings() -> None:
    from mindnest_api.llm import PROVIDERS

    assert set(SUPPORTED_PROVIDERS) == set(PROVIDERS)
    for info in PROVIDERS.values():
        build_chat_model(info.id, info.default_model, FAKE_KEY)


@pytest.mark.parametrize(
    ("provider", "model", "key", "code"),
    [
        ("mistral", "m", FAKE_KEY, "unknown_provider"),
        ("openai", "  ", FAKE_KEY, "bad_request"),
        ("openai", "gpt-6-luna", "  ", "no_key"),
    ],
)
def test_bad_choices_are_refused_with_a_stable_code(provider: str, model: str, key: str, code: str) -> None:
    with pytest.raises(AgentError) as caught:
        build_chat_model(provider, model, key)
    assert caught.value.code == code


def test_the_key_is_not_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-environment-000000000000")
    with pytest.raises(AgentError):
        build_chat_model("openai", "gpt-6-luna", "")


class _WithStatus(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("provider said something with sk-ant-secret-secret-secret in it")
        self.status_code = status_code


class _WithResponse(Exception):
    def __init__(self, status: int) -> None:
        super().__init__("x")

        class R:
            status_code = status

        self.response = R()


class RateLimitError(Exception): ...


class APITimeoutError(Exception): ...


class AuthenticationError(Exception): ...


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (_WithStatus(401), "invalid_key"),
        (_WithStatus(403), "invalid_key"),
        (_WithStatus(429), "rate_limited"),
        (_WithStatus(400), "bad_request"),
        (_WithStatus(503), "provider_unavailable"),
        (_WithResponse(429), "rate_limited"),
        (RateLimitError("x"), "rate_limited"),
        (APITimeoutError("x"), "provider_unavailable"),
        (AuthenticationError("x"), "invalid_key"),
        (AgentError("no_key"), "no_key"),
        (ValueError("boom"), "provider_error"),
    ],
)
def test_provider_failures_become_stable_codes(exc: Exception, code: str) -> None:
    assert error_code(exc) == code
