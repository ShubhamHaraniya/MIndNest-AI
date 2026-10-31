"""The provider adapters, run against canned HTTP responses (no network, no database)."""

import json

import httpx
import pytest
from mindnest_api.llm import ChatMessage, HttpLLM, LLMError
from mindnest_api.vault import decrypt, encrypt

TURNS = [ChatMessage("user", "Hi"), ChatMessage("assistant", "Hello"), ChatMessage("user", "Explain")]


def sse(*payloads: str) -> bytes:
    return "".join(f"data: {p}\n\n" for p in payloads).encode()


async def collect(llm: HttpLLM, provider: str) -> str:
    return "".join([p async for p in llm.stream(provider, "secret-key", "some-model", "SYS", TURNS)])


def llm_for(handler):  # type: ignore[no-untyped-def]
    return HttpLLM(transport=httpx.MockTransport(handler))


async def test_anthropic_request_and_stream():  # type: ignore[no-untyped-def]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, json.loads(request.content)
        body = sse(
            json.dumps({"type": "message_start"}),
            json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}}),
            json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}}),
            json.dumps({"type": "message_stop"}),
        )
        return httpx.Response(200, content=body)

    assert await collect(llm_for(handler), "anthropic") == "Hello"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "secret-key"
    assert seen["body"]["system"] == "SYS" and seen["body"]["stream"] is True
    assert [m["role"] for m in seen["body"]["messages"]] == ["user", "assistant", "user"]


@pytest.mark.parametrize(
    ("provider", "host"),
    [("openai", "api.openai.com/v1"), ("groq", "api.groq.com/openai/v1")],
)
async def test_openai_style_providers(provider, host):  # type: ignore[no-untyped-def]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        chunk = lambda text: json.dumps({"choices": [{"delta": {"content": text}}]})  # noqa: E731
        return httpx.Response(
            200, content=sse(json.dumps({"choices": [{"delta": {"role": "assistant"}}]}), chunk("Hi "), chunk("there"), "[DONE]")
        )

    assert await collect(llm_for(handler), provider) == "Hi there"
    assert seen["url"] == f"https://{host}/chat/completions"
    assert seen["auth"] == "Bearer secret-key"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"}


async def test_gemini_request_and_stream():  # type: ignore[no-untyped-def]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, json.loads(request.content)
        part = lambda text: json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]})  # noqa: E731
        return httpx.Response(200, content=sse(part("Na"), part("maste")))

    assert await collect(llm_for(handler), "gemini") == "Namaste"
    assert "some-model:streamGenerateContent?alt=sse" in seen["url"]
    assert "secret-key" not in seen["url"] and seen["headers"]["x-goog-api-key"] == "secret-key"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]


async def test_gemini_blocked_prompt():  # type: ignore[no-untyped-def]
    body = sse(json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(LLMError) as caught:
        await collect(llm_for(lambda request: httpx.Response(200, content=body)), "gemini")
    assert caught.value.code == "blocked"


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "invalid_key"), (403, "invalid_key"), (429, "rate_limited"), (404, "bad_request"),
     (400, "bad_request"), (503, "provider_unavailable")],
)
async def test_http_errors_become_stable_codes(status, code):  # type: ignore[no-untyped-def]
    llm = llm_for(lambda request: httpx.Response(status, json={"error": {"message": "nope"}}))
    with pytest.raises(LLMError) as caught:
        await collect(llm, "openai")
    assert caught.value.code == code


async def test_network_failures_become_codes():  # type: ignore[no-untyped-def]
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(LLMError) as caught:
        await collect(llm_for(timeout), "groq")
    assert caught.value.code == "timeout"
    with pytest.raises(LLMError) as caught:
        await collect(llm_for(down), "groq")
    assert caught.value.code == "provider_unavailable"


async def test_unknown_provider():  # type: ignore[no-untyped-def]
    with pytest.raises(LLMError):
        await collect(llm_for(lambda request: httpx.Response(200)), "mystery")


def test_vault_round_trip_and_wrong_secret():  # type: ignore[no-untyped-def]
    token = encrypt("secret-one", "sk-abc")
    assert "sk-abc" not in token
    assert decrypt("secret-one", token) == "sk-abc"
    assert encrypt("secret-one", "sk-abc") != token  # fresh IV every time
    from mindnest_api.errors import AppError

    with pytest.raises(AppError) as caught:
        decrypt("secret-two", token)
    assert caught.value.code == "key_unreadable"


async def test_model_lists_keep_only_chat_models():  # type: ignore[no-untyped-def]
    payloads = {
        "api.groq.com": {"data": [{"id": "openai/gpt-oss-20b"}, {"id": "whisper-large-v3"},
                                  {"id": "llama-guard-4-12b"}, {"id": "llama-3.3-70b-versatile"}]},
        "api.openai.com": {"data": [{"id": "gpt-6-luna"}, {"id": "text-embedding-3-small"},
                                    {"id": "dall-e-3"}, {"id": "o4-mini"}, {"id": "davinci-002"}]},
        "api.anthropic.com": {"data": [{"id": "claude-sonnet-5-5"}, {"id": "claude-haiku-5-5"}]},
        "generativelanguage.googleapis.com": {"models": [
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}]},
    }
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = dict(request.headers)
        return httpx.Response(200, json=payloads[request.url.host])

    llm = llm_for(handler)
    assert await llm.list_models("groq", "k") == ["llama-3.3-70b-versatile", "openai/gpt-oss-20b"]
    assert await llm.list_models("openai", "k") == ["gpt-6-luna", "o4-mini"]
    assert await llm.list_models("anthropic", "k") == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert await llm.list_models("gemini", "k") == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert seen["generativelanguage.googleapis.com"]["x-goog-api-key"] == "k"


async def test_model_list_errors_become_codes():  # type: ignore[no-untyped-def]
    llm = llm_for(lambda request: httpx.Response(401, json={}))
    with pytest.raises(LLMError) as caught:
        await llm.list_models("openai", "k")
    assert caught.value.code == "invalid_key"
