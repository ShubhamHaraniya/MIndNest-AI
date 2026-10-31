"""Produce REAL Evaluation Lab data in a development database, without the model service.

What it does (every number in the lab afterwards comes from the project's own evaluation code):

  1. Uploads the evaluation corpus (default: a folder of the documents named by evals/datasets/*.jsonl)
     as one subject of the signed-in student, and processes each file with the worker's own pipeline
     (same parser, same chunker) using the hash-based test embedder instead of BGE-M3.
  2. Imports evals/datasets/rag_v1.jsonl and rag_v1_en.jsonl through the real /eval/datasets endpoint.
  3. Creates retrieval runs (baseline, hybrid, advanced) and executes them with the real runner
     (mindnest_worker.evaluation.run_evaluation). Search uses the hash-based embedder and a word-overlap
     reranker, exactly the test doubles of services/api/tests/conftest.py. The stored config says so.
  4. Runs the agent guardrail suite (evals/agents/agent_v1.jsonl, the cases marked "offline") several
     times with the real `mindnest_agents.evaluation` code and stores every trial, with the rail
     decision of each, so pass@k and pass^k can be computed from real trials.

It never writes a number itself: scores come from run_evaluation and mindnest_agents.evaluation.
Nothing here changes evaluation logic. Re-running adds new runs; datasets are replaced in place.

    python scripts/seed_eval_demo.py --email raj.demo@example.com --password '...' \
        --corpus /path/to/corpus --trials 5
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import requests
from mindnest_agents.evaluation.cases import load_cases
from mindnest_agents.evaluation.metrics import CaseResult, summarize
from mindnest_agents.evaluation.offline import run_offline
from mindnest_agents.guardrails import Guardrails
from mindnest_core.db import make_engine, make_session_factory, user_session
from mindnest_core.settings import get_settings
from mindnest_core.storage import S3Storage
from mindnest_worker.evaluation import run_evaluation
from mindnest_worker.pipeline import DeterministicEmbedder, run_ingestion
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
SUBJECT_NAME = "Evaluation corpus (AI study library)"
EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}


class HashingModels:
    """The search-side test doubles: hash-based embeddings and a word-overlap reranker."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = await DeterministicEmbedder(get_settings().embedding_dim).embed(texts)
        return result.vectors

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        words = set(query.lower().split())
        return [float(len(words & set(p.lower().split()))) for p in passages]


class NoLLM:
    """Retrieval-only runs never call the model."""

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("retrieval-only runs do not call a model")


async def _no_sleep(_seconds: float) -> None:
    return None


def app_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def language_of(message: str) -> str:
    if re.search(r"[઀-૿]", message):
        return "gu"
    if re.search(r"[ऀ-ॿ]", message):
        return "hi"
    return "en"


# ------------------------------------------------------------------------------------ corpus


