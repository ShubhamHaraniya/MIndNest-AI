"""One factory for the chat model every agent uses, whichever provider the student chose.

The key is handed in explicitly for this run. Nothing here reads provider keys from environment
variables, so a key set on the server can never be used on a student's behalf by accident.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from .errors import AgentError

SUPPORTED_PROVIDERS = ("anthropic", "gemini", "openai", "groq")


def build_chat_model(
    provider: str,
    model: str,
    api_key: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    max_retries: int = 1,
) -> BaseChatModel:
    """A LangChain chat model for the student's provider. Raises AgentError for a bad choice."""
    if provider not in SUPPORTED_PROVIDERS:
        raise AgentError("unknown_provider")
    if not model.strip():
        raise AgentError("bad_request")
    if not api_key.strip():
        raise AgentError("no_key")

    # Imported here so that starting the API does not load four vendor SDKs.
    llm: Any
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=model,  # type: ignore[call-arg]
            api_key=api_key,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,  # type: ignore[call-arg]
            timeout=timeout,
            max_retries=max_retries,
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=model,
            api_key=api_key,  # type: ignore[arg-type]
            temperature=temperature,
            max_completion_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=model,
            api_key=api_key,  # type: ignore[arg-type]
            temperature=temperature,
            max_output_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
    else:
        from langchain_groq import ChatGroq

        llm = ChatGroq(
            model=model,
            api_key=api_key,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
    return llm  # type: ignore[no-any-return]
