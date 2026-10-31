import math

from fastapi.testclient import TestClient
from mindnest_models.backends import FakeBackend
from mindnest_models.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app(FakeBackend(dim=64)))


def test_embed_returns_one_unit_vector_per_text() -> None:
    response = make_client().post("/embed", json={"texts": ["binary search tree", "ટ્રી ડેટા સ્ટ્રક્ચર"]})
    body = response.json()
    assert response.status_code == 200
    assert body["dim"] == 64
    assert len(body["embeddings"]) == 2
    for vector in body["embeddings"]:
        assert len(vector) == 64
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)


def test_embed_is_deterministic() -> None:
    client = make_client()
    first = client.post("/embed", json={"texts": ["graph algorithms"]}).json()
    second = client.post("/embed", json={"texts": ["graph algorithms"]}).json()
    assert first["embeddings"] == second["embeddings"]


def test_rerank_prefers_overlapping_passage() -> None:
    response = make_client().post(
        "/rerank",
        json={
            "query": "binary search tree insertion",
            "passages": ["cooking pasta at home", "insertion in a binary search tree"],
        },
    )
    scores = response.json()["scores"]
    assert scores[1] > scores[0]


def test_embed_rejects_empty_input() -> None:
    assert make_client().post("/embed", json={"texts": []}).status_code == 422


def test_status_reports_the_real_configuration() -> None:
    body = make_client().get("/status").json()
    assert body["status"] == "ok"
    assert body["embed_model"] == "fake-hash-embedder"
    assert body["rerank_model"] == "fake-overlap-reranker"
    assert body["dim"] == 64
    assert body["backend"] == "fake"
    assert body["embedder_loaded"] is True


def test_the_sentence_transformer_backend_does_not_claim_a_gpu_before_torch_is_loaded() -> None:
    import sys

    from mindnest_models.backends import SentenceTransformerBackend

    backend = SentenceTransformerBackend(embed_model="x/embed", rerank_model="x/rerank")
    described = backend.describe()
    assert described["embedder_loaded"] is False and described["reranker_loaded"] is False
    assert described["embedder_device"] is None and described["reranker_device"] is None
    if "torch" not in sys.modules:
        assert described["cuda_available"] is None and described["precision"] is None
    assert described["max_seq_length"] == 512
