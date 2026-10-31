"""Talking to the AI providers. Every provider is called over plain HTTPS with httpx and the
reply is streamed back as text pieces, so no vendor SDK is needed.

The user's own API key is passed in for each call and is never logged or stored here.
"""

import json
import logging
import re
from urllib.parse import quote
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

logger = logging.getLogger("mindnest.llm")

ProviderId = Literal["anthropic", "gemini", "openai", "groq"]


@dataclass(frozen=True)
class ProviderInfo:
    id: ProviderId
    label: str
    # Suggestions only; any model name the provider accepts can be typed in Settings.
    # Checked against each provider's own model list on 2026-10-28; these change often.
    models: tuple[str, ...]
    default_model: str
    key_url: str


PROVIDERS: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo(
        "anthropic",
        "Anthropic Claude",
        ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"),
        "claude-sonnet-5-5",
        "https://console.anthropic.com/settings/keys",
    ),
    "gemini": ProviderInfo(
        "gemini",
        "Google Gemini",
        ("gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"),
        "gemini-3.8-flash",
        "https://aistudio.google.com/apikey",
    ),
    "openai": ProviderInfo(
        "openai",
        "OpenAI",
        ("gpt-6-luna", "gpt-6.1-terra", "gpt-5.4-mini"),
        "gpt-6-luna",
        "https://platform.openai.com/api-keys",
    ),
    "groq": ProviderInfo(
        "groq",
        "Groq",
        ("openai/gpt-oss-20b", "openai/gpt-oss-120b"),
        "openai/gpt-oss-20b",
        "https://console.groq.com/keys",
    ),
}

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


class LLMError(Exception):
    """A provider call failed. `code` is stable and safe to show to the user."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class LLM(Protocol):
    async def list_models(self, provider: str, api_key: str) -> list[str]: ...

    def stream(
        self,
        provider: str,
        api_key: str,
        model: str,
        system: str,
        messages: list[ChatMessage],
    ) -> AsyncGenerator[str, None]: ...


_NOT_CHAT = ("embed", "whisper", "tts", "dall", "image", "moderation", "audio", "realtime",
             "transcribe", "orpheus", "guard", "rerank", "aqa", "imagen", "veo")
_OPENAI_CHAT = re.compile(r"^(gpt|o\d|chatgpt)")


def _chat_model_ids(provider: str, payload: Any) -> list[str]:
    """Pick the text-chat models out of a provider's model list."""
    ids: list[str] = []
    if provider == "gemini":
        for model in payload.get("models", []):
            name = str(model.get("name", "")).removeprefix("models/")
            if "generateContent" in model.get("supportedGenerationMethods", []):
                ids.append(name)
    else:
        for model in payload.get("data", []):
            ids.append(str(model.get("id", "")))
    keep = [i for i in ids if i and not any(word in i.lower() for word in _NOT_CHAT)]
    if provider == "openai":
        keep = [i for i in keep if _OPENAI_CHAT.match(i)]
    return sorted(set(keep))


def _status_to_code(status: int) -> str:
    if status in (401, 403):
        return "invalid_key"
    if status == 429:
        return "rate_limited"
    if status in (400, 404, 422):
        return "bad_request"
    if status >= 500:
        return "provider_unavailable"
    return "provider_error"


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """The `data:` payloads of a server-sent-events response."""
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            yield line[5:].strip()


def _anthropic_request(
    api_key: str, model: str, system: str, messages: list[ChatMessage]
) -> tuple[str, dict[str, str], dict[str, Any]]:
    return (
        "https://api.anthropic.com/v1/messages",
        {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        {
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "stream": True,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        },
    )


def _openai_style_request(
    base_url: str, api_key: str, model: str, system: str, messages: list[ChatMessage]
) -> tuple[str, dict[str, str], dict[str, Any]]:
    return (
        f"{base_url}/chat/completions",
        {"authorization": f"Bearer {api_key}"},
        {
            "model": model,
            "stream": True,
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        },
    )


def _gemini_request(
    api_key: str, model: str, system: str, messages: list[ChatMessage]
) -> tuple[str, dict[str, str], dict[str, Any]]:
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model.removeprefix('models/'), safe='')}:streamGenerateContent?alt=sse",
        # The key goes in a header, not the URL, so it cannot end up in access logs.
        {"x-goog-api-key": api_key},
        {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "user" if m.role == "user" else "model", "parts": [{"text": m.content}]}
                for m in messages
            ],
        },
    )


