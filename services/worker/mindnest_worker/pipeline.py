"""The ingestion pipeline: file -> text -> chunks -> embeddings -> database.

Each stage is recorded in ingestion_jobs and committed on its own, so the web app can show
progress while the work runs. Failures end as a short error code on the material.
"""

import asyncio
import hashlib
import logging
import math
from collections import Counter
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
from mindnest_core.db import user_session
from mindnest_core.filetypes import extension_of, looks_like
from mindnest_core.settings import Settings
from mindnest_core.storage import ObjectStorage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mindnest_worker.chunking import Chunk, Segment, chunk_segments
from mindnest_worker.parsing import IngestError, parse_document, run_ocr

logger = logging.getLogger("mindnest.ingest")

MAX_CHUNKS_PER_MATERIAL = 20000

type SessionFactory = async_sessionmaker[AsyncSession]


@dataclass(frozen=True)
class EmbedResult:
    model: str
    vectors: list[list[float]]


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> EmbedResult: ...


class HttpEmbedder:
    """Calls the model service (services/models), which runs on the host GPU."""

    def __init__(self, base_url: str, batch_size: int = 16, retry_delay: float = 1.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._batch_size = batch_size
        self._retry_delay = retry_delay

    async def embed(self, texts: list[str]) -> EmbedResult:
        vectors: list[list[float]] = []
        model = ""
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0)) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                data = await self._post_with_retry(client, batch)
                model = data["model"]
                vectors.extend(data["embeddings"])
        return EmbedResult(model, vectors)

    async def _post_with_retry(self, client: httpx.AsyncClient, batch: list[str]) -> dict:  # type: ignore[type-arg]
        last: Exception | None = None
        for attempt in range(3):
            try:
                response = await client.post(f"{self._base_url}/embed", json={"texts": batch})
                if response.status_code >= 500:
                    raise IngestError("embedding_failed")
                response.raise_for_status()
                return response.json()  # type: ignore[no-any-return]
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                last = exc
                await asyncio.sleep(self._retry_delay * 2**attempt)
            except httpx.HTTPError as exc:
                raise IngestError("embedding_failed") from exc
        raise IngestError("embedding_unreachable") from last


class DeterministicEmbedder:
    """Hash-based vectors for tests and for running without the model service. Texts that share
    words get similar vectors, which is enough to exercise the pipeline; it is not a real model."""

    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim

    async def embed(self, texts: list[str]) -> EmbedResult:
        return EmbedResult("deterministic-test-embedder", [self._vector(t) for t in texts])

    def _vector(self, text_value: str) -> list[float]:
        vector = [0.0] * self._dim
        for word in text_value.lower().split():
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


@dataclass(frozen=True)
class MaterialInfo:
    id: UUID
    subject_id: UUID
    filename: str
    storage_key: str
    version: int
    visibility: str


class _Stages:
    """Keeps ingestion_jobs in step with the pipeline."""

    def __init__(self, factory: SessionFactory, owner_id: UUID, material_id: UUID) -> None:
        self._factory = factory
        self._owner_id = owner_id
        self._material_id = material_id

    async def reset(self) -> None:
        async with user_session(self._factory, self._owner_id) as session:
            await session.execute(
                text("DELETE FROM ingestion_jobs WHERE material_id = :id"), {"id": self._material_id}
            )

    async def begin(self, stage: str) -> None:
        async with user_session(self._factory, self._owner_id) as session:
            await session.execute(
                text(
                    "UPDATE ingestion_jobs SET status = 'done', updated_at = now() "
                    "WHERE material_id = :id AND status = 'running'"
                ),
                {"id": self._material_id},
            )
            await session.execute(
                text(
                    "INSERT INTO ingestion_jobs (material_id, stage, status, attempts) "
                    "VALUES (:id, :stage, 'running', 1)"
                ),
                {"id": self._material_id, "stage": stage},
            )

    async def finish(self, error: str | None = None) -> None:
        status = "failed" if error else "done"
        async with user_session(self._factory, self._owner_id) as session:
            await session.execute(
                text(
                    "UPDATE ingestion_jobs SET status = :status, error = :error, updated_at = now() "
                    "WHERE material_id = :id AND status = 'running'"
                ),
                {"id": self._material_id, "status": status, "error": error},
            )


async def _load_material(
    factory: SessionFactory, owner_id: UUID, material_id: UUID
) -> MaterialInfo | None:
    async with user_session(factory, owner_id) as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id, subject_id, filename, storage_key, version, visibility "
                        "FROM materials WHERE id = :id AND deleted_at IS NULL"
                    ),
                    {"id": material_id},
                )
            )
            .mappings()
            .first()
        )
    return MaterialInfo(**row) if row else None


