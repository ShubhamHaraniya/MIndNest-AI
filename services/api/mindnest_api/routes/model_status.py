"""Settings > Local retrieval models: what the embedding and reranking models really are.

These two models run on the student's own laptop (the model service on the host), never in the
cloud, and they are not language models: they turn text into vectors and order search results.
Everything below is read from the running service. When it cannot be reached the answer says so
instead of showing configured-looking values.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from mindnest_core.settings import get_settings
from pydantic import BaseModel

from mindnest_api.deps import AuthUser, ModelsDep
from mindnest_api.retrieval import RERANK_CHARS, RETRIEVAL_MODES, RRF_K

router = APIRouter(prefix="/settings/models", tags=["settings"])
log = logging.getLogger("mindnest.models.status")


class ModelPart(BaseModel):
    name: str
    # None means the service did not say (for example before the first request loads the model).
    loaded: bool | None
    device: str | None


class ModelsStatus(BaseModel):
    reachable: bool
    # Why it is not reachable: no answer, or a service too old to report its configuration.
    problem: Literal["unreachable", "unsupported", "bad_response"] | None
    checked_at: datetime
    latency_ms: int | None
    # host:port of the service, so a student can see it is their own machine.
    service: str
    backend: str | None
    embedding: ModelPart | None
    reranker: ModelPart | None
    dim: int | None
    expected_dim: int
    dim_matches: bool | None
    cuda_available: bool | None
    gpu_name: str | None
    precision: str | None
    max_seq_length: int | None
    embed_batch_size: int | None
    rerank_batch_size: int | None
    # How retrieval uses them (constants from the code, not measurements).
    modes: list[str]
    rerank_chars: int
    rrf_k: int


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _opt_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


@router.get("", response_model=ModelsStatus)
async def models_status(_user: AuthUser, models: ModelsDep) -> ModelsStatus:
    settings = get_settings()
    base: dict[str, Any] = {
        "checked_at": datetime.now(UTC),
        "service": urlparse(settings.model_service_url).netloc or settings.model_service_url,
        "expected_dim": settings.embedding_dim,
        "modes": list(RETRIEVAL_MODES),
        "rerank_chars": RERANK_CHARS,
        "rrf_k": RRF_K,
        "backend": None,
        "embedding": None,
        "reranker": None,
        "dim": None,
        "dim_matches": None,
        "cuda_available": None,
        "gpu_name": None,
        "precision": None,
        "max_seq_length": None,
        "embed_batch_size": None,
        "rerank_batch_size": None,
        "latency_ms": None,
    }
    status = getattr(models, "status", None)
    if not callable(status):
        return ModelsStatus(reachable=False, problem="unsupported", **base)

    started = time.perf_counter()
    try:
        body = await status()
    except (httpx.HTTPError, OSError):
        log.info("model service status check failed", exc_info=True)
        return ModelsStatus(reachable=False, problem="unreachable", **base)
    except ValueError:
        return ModelsStatus(reachable=False, problem="bad_response", **base)
    base["latency_ms"] = round((time.perf_counter() - started) * 1000)

    if not isinstance(body, dict):
        return ModelsStatus(reachable=False, problem="bad_response", **{**base, "latency_ms": None})
    embed_name, rerank_name = body.get("embed_model"), body.get("rerank_model")
    if not isinstance(embed_name, str) or not isinstance(rerank_name, str):
        return ModelsStatus(reachable=False, problem="bad_response", **{**base, "latency_ms": None})
    dim = _int(body.get("dim"))
    base.update(
        backend=_opt_str(body.get("backend")),
        embedding=ModelPart(
            name=embed_name,
            loaded=_opt_bool(body.get("embedder_loaded")),
            device=_opt_str(body.get("embedder_device")),
        ),
        reranker=ModelPart(
            name=rerank_name,
            loaded=_opt_bool(body.get("reranker_loaded")),
            device=_opt_str(body.get("reranker_device")),
        ),
        dim=dim,
        dim_matches=None if dim is None else dim == settings.embedding_dim,
        cuda_available=_opt_bool(body.get("cuda_available")),
        gpu_name=_opt_str(body.get("gpu_name")),
        precision=_opt_str(body.get("precision")),
        max_seq_length=_int(body.get("max_seq_length")),
        embed_batch_size=_int(body.get("embed_batch_size")),
        rerank_batch_size=_int(body.get("rerank_batch_size")),
    )
    return ModelsStatus(reachable=True, problem=None, **base)
