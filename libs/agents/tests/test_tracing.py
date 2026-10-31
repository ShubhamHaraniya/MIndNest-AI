"""LangSmith tracing sends masked text only, and is never switched on by the environment."""

import os
import uuid
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langsmith import Client
from mindnest_agents import tracing
from mindnest_agents.tracing import (
    lock_down_global_tracing,
    make_tracing,
    mask_payload,
    mask_text,
    student_tag,
)
from mindnest_core.settings import Settings, tracing_enabled

USER = uuid.UUID("11111111-1111-1111-1111-111111111111")


def settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {"secret_key": "k" * 40, "environment": "test"}
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_text_is_masked_and_keys_removed() -> None:
    out = mask_text("mail priya.s@gmail.com or call +91 98765 43210, key sk-ant-api03-abcdefghijklmnop")
    assert "priya.s@gmail.com" not in out and "98765" not in out and "abcdefghij" not in out
    assert "[EMAIL]" in out and "[PHONE]" in out


def test_exact_known_secret_is_removed_even_if_it_has_no_known_shape() -> None:
    assert "plainsecret99" not in mask_text("the key is plainsecret99", ["plainsecret99"])


def test_payload_is_masked_deeply_and_odd_objects_are_not_serialised() -> None:
    class Secretive:
        def __repr__(self) -> str:
            return "api key sk-ant-api03-abcdefghijklmnop"

    out = mask_payload({"a": ["x@gmail.com", {"b": ("+91 98765 43210", 3, None, True)}], "c": Secretive(), 5: b"abc"})
    flat = str(out)
    assert "x@gmail.com" not in flat and "98765" not in flat and "sk-ant" not in flat
    assert out["c"] == "[Secretive]" and out["5"] == "[3 bytes]"


def test_long_text_is_cut() -> None:
    out = mask_text("a" * 20000)
    assert len(out) < 6100 and "more characters cut" in out


def test_student_tag_is_stable_and_hides_the_id() -> None:
    tag = student_tag("s" * 40, USER)
    assert tag == student_tag("s" * 40, USER)
    assert tag != student_tag("t" * 40, USER)
    assert str(USER)[:8] not in tag and tag.startswith("student:")


def test_global_tracing_variables_are_forced_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    lock_down_global_tracing()
    assert os.environ["LANGSMITH_TRACING"] == "false" and os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_tracing_needs_both_the_switch_and_a_key() -> None:
    assert not tracing_enabled(settings())
    assert not tracing_enabled(settings(agent_tracing=True))
    assert not tracing_enabled(settings(langsmith_api_key="ls-key"))
    assert tracing_enabled(settings(agent_tracing=True, langsmith_api_key="ls-key"))


def test_disabled_tracing_adds_no_callbacks_but_still_labels_the_run() -> None:
    run_id = uuid.uuid4()
    t = make_tracing(settings(), run_id=run_id, user_id=USER, graph_version="agents-1")
    assert not t.enabled and t.callbacks == []
    cfg = t.config()
    assert "callbacks" not in cfg and cfg["metadata"]["agent_run_id"] == str(run_id)
    assert any(tag.startswith("student:") for tag in cfg["tags"])
    assert str(USER) not in str(cfg)


def test_a_real_trace_leaves_the_server_masked() -> None:
    sent: list[str] = []

    def fake_request(self: Any, method: str, path: str, *args: Any, **kw: Any) -> Any:
        sent.append(kw["request_kwargs"]["data"].decode())
        return SimpleNamespace(status_code=200, json=lambda: {})

    def factory(api_key: str, endpoint: str) -> Client:
        return Client(
            api_url=endpoint, api_key=api_key, auto_batch_tracing=False,
            hide_inputs=tracing._hide, hide_outputs=tracing._hide, hide_metadata=tracing._hide,
        )

    run_id = uuid.uuid4()
    cfg = settings(agent_tracing=True, langsmith_api_key="ls-test", langsmith_endpoint="http://ls.invalid")
    with mock.patch.object(Client, "request_with_retries", fake_request):
        t = make_tracing(cfg, run_id=run_id, user_id=USER, graph_version="agents-1", client_factory=factory)
        assert t.enabled and len(t.callbacks) == 1
        model = GenericFakeChatModel(messages=iter([AIMessage(content="Call +91 98765 43210, key sk-ant-api03-abcdefghijklmnop")]))
        model.invoke(
            "my mail is raj.s@gmail.com",
            config={**t.config(), "run_id": run_id, "metadata": {**t.metadata, "note": "x@gmail.com"}},
        )
        t.callbacks[0].client.flush()
    blob = "\n".join(sent)
    assert sent, "nothing was traced"
    for secret in ("raj.s@gmail.com", "x@gmail.com", "98765", "sk-ant-api03", str(USER)):
        assert secret not in blob, secret
    assert "[EMAIL]" in blob and "[PHONE]" in blob
    assert str(run_id) in blob  # the trace carries the agent run id
