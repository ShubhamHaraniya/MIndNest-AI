"""Finding the passages of a student's own materials that answer a question.

Three modes exist so the Evaluation Lab can compare them on the same questions:
  * baseline: meaning search only (the simplest thing that could work);
  * hybrid:   meaning + words, merged;
  * advanced: meaning search, then reranked (what chat uses).

  * meaning: pgvector nearest neighbours of the question's embedding;
  * words: Postgres full-text search, which catches exact terms the embedding blurs. Only the
    hybrid mode uses it (and every mode falls back to it when the question cannot be embedded).
In hybrid, reciprocal rank fusion merges the two lists. In advanced, the multilingual reranker
orders the meaning-search candidates. If the model service is down, search degrades to words
only instead of failing.
Row-level security already limits every row to the signed-in student.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("mindnest.retrieval")

RetrievalMode = Literal["baseline", "hybrid", "advanced"]
RETRIEVAL_MODES: tuple[str, ...] = ("baseline", "hybrid", "advanced")

RRF_K = 60
RERANK_CHARS = 1200


class ModelClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def rerank(self, query: str, passages: list[str]) -> list[float]: ...


class HttpModelClient:
    """Calls the model service (services/models) running on the host GPU."""

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(60.0, connect=3.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self._client.post("/embed", json={"texts": texts})
        response.raise_for_status()
        return response.json()["embeddings"]  # type: ignore[no-any-return]

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        response = await self._client.post("/rerank", json={"query": query, "passages": passages})
        response.raise_for_status()
        return response.json()["scores"]  # type: ignore[no-any-return]

    async def status(self) -> dict[str, Any]:
        """The model service's own report of its configuration and what is loaded."""
        response = await self._client.get("/status", timeout=httpx.Timeout(4.0, connect=2.0))
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


@dataclass
class Passage:
    chunk_id: UUID
    material_id: UUID
    filename: str
    page: int | None
    section: str | None
    text: str
    score: float = 0.0


@dataclass
class Retrieved:
    passages: list[Passage]
    # True when the model service could not be reached and only word search was used.
    degraded: bool = False


_COLUMNS = """
  c.id AS chunk_id, c.material_id, m.filename, c.page, c.section, c.text
"""

_FROM = """
  FROM chunks c
  JOIN materials m ON m.id = c.material_id
  WHERE c.is_active AND m.deleted_at IS NULL AND m.status = 'ready'
    AND (CAST(:subject AS uuid) IS NULL OR c.subject_id = CAST(:subject AS uuid))
    AND (CAST(:mats AS uuid[]) IS NULL OR c.material_id = ANY(CAST(:mats AS uuid[])))
"""

_VECTOR_SQL = f"""
  SELECT {_COLUMNS} {_FROM} AND c.embedding IS NOT NULL
  ORDER BY c.embedding <=> CAST(:embedding AS vector) LIMIT :n
"""

# plainto_tsquery joins words with AND, which finds nothing for a natural question. Turning
# the ANDs into ORs keeps Postgres's own tokenizer (so Hindi and Gujarati split the same way as
# when the chunks were indexed) while matching any of the words; ranking sorts out the rest.
_WORD_SQL = f"""
  SELECT {_COLUMNS} {_FROM}
    AND c.tsv @@ replace(plainto_tsquery('simple', :q)::text, ' & ', ' | ')::tsquery
  ORDER BY ts_rank_cd(c.tsv, replace(plainto_tsquery('simple', :q)::text, ' & ', ' | ')::tsquery) DESC
  LIMIT :n
"""


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6g}" for value in vector) + "]"


def _to_passage(row: object) -> Passage:
    mapping = row._mapping  # type: ignore[attr-defined]
    return Passage(
        chunk_id=mapping["chunk_id"],
        material_id=mapping["material_id"],
        filename=mapping["filename"],
        page=mapping["page"],
        section=mapping["section"],
        text=mapping["text"],
    )


def fuse(*rankings: list[Passage]) -> list[Passage]:
    """Reciprocal rank fusion: a passage ranked high in either list rises to the top."""
    scores: dict[UUID, float] = {}
    by_id: dict[UUID, Passage] = {}
    for ranking in rankings:
        for position, passage in enumerate(ranking):
            by_id[passage.chunk_id] = passage
            scores[passage.chunk_id] = scores.get(passage.chunk_id, 0.0) + 1.0 / (RRF_K + position + 1)
    ordered = sorted(by_id.values(), key=lambda p: scores[p.chunk_id], reverse=True)
    for passage in ordered:
        passage.score = scores[passage.chunk_id]
    return ordered


async def retrieve(
    session: AsyncSession,
    models: ModelClient,
    query: str,
    *,
    subject_id: UUID | None,
    candidates: int,
    top_k: int,
    mode: RetrievalMode = "advanced",
    material_ids: Sequence[UUID] | None = None,
) -> Retrieved:
    """Search the student's chunks. `material_ids` limits the search to those files (a chat the
    student pointed at chosen documents); None means no such limit."""
    degraded = False
    params = {
        "subject": str(subject_id) if subject_id else None,
        "mats": [str(m) for m in material_ids] if material_ids is not None else None,
        "n": candidates,
    }

    vector_hits: list[Passage] = []
    try:
        (vector,) = await models.embed([query])
        rows = await session.execute(
            text(_VECTOR_SQL), {**params, "embedding": _vector_literal(vector)}
        )
        vector_hits = [_to_passage(row) for row in rows]
    except (httpx.HTTPError, ValueError, KeyError):
        logger.warning("Embedding the question failed; using word search only", exc_info=True)
        degraded = True

    if mode == "baseline":
        # Nearest neighbours only: the score is the vector rank, so the order is unchanged.
        for position, passage in enumerate(vector_hits):
            passage.score = 1.0 / (position + 1)
        return Retrieved(vector_hits[:top_k], degraded)

    if mode == "advanced" and vector_hits:
        # Meaning search picks the candidates; the reranker then puts them in order.
        return await _rerank(models, query, vector_hits, top_k, degraded)

    rows = await session.execute(text(_WORD_SQL), {**params, "q": query})
    word_hits = [_to_passage(row) for row in rows]

    if mode == "advanced":
        # The question could not be embedded, so the candidates come from the words alone.
        return await _rerank(models, query, word_hits, top_k, degraded)

    merged = fuse(vector_hits, word_hits)[:candidates]
    return Retrieved(merged[:top_k], degraded)


async def _rerank(
    models: ModelClient, query: str, pool: list[Passage], top_k: int, degraded: bool
) -> Retrieved:
    if not pool:
        return Retrieved([], degraded)
    try:
        scores = await models.rerank(query, [p.text[:RERANK_CHARS] for p in pool])
        if len(scores) == len(pool):
            for passage, score in zip(pool, scores, strict=True):
                passage.score = float(score)
            pool.sort(key=lambda p: p.score, reverse=True)
    except (httpx.HTTPError, ValueError, KeyError):
        logger.warning("Reranking failed; keeping the search order", exc_info=True)
        degraded = True
    return Retrieved(pool[:top_k], degraded)