def _pieces(provider: str, payload: str) -> list[str]:
    """Text carried by one streamed JSON payload. Raises LLMError for error payloads."""
    if payload == "[DONE]" or not payload:
        return []
    try:
        data = json.loads(payload)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []

    if provider == "anthropic":
        kind = data.get("type")
        if kind == "error":
            error_type = (data.get("error") or {}).get("type", "")
            raise LLMError("rate_limited" if "rate_limit" in error_type else "provider_error")
        if kind == "content_block_delta":
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta":
                return [str(delta.get("text", ""))]
        return []

    if provider == "gemini":
        if (data.get("promptFeedback") or {}).get("blockReason"):
            raise LLMError("blocked")
        out: list[str] = []
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if isinstance(part.get("text"), str):
                    out.append(part["text"])
        return out

    # OpenAI and Groq share one format.
    if data.get("error"):
        raise LLMError("provider_error")
    out = []
    for choice in data.get("choices") or []:
        content = (choice.get("delta") or {}).get("content")
        if isinstance(content, str) and content:
            out.append(content)
    return out


class HttpLLM:
    def __init__(self, timeout: float = 120.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0), transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self, provider: str, api_key: str) -> list[str]:
        """The chat models this particular key can use, straight from the provider, so the
        suggestions never go stale and never offer a model the account cannot access."""
        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/models?limit=100"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        elif provider == "gemini":
            url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
            headers = {"x-goog-api-key": api_key}
        elif provider == "openai":
            url = "https://api.openai.com/v1/models"
            headers = {"authorization": f"Bearer {api_key}"}
        elif provider == "groq":
            url = "https://api.groq.com/openai/v1/models"
            headers = {"authorization": f"Bearer {api_key}"}
        else:
            raise LLMError("unknown_provider")
        try:
            response = await self._client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError("timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMError("provider_unavailable") from exc
        if response.status_code >= 400:
            logger.warning("%s model list returned HTTP %s", provider, response.status_code)
            raise LLMError(_status_to_code(response.status_code))
        try:
            return _chat_model_ids(provider, response.json())
        except (ValueError, AttributeError, TypeError) as exc:
            raise LLMError("provider_error") from exc

    async def stream(
        self,
        provider: str,
        api_key: str,
        model: str,
        system: str,
        messages: list[ChatMessage],
    ) -> AsyncGenerator[str, None]:
        if provider == "anthropic":
            url, headers, body = _anthropic_request(api_key, model, system, messages)
        elif provider == "gemini":
            url, headers, body = _gemini_request(api_key, model, system, messages)
        elif provider == "openai":
            url, headers, body = _openai_style_request(
                "https://api.openai.com/v1", api_key, model, system, messages
            )
        elif provider == "groq":
            url, headers, body = _openai_style_request(
                "https://api.groq.com/openai/v1", api_key, model, system, messages
            )
        else:
            raise LLMError("unknown_provider")

        try:
            async with self._client.stream("POST", url, headers=headers, json=body) as response:
                if response.status_code >= 400:
                    detail = (await response.aread())[:300].decode("utf-8", "replace")
                    # The provider's message (never the key) helps debugging a wrong model name.
                    logger.warning("%s returned HTTP %s: %s", provider, response.status_code, detail)
                    raise LLMError(_status_to_code(response.status_code))
                async for payload in _sse_data(response):
                    for piece in _pieces(provider, payload):
                        if piece:
                            yield piece
        except httpx.TimeoutException as exc:
            raise LLMError("timeout") from exc
        except httpx.HTTPError as exc:
            raise LLMError("provider_unavailable") from exc
