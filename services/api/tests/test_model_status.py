"""Settings > Local retrieval models: the screen shows what the service reports, and says so when it cannot."""

import asyncio

import httpx
import pytest
from mindnest_api.deps import get_models
from mindnest_api.retrieval import HttpModelClient
from mindnest_core.settings import get_settings


class OldModels:
    """A model client from before /status existed: it can embed and rerank, nothing more."""

    async def embed(self, texts):  # type: ignore[no-untyped-def]
        return [[0.0] for _ in texts]

    async def rerank(self, query, passages):  # type: ignore[no-untyped-def]
        return [0.0 for _ in passages]


class ReportingModels(OldModels):
    def __init__(self, body: dict | Exception) -> None:  # type: ignore[type-arg]
        self.body = body

    async def status(self):  # type: ignore[no-untyped-def]
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.fixture
def use_models(app):  # type: ignore[no-untyped-def]
    previous = app.dependency_overrides[get_models]

    def _use(models) -> None:  # type: ignore[no-untyped-def]
        app.dependency_overrides[get_models] = lambda: models

    yield _use
    app.dependency_overrides[get_models] = previous


GOOD = {
    "status": "ok",
    "embed_model": "BAAI/bge-m3",
    "rerank_model": "BAAI/bge-reranker-v2-m3",
    "dim": 1024,
    "backend": "sentence-transformers",
    "cuda_available": True,
    "gpu_name": "Laptop GPU",
    "embedder_loaded": True,
    "reranker_loaded": False,
    "embedder_device": "cuda:0",
    "reranker_device": None,
    "precision": "fp16",
    "max_seq_length": 512,
    "embed_batch_size": 8,
    "rerank_batch_size": 8,
}


def test_the_screen_shows_what_the_service_reports(make_user, use_models):  # type: ignore[no-untyped-def]
    use_models(ReportingModels(GOOD))
    body = make_user().get("/settings/models").json()
    assert body["reachable"] is True and body["problem"] is None
    assert body["embedding"] == {"name": "BAAI/bge-m3", "loaded": True, "device": "cuda:0"}
    assert body["reranker"] == {"name": "BAAI/bge-reranker-v2-m3", "loaded": False, "device": None}
    assert body["dim"] == 1024 and body["dim_matches"] is (get_settings().embedding_dim == 1024)
    assert body["gpu_name"] == "Laptop GPU" and body["precision"] == "fp16"
    assert body["modes"] == ["baseline", "hybrid", "advanced"]
    assert body["latency_ms"] is not None


def test_an_unreachable_service_is_reported_not_guessed(make_user, use_models):  # type: ignore[no-untyped-def]
    use_models(ReportingModels(httpx.ConnectError("refused")))
    body = make_user().get("/settings/models").json()
    assert body["reachable"] is False and body["problem"] == "unreachable"
    assert body["embedding"] is None and body["reranker"] is None
    assert body["latency_ms"] is None and body["dim_matches"] is None


def test_an_old_service_without_a_status_report_is_flagged(make_user, use_models):  # type: ignore[no-untyped-def]
    use_models(OldModels())
    body = make_user().get("/settings/models").json()
    assert body["reachable"] is False and body["problem"] == "unsupported"


def test_a_malformed_report_is_flagged(make_user, use_models):  # type: ignore[no-untyped-def]
    use_models(ReportingModels({"status": "ok"}))
    assert make_user().get("/settings/models").json()["problem"] == "bad_response"


def test_the_screen_needs_a_signed_in_student(anon):  # type: ignore[no-untyped-def]
    assert anon.get("/settings/models").status_code == 401


def test_the_http_client_reads_the_status_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/status"
        return httpx.Response(200, json=GOOD)

    async def go() -> dict:  # type: ignore[type-arg]
        client = HttpModelClient("http://models.test", transport=httpx.MockTransport(handler))
        try:
            return await client.status()
        finally:
            await client.aclose()

    assert asyncio.run(go())["embed_model"] == "BAAI/bge-m3"