async def _set_status(
    factory: SessionFactory,
    owner_id: UUID,
    material_id: UUID,
    status: str,
    error: str | None = None,
    language: str | None = None,
) -> None:
    async with user_session(factory, owner_id) as session:
        await session.execute(
            text(
                "UPDATE materials SET status = :status, error = :error, "
                "language = COALESCE(:language, language), updated_at = now() WHERE id = :id"
            ),
            {"id": material_id, "status": status, "error": error, "language": language},
        )


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6g}" for value in vector) + "]"


async def _store_chunks(
    factory: SessionFactory,
    owner_id: UUID,
    material: MaterialInfo,
    chunks: list[Chunk],
    result: EmbedResult,
) -> None:
    rows = [
        {
            "material_id": material.id,
            "version": material.version,
            "subject_id": material.subject_id,
            "owner_id": owner_id,
            "visibility": material.visibility,
            "page": chunk.page,
            "section": chunk.section,
            "text": chunk.text,
            "language": chunk.language,
            "embedding": _vector_literal(vector),
            "model": result.model,
        }
        for chunk, vector in zip(chunks, result.vectors, strict=True)
    ]
    async with user_session(factory, owner_id) as session:
        # Replacing, not appending, makes a retry safe.
        await session.execute(
            text("DELETE FROM chunks WHERE material_id = :id"), {"id": material.id}
        )
        await session.execute(
            text(
                "INSERT INTO chunks (material_id, material_version, subject_id, owner_id, "
                "visibility, page, section, text, language, embedding, embedding_model) "
                "VALUES (:material_id, :version, :subject_id, :owner_id, :visibility, :page, "
                ":section, :text, :language, CAST(:embedding AS vector), :model)"
            ),
            rows,
        )


async def run_ingestion(
    material_id: UUID,
    owner_id: UUID,
    *,
    factory: SessionFactory,
    storage: ObjectStorage,
    embedder: Embedder,
    settings: Settings,
) -> None:
    """Process one material end to end. Never raises: problems are recorded on the material."""
    material = await _load_material(factory, owner_id, material_id)
    if material is None:
        return  # deleted before the worker got to it

    stages = _Stages(factory, owner_id, material_id)
    try:
        await _set_status(factory, owner_id, material_id, "processing")
        await stages.reset()

        await stages.begin("validate")
        data = await asyncio.to_thread(storage.get_bytes, material.storage_key)
        extension = extension_of(material.storage_key)
        if not data or not looks_like(extension, data[:4096]):
            raise IngestError("unreadable_file")

        await stages.begin("parse")
        parsed = await asyncio.to_thread(parse_document, extension, data)
        segments: list[Segment] = list(parsed.segments)

        if parsed.needs_ocr:
            await stages.begin("ocr")
            extra = await asyncio.to_thread(
                run_ocr, extension, data, parsed, settings.ocr_languages, settings.max_ocr_pages
            )
            segments.extend(extra)
            segments.sort(key=lambda s: (s.page is None, s.page or 0))

        await stages.begin("chunk")
        chunks = chunk_segments(segments, settings.chunk_max_chars, settings.chunk_overlap_chars)
        if not chunks:
            raise IngestError("no_text")
        if len(chunks) > MAX_CHUNKS_PER_MATERIAL:
            raise IngestError("too_large")

        await stages.begin("embed")
        result = await embedder.embed([chunk.text for chunk in chunks])
        if len(result.vectors) != len(chunks):
            raise IngestError("embedding_failed")
        if any(len(vector) != settings.embedding_dim for vector in result.vectors):
            raise IngestError("embedding_dimension_mismatch")
        await _store_chunks(factory, owner_id, material, chunks, result)

        await stages.finish()
        language = Counter(chunk.language for chunk in chunks).most_common(1)[0][0]
        await _set_status(factory, owner_id, material_id, "ready", language=language)
    except IngestError as exc:
        await _record_failure(stages, factory, owner_id, material_id, exc.code)
    except Exception:
        logger.exception("Ingestion of material %s crashed", material_id)
        await _record_failure(stages, factory, owner_id, material_id, "internal")


async def _record_failure(
    stages: _Stages, factory: SessionFactory, owner_id: UUID, material_id: UUID, code: str
) -> None:
    try:
        await stages.finish(error=code)
        await _set_status(factory, owner_id, material_id, "failed", error=code)
    except Exception:
        logger.exception("Could not record the failure of material %s", material_id)
