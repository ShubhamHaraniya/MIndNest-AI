"""HTTP interface to the embedding and rerank models.

Run on the host (not in Docker) so it can use the laptop GPU:
    uvicorn mindnest_models.main:app --port 8100
"""

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from mindnest_models.backends import Backend, backend_from_env


logger = logging.getLogger("mindnest.models")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)


class EmbedResponse(BaseModel):
    model: str
    dim: int
    embeddings: list[list[float]]


class RerankRequest(BaseModel):
    query: str = Field(min_length=1)
    passages: list[str] = Field(min_length=1, max_length=100)


class RerankResponse(BaseModel):
    model: str
    scores: list[float]


def create_app(backend: Backend | None = None) -> FastAPI:
    active = backend or backend_from_env()
    # One request at a time on the GPU: concurrent batches would exhaust 4 GB of memory.
    gpu_lock = threading.Lock()

    def warm_up() -> None:
        warm = getattr(active, "warm", None)
        if warm is None:
            return
        with gpu_lock:
            try:
                warm()
            except Exception:
                logger.exception("Warming up the models failed; they will load on first use")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        own = logging.getLogger("mindnest.models")
        if not own.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
            own.addHandler(handler)
            own.setLevel(logging.INFO)
            own.propagate = False
        # In the background, so the service answers /health at once while models load.
        threading.Thread(target=warm_up, name="model-warmup", daemon=True).start()
        yield

    app = FastAPI(title="MindNest model service", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "embed_model": active.embed_model, "rerank_model": active.rerank_model}

    @app.get("/status")
    def status() -> dict[str, Any]:
        """The real configuration and load state, read without touching the GPU lock."""
        describe = getattr(active, "describe", None)
        details: dict[str, Any] = describe() if callable(describe) else {}
        return {
            "status": "ok",
            "embed_model": active.embed_model,
            "rerank_model": active.rerank_model,
            "dim": active.dim,
            **details,
        }

    @app.post("/embed", response_model=EmbedResponse)
    def embed(request: EmbedRequest) -> EmbedResponse:
        with gpu_lock:
            vectors = active.embed(request.texts)
        return EmbedResponse(model=active.embed_model, dim=active.dim, embeddings=vectors)

    @app.post("/rerank", response_model=RerankResponse)
    def rerank(request: RerankRequest) -> RerankResponse:
        with gpu_lock:
            scores = active.rerank(request.query, request.passages)
        return RerankResponse(model=active.rerank_model, scores=scores)

    return app


app = create_app()
