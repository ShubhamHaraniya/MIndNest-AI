"""LangSmith tracing that only ever sends masked text.

Tracing is attached to one run by passing a callback handler, never switched on globally, so a
stray LANGSMITH_TRACING variable on the server cannot start sending unmasked traces. Before any
trace leaves the server, every string in it passes through the same personal-data masking as the
rest of the app (phone numbers, e-mail addresses, ID numbers) and through key redaction.
"""

import hashlib
import hmac
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from mindnest_core.aisafety import mask_pii
from mindnest_core.redact import redact
from mindnest_core.settings import Settings, tracing_enabled

logger = logging.getLogger("mindnest.agents.tracing")

# A trace is for debugging behaviour, not for archiving documents: long text is cut.
MAX_TRACE_STRING = 6000
MAX_DEPTH = 12


def lock_down_global_tracing() -> None:
    """Call once at process start. Makes sure env-var tracing stays off; only our masked tracer
    (see make_tracing) can send anything to LangSmith."""
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGSMITH_TRACING_V2"):
        os.environ[name] = "false"


def mask_text(value: str, known: Iterable[str] = (), limit: int = MAX_TRACE_STRING) -> str:
    masked = mask_pii(redact(value, known)).text
    if len(masked) > limit:
        masked = masked[:limit] + f"… [{len(masked) - limit} more characters cut]"
    return masked


def mask_payload(
    value: Any, known: Iterable[str] = (), _depth: int = 0, limit: int = MAX_TRACE_STRING
) -> Any:
    """The same structure with every string masked. Unknown objects become their type name."""
    if _depth > MAX_DEPTH:
        return "[too deep]"
    if isinstance(value, str):
        return mask_text(value, known, limit)
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, dict):
        return {
            (k if isinstance(k, str) else str(k)): mask_payload(v, known, _depth + 1, limit)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [mask_payload(v, known, _depth + 1, limit) for v in value]
    if isinstance(value, bytes | bytearray):
        return f"[{len(value)} bytes]"
    return f"[{type(value).__name__}]"


def _hide(payload: dict[str, Any]) -> dict[str, Any]:
    out = mask_payload(payload)
    return out if isinstance(out, dict) else {}


def student_tag(secret_key: str, user_id: UUID) -> str:
    """A stable pseudonym for filtering traces per student without exposing the account id."""
    digest = hmac.new(secret_key.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
    return f"student:{digest[:12]}"


_clients: dict[tuple[str, str], Any] = {}


def _client(api_key: str, endpoint: str) -> Any:
    """One shared LangSmith client per key and endpoint (each owns a background sender thread)."""
    key = (api_key, endpoint)
    if key not in _clients:
        from langsmith import Client

        _clients[key] = Client(
            api_url=endpoint,
            api_key=api_key,
            hide_inputs=_hide,
            hide_outputs=_hide,
            hide_metadata=_hide,
        )
    return _clients[key]


@dataclass
class RunTracing:
    """What to pass to a graph run: `config` gets merged into the LangGraph config."""

    enabled: bool = False
    callbacks: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def config(self) -> dict[str, Any]:
        out: dict[str, Any] = {"tags": list(self.tags), "metadata": dict(self.metadata)}
        if self.callbacks:
            out["callbacks"] = list(self.callbacks)
        return out


def make_tracing(
    settings: Settings,
    *,
    run_id: UUID,
    user_id: UUID,
    graph_version: str,
    client_factory: Callable[[str, str], Any] | None = None,
) -> RunTracing:
    """Tracing for one run. The LangSmith root run id is the agent run id (pass it as `run_id`
    in the graph config), so a row in agent_runs links straight to its trace."""
    tags = [f"graph:{graph_version}", f"env:{settings.environment}", student_tag(settings.secret_key, user_id)]
    metadata = {"agent_run_id": str(run_id), "graph_version": graph_version}
    if not tracing_enabled(settings):
        return RunTracing(False, [], tags, metadata)
    from langchain_core.tracers.langchain import LangChainTracer

    client = (client_factory or _client)(settings.langsmith_api_key, settings.langsmith_endpoint)
    tracer = LangChainTracer(client=client, project_name=settings.langsmith_project)
    return RunTracing(True, [tracer], tags, metadata)


def flush_traces() -> None:
    """Send any traces still queued. Call when the API or a worker shuts down."""
    for client in list(_clients.values()):
        try:
            client.flush()
        except Exception:  # shutting down must not fail because of tracing
            logger.warning("could not flush LangSmith traces", exc_info=True)