def login(api: str, email: str, password: str) -> requests.Session:
    session = requests.Session()
    response = session.post(f"{api}/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return session


async def owner_one(owner_factory: Any, sql: str, **params: Any) -> Any:
    async with owner_factory() as session, session.begin():
        return (await session.execute(text(sql), params)).first()


async def ensure_corpus(api: str, http: requests.Session, corpus: Path, owner_factory: Any, user_id: UUID) -> UUID:
    row = await owner_one(
        owner_factory, "SELECT id FROM subjects WHERE owner_id = :u AND name = :n", u=user_id, n=SUBJECT_NAME
    )
    if row is None:
        created = http.post(
            f"{api}/subjects",
            json={"name": SUBJECT_NAME, "course_code": "EVAL", "description": "Documents the Evaluation Lab questions were written against."},
        )
        created.raise_for_status()
        subject_id = UUID(created.json()["id"])
    else:
        subject_id = row[0]
    have = {m["filename"] for m in http.get(f"{api}/subjects/{subject_id}/materials").json()}
    for path in sorted(p for p in corpus.iterdir() if p.suffix.lower() in EXTENSIONS):
        if path.name in have:
            continue
        uploaded = http.post(
            f"{api}/subjects/{subject_id}/materials", files={"file": (path.name, path.read_bytes())}, data={"kind": "material"}
        )
        uploaded.raise_for_status()
        print("uploaded", path.name)
    return subject_id


async def ingest_pending(factory: Any, user_id: UUID, subject_id: UUID) -> None:
    settings = get_settings()
    storage = S3Storage(settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key, settings.s3_bucket)
    async with user_session(factory, user_id) as session:
        pending = (
            await session.execute(
                text("SELECT id, filename FROM materials WHERE subject_id = :s AND status <> 'ready' AND deleted_at IS NULL"),
                {"s": subject_id},
            )
        ).all()
    for material_id, filename in pending:
        await run_ingestion(
            material_id, user_id, factory=factory, storage=storage,
            embedder=DeterministicEmbedder(settings.embedding_dim), settings=settings,
        )
        print("processed", filename)


# ------------------------------------------------------------------------------- retrieval runs


def import_dataset(api: str, http: requests.Session, path: Path, name: str, description: str, subject_id: UUID) -> dict[str, Any]:
    body = {
        "name": name, "description": description, "subject_id": str(subject_id),
        "jsonl": path.read_text(encoding="utf-8"), "replace": True,
    }
    response = http.post(f"{api}/eval/datasets", json=body)
    response.raise_for_status()
    return dict(response.json())


async def run_retrieval(
    factory: Any, owner_factory: Any, user_id: UUID, dataset_id: UUID, dataset_file: Path,
    mode: str, top_k: int, candidates: int,
) -> UUID:
    settings = get_settings()
    config: dict[str, Any] = {
        "kind": "retrieval", "mode": mode, "top_k": top_k, "candidates": candidates,
        "generate": False, "judge": False, "provider": None, "model": None, "judge_model": None, "delay_seconds": 0,
        # Provenance of this particular execution (read by the lab; not used by the runner).
        "embedder": "hash-based test embedder (1024-d, local)",
        "reranker": "word-overlap test reranker (local)" if mode == "advanced" else None,
        "environment": "local sandbox without the model service; scores are for pipeline comparison, not BGE-M3 quality",
        "dataset_file": str(dataset_file.relative_to(ROOT)),
        "dataset_file_sha256": file_sha256(dataset_file),
        "app_version": app_version(),
        "git_commit": None,
        "seed": None,
        "deterministic": True,
        "executed_by": "scripts/seed_eval_demo.py",
    }
    label = f"{mode} · k={top_k}"
    async with user_session(factory, user_id) as session:
        total = (await session.execute(text("SELECT count(*) FROM eval_cases WHERE dataset_id = :d"), {"d": dataset_id})).scalar_one()
        run_id = (
            await session.execute(
                text(
                    "INSERT INTO eval_runs (user_id, dataset_id, label, config, total) "
                    "VALUES (:u, :d, :l, CAST(:c AS jsonb), :t) RETURNING id"
                ),
                {"u": user_id, "d": dataset_id, "l": label, "c": json.dumps(config), "t": total},
            )
        ).scalar_one()
    await run_evaluation(
        run_id, user_id, factory=factory, models=HashingModels(), llm=NoLLM(),  # type: ignore[arg-type]
        settings=settings, sleep=_no_sleep, backoff=(0.0,),
    )
    print("retrieval run", mode, top_k, run_id)
    return UUID(str(run_id))


# ------------------------------------------------------------------------------------ agent runs


class RecordingGuard(Guardrails):
    """The real input rail; remembers each decision so the trace can show what the rail did."""

    def __init__(self) -> None:
        super().__init__()
        self.decisions: list[Any] = []

    async def check_input(self, *args: Any, **kwargs: Any) -> Any:
        decision = await super().check_input(*args, **kwargs)
        self.decisions.append(decision)
        return decision


def expectation_text(case: Any) -> str:
    exp = case.expect
    parts = []
    guard = exp.get("guard_offline", exp.get("guard"))
    if guard == "block":
        parts.append("The input rail stops the message.")
    elif guard == "allow":
        parts.append("The input rail lets the message through.")
    if exp.get("answer_any"):
        parts.append("The reply mentions one of: " + ", ".join(exp["answer_any"]) + ".")
    return " ".join(parts) or "No rule listed."


async def run_agent_trials(
    factory: Any, owner_factory: Any, user_id: UUID, dataset_path: Path, trials: int, subject_id: UUID | None
) -> UUID:
    cases = [c for c in load_cases(dataset_path) if c.offline]
    name = "agent_v1_offline"
    description = (
        f"{len(cases)} of the {len(load_cases(dataset_path))} cases in evals/agents/agent_v1.jsonl: the ones the input "
        "guardrails alone can decide (python -m mindnest_agents.evaluation offline). Cases that need a model "
        "(routing, tools, grounding) were not run."
    )
    async with owner_factory() as session, session.begin():
        await session.execute(text("DELETE FROM eval_datasets WHERE user_id = :u AND name = :n"), {"u": user_id, "n": name})
        dataset_id = (
            await session.execute(
                text("INSERT INTO eval_datasets (user_id, subject_id, name, description) VALUES (:u, NULL, :n, :d) RETURNING id"),
                {"u": user_id, "n": name, "d": description},
            )
        ).scalar_one()
        case_ids: dict[str, UUID] = {}
        for case in cases:
            guard = case.expect.get("guard_offline", case.expect.get("guard"))
            tags = [case.category, "suite:agent"] + ([f"guard:{guard}"] if guard else [])
            case_ids[case.id] = (
                await session.execute(
                    text(
                        "INSERT INTO eval_cases (dataset_id, user_id, case_key, language, question, reference_answer, "
                        "answerable, evidence, tags) VALUES (:d, :u, :k, :l, :q, :r, true, '[]'::jsonb, CAST(:t AS text[])) RETURNING id"
                    ),
                    {"d": dataset_id, "u": user_id, "k": case.id, "l": language_of(case.message), "q": case.message,
                     "r": expectation_text(case), "t": tags},
                )
            ).scalar_one()

    started = datetime.now(UTC)
    per_case: dict[str, list[dict[str, Any]]] = {c.id: [] for c in cases}
    trial_results: list[list[CaseResult]] = []
    for trial in range(1, trials + 1):
        guard = RecordingGuard()
        began = time.perf_counter()
        results = await run_offline(cases, guard)
        trial_results.append(results)
        print(f"agent trial {trial}: {sum(r.passed for r in results)}/{len(results)} passed in {time.perf_counter() - began:.1f}s")
        for result, decision in zip(results, guard.decisions, strict=True):
            steps = [
                {
                    "seq": 1, "kind": "rail", "rail": "input", "action": decision.action, "code": decision.code,
                    "category": decision.category, "reasons": decision.reasons, "judged": decision.judged,
                    "judge": decision.judge, "engine": decision.engine, "ms": decision.ms,
                }
            ]
            if result.record.answer:
                steps.append({"seq": 2, "kind": "answer", "text": result.record.answer[:1200], "ms": 0})
            per_case[result.case.id].append(
                {
                    "trial": trial, "passed": result.passed, "failures": result.failures, "status": result.record.status,
                    "total_ms": result.record.total_ms, "route": None, "steps": steps,
                    "answer": result.record.answer[:1200],
                }
            )
    finished = datetime.now(UTC)

    first = summarize(trial_results[0])
    config = {
        "kind": "agent", "mode": "offline_guardrails", "trials": trials, "top_k": None, "candidates": None,
        "generate": False, "judge": False, "provider": None, "model": None,
        "embedder": None, "reranker": None,
        "environment": "local sandbox; input rail only (NeMo Guardrails rules, no second-opinion model)",
        "dataset_file": str(dataset_path.relative_to(ROOT)),
        "dataset_file_sha256": file_sha256(dataset_path),
        "app_version": app_version(), "git_commit": None, "seed": None, "deterministic": True,
        "executed_by": "scripts/seed_eval_demo.py",
        "not_run": "cases that need a model (routing, tools, grounding, speed)",
    }
    summary = {
        "cases": len(cases), "failed": 0, "degraded": 0, "answerable": len(cases), "unanswerable": 0,
        "metrics": {
            "pass_rate": first["task_success"]["rate"],
            "attack_recall": first["guardrails"]["recall"],
            "false_block_rate": first["guardrails"]["false_block_rate"],
        },
        "by_language": {},
        "latency": {},
        "est_tokens_avg": None,
        "agent": first,
    }
    async with user_session(factory, user_id) as session:
        run_id = (
            await session.execute(
                text(
                    "INSERT INTO eval_runs (user_id, dataset_id, label, config, status, total, done, summary, "
                    "created_at, started_at, finished_at) VALUES (:u, :d, :l, CAST(:c AS jsonb), 'completed', :t, :t, "
                    "CAST(:s AS jsonb), :st, :st, :fi) RETURNING id"
                ),
                {"u": user_id, "d": dataset_id, "l": f"guardrails · {trials} trials", "c": json.dumps(config),
                 "t": len(cases), "s": json.dumps(summary), "st": started, "fi": finished},
            )
        ).scalar_one()
        for case in cases:
            trials_list = per_case[case.id]
            passes = sum(1 for t in trials_list if t["passed"])
            times = sorted(float(t["total_ms"]) for t in trials_list)
            await session.execute(
                text(
                    "INSERT INTO eval_results (run_id, case_id, user_id, retrieved, answer, scores, timings, error) "
                    "VALUES (:r, :c, :u, CAST(:ret AS jsonb), :a, CAST(:s AS jsonb), CAST(:t AS jsonb), NULL)"
                ),
                {
                    "r": run_id, "c": case_ids[case.id], "u": user_id,
                    "ret": json.dumps(trials_list, ensure_ascii=False),
                    "a": trials_list[-1]["answer"] or None,
                    "s": json.dumps({"passes": passes, "trials": len(trials_list), "pass_rate": passes / len(trials_list)}),
                    "t": json.dumps({"total_ms_median": times[len(times) // 2], "total_ms_max": times[-1]}),
                },
            )
    print("agent run", run_id)
    return UUID(str(run_id))


# --------------------------------------------------------------------------------------- main


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--skip-retrieval", action="store_true")
    parser.add_argument("--skip-agent", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    owner_factory = make_session_factory(make_engine(settings.migration_database_url))
    http = login(args.api, args.email, args.password)
    me = http.get(f"{args.api}/auth/me").json()
    user_id = UUID(me["id"])

    subject_id: UUID | None = None
    if not args.skip_retrieval:
        subject_id = await ensure_corpus(args.api, http, args.corpus, owner_factory, user_id)
        await ingest_pending(factory, user_id, subject_id)
        datasets = {
            "rag_v1": ("Multilingual RAG set: 50 questions (en 26, hi 12, gu 12), 5 not answerable.", ROOT / "evals/datasets/rag_v1.jsonl"),
            "rag_v1_en": ("English-only subset of rag_v1 (26 questions).", ROOT / "evals/datasets/rag_v1_en.jsonl"),
        }
        imported = {name: import_dataset(args.api, http, path, name, desc, subject_id) for name, (desc, path) in datasets.items()}
        plan = [("rag_v1", 6), ("rag_v1", 10), ("rag_v1_en", 6)]
        for name, k in plan:
            for mode in ("baseline", "hybrid", "advanced"):
                await run_retrieval(
                    factory, owner_factory, user_id, UUID(imported[name]["id"]), datasets[name][1], mode, k, settings.retrieval_candidates
                )
        # Keep the corpus out of the student's course lists; the runs still search it.
        async with owner_factory() as session, session.begin():
            await session.execute(text("UPDATE subjects SET archived_at = now() WHERE id = :s AND archived_at IS NULL"), {"s": subject_id})
    if not args.skip_agent:
        await run_agent_trials(factory, owner_factory, user_id, ROOT / "evals/agents/agent_v1.jsonl", args.trials, subject_id)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
