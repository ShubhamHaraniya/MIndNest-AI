"""Model backends for the local embedding and rerank service.

SentenceTransformerBackend runs BGE-M3 (embeddings) and bge-reranker-v2-m3 (reranking)
and is tuned for a 4 GB GPU: half precision, small batches, capped sequence length, and a
CPU fallback for the reranker if GPU memory runs out. FakeBackend is deterministic and
needs no downloads; it exists for tests and for developing the rest of the stack without
the models.
"""

import hashlib
import logging
import math
import os
import re
import time
from typing import Any, Protocol


class Backend(Protocol):
    embed_model: str
    rerank_model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def rerank(self, query: str, passages: list[str]) -> list[float]: ...


logger = logging.getLogger("mindnest.models")

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(value.lower()))


class FakeBackend:
    embed_model = "fake-hash-embedder"
    rerank_model = "fake-overlap-reranker"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        query_tokens = _tokens(query)
        scores = []
        for passage in passages:
            passage_tokens = _tokens(passage)
            union = query_tokens | passage_tokens
            scores.append(len(query_tokens & passage_tokens) / len(union) if union else 0.0)
        return scores

    def describe(self) -> dict[str, Any]:
        """What this backend is, for the Settings screen. Nothing here is estimated."""
        return {
            "backend": "fake",
            "dim": self.dim,
            "device": "none",
            "precision": "none",
            "embedder_loaded": True,
            "reranker_loaded": True,
        }

    def _vector(self, text: str) -> list[float]:
        values = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            values[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in values))
        return [v / norm for v in values] if norm else values


class SentenceTransformerBackend:
    dim = 1024  # BGE-M3 dense vectors

    def __init__(
        self,
        embed_model: str | None = None,
        rerank_model: str | None = None,
        embed_batch_size: int = 8,
        rerank_batch_size: int = 8,
        max_seq_length: int = 512,
    ) -> None:
        self.embed_model: str = embed_model or os.getenv("EMBED_MODEL") or "BAAI/bge-m3"
        self.rerank_model: str = (
            rerank_model or os.getenv("RERANK_MODEL") or "BAAI/bge-reranker-v2-m3"
        )
        self.embed_batch_size = embed_batch_size
        self.rerank_batch_size = rerank_batch_size
        self.max_seq_length = max_seq_length
        self._embedder: Any = None
        self._reranker: Any = None
        self._reranker_on_cpu = False

    @staticmethod
    def _cuda_available() -> bool:
        import torch

        return bool(torch.cuda.is_available())

    def _load_embedder(self) -> Any:
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            use_cuda = self._cuda_available()
            model = SentenceTransformer(self.embed_model, device="cuda" if use_cuda else "cpu")
            model.max_seq_length = self.max_seq_length
            if use_cuda:
                model.half()
            self._embedder = model
        return self._embedder

    def _load_reranker(self, force_cpu: bool = False) -> Any:
        if self._reranker is None or (force_cpu and not self._reranker_on_cpu):
            from sentence_transformers import CrossEncoder

            use_cuda = self._cuda_available() and not force_cpu
            model = CrossEncoder(
                self.rerank_model,
                device="cuda" if use_cuda else "cpu",
                max_length=self.max_seq_length,
            )
            if use_cuda:
                model.model.half()
            self._reranker = model
            self._reranker_on_cpu = not use_cuda
        return self._reranker

    def describe(self) -> dict[str, Any]:
        """What is configured and what is loaded right now, for the Settings screen.

        Only facts: torch is asked about the GPU only if it has already been imported (loading a
        model imports it), so a status check never triggers a slow import; until then the
        answer is None, meaning "not known yet".
        """
        import sys

        torch = sys.modules.get("torch")
        cuda: bool | None = None
        gpu_name: str | None = None
        if torch is not None:
            cuda = bool(torch.cuda.is_available())
            gpu_name = str(torch.cuda.get_device_name(0)) if cuda else None
        return {
            "backend": "sentence-transformers",
            "dim": self.dim,
            "cuda_available": cuda,
            "gpu_name": gpu_name,
            "embedder_loaded": self._embedder is not None,
            "reranker_loaded": self._reranker is not None,
            "embedder_device": str(self._embedder.device) if self._embedder is not None else None,
            "reranker_device": (
                None
                if self._reranker is None
                else ("cpu" if self._reranker_on_cpu else "cuda")
            ),
            "precision": None if cuda is None else ("fp16" if cuda else "fp32"),
            "max_seq_length": self.max_seq_length,
            "embed_batch_size": self.embed_batch_size,
            "rerank_batch_size": self.rerank_batch_size,
        }

    def warm(self) -> None:
        """Download (first run only) and load both models now, so the first real request is fast."""
        logger.info("Loading the embedding model %s ...", self.embed_model)
        self.embed(["warm-up"])
        logger.info("Loading the reranking model %s ...", self.rerank_model)
        self.rerank("warm-up", ["warm-up"])
        logger.info("Both models are ready.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        model = self._load_embedder()
        loaded = time.perf_counter()
        vectors = model.encode(
            texts,
            batch_size=self.embed_batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        logger.info(
            "embed: %d text(s) in %.2fs (model load %.2fs, device %s)",
            len(texts), time.perf_counter() - loaded, loaded - started, model.device,
        )
        return [[float(x) for x in row] for row in vectors]

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        started = time.perf_counter()
        result = self._rerank(query, passages)
        logger.info(
            "rerank: %d passage(s) in %.2fs (device %s)",
            len(passages), time.perf_counter() - started, "CPU" if self._reranker_on_cpu else "GPU",
        )
        return result

    def _rerank(self, query: str, passages: list[str]) -> list[float]:
        pairs = [(query, passage) for passage in passages]
        try:
            scores = self._load_reranker().predict(pairs, batch_size=self.rerank_batch_size)
        except RuntimeError as exc:
            # A 4 GB card can run out of memory when the embedder is also loaded.
            if "out of memory" not in str(exc).lower():
                raise
            import torch

            torch.cuda.empty_cache()
            scores = self._load_reranker(force_cpu=True).predict(
                pairs, batch_size=self.rerank_batch_size
            )
        return [float(s) for s in scores]


def backend_from_env() -> Backend:
    if os.getenv("MODEL_BACKEND", "sentence-transformers") == "fake":
        return FakeBackend()
    return SentenceTransformerBackend()
