"""Evaluation Lab: datasets, runs and results, with the real runner and a real database."""

import csv
import io
import json

import httpx
from mindnest_core.evalmetrics import JUDGE_SYSTEM

KEY = "sk-test-1234567890abcdef"
BIOLOGY = (
    b"Photosynthesis converts light energy into chemical energy inside chloroplasts. "
    b"The Calvin cycle then fixes carbon dioxide into sugars."
)
HISTORY = (
    b"The Battle of Plassey was fought in 1757 between the British East India Company "
    b"and the Nawab of Bengal."
)


def case(key, question, *, language="en", answerable=True, phrase=None, file=None, tags=None):  # type: ignore[no-untyped-def]
    evidence = [{"file": file, "phrase": phrase}] if phrase else []
    return {
        "id": key, "language": language, "question": question, "answerable": answerable,
        "reference_answer": "A reference answer." if answerable else None,
        "evidence": evidence, "tags": tags or [],
    }


def jsonl(*cases):  # type: ignore[no-untyped-def]
    return "\n".join(json.dumps(c, ensure_ascii=False) for c in cases)


DEFAULT_CASES = (
    case("en-01", "How does photosynthesis convert light energy?",
         phrase="light energy into chemical energy", file="biology.txt"),
    case("en-02", "When was the Battle of Plassey fought?", phrase="fought in 1757", file="history.txt"),
    case("en-03", "What is the capital of Mongolia?", answerable=False),
    case("hi-01", "मंगोलिया की राजधानी क्या है?", language="hi", answerable=False),
)


def corpus(user, ingest):  # type: ignore[no-untyped-def]
    subject_id = user.post("/subjects", json={"name": "Corpus"}).json()["id"]
    for name, data in (("biology.txt", BIOLOGY), ("history.txt", HISTORY)):
        material = user.post(f"/subjects/{subject_id}/materials", files={"file": (name, data)}).json()
        ingest(material["id"], user.id)
    return subject_id


def import_dataset(user, subject_id, cases=DEFAULT_CASES, name="rag", **extra):  # type: ignore[no-untyped-def]
    response = user.post(
        "/eval/datasets",
        json={"name": name, "subject_id": subject_id, "jsonl": jsonl(*cases), **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def start(user, dataset_id, queue, **body):  # type: ignore[no-untyped-def]
    response = user.post("/eval/runs", json={"dataset_id": dataset_id, **body})
    assert response.status_code == 201, response.text
    return response.json()


def finish(user, evaluate, run):  # type: ignore[no-untyped-def]
    evaluate(run["id"], user.id)
    return user.get(f"/eval/runs/{run['id']}").json()


# ------------------------------------------------------------------ datasets


def test_a_bad_question_file_is_refused_with_line_numbers(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    response = user.post("/eval/datasets", json={"name": "bad", "jsonl": "nope\n" + jsonl(case("x", "Q?"))})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_dataset"
    assert body["details"]["errors"][0] == "line 1: not valid JSON"
    assert user.get("/eval/datasets").json() == []  # nothing half-imported


def test_import_list_open_replace_and_delete(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    subject_id = corpus(user, ingest)
    created = import_dataset(user, subject_id)
    assert created["cases"] == 4 and created["unanswerable"] == 2
    assert created["languages"] == {"en": 3, "hi": 1}
    assert created["subject_name"] == "Corpus"

    again = user.post("/eval/datasets", json={"name": "rag", "jsonl": jsonl(*DEFAULT_CASES)})
    assert again.status_code == 409 and again.json()["code"] == "dataset_exists"

    replaced = import_dataset(user, subject_id, DEFAULT_CASES[:2], replace=True)
    assert replaced["id"] == created["id"] and replaced["cases"] == 2

    detail = user.get(f"/eval/datasets/{created['id']}").json()
    assert [c["key"] for c in detail["items"]] == ["en-01", "en-02"]
    assert detail["items"][0]["evidence"][0]["phrase"] == "light energy into chemical energy"
    assert [d["id"] for d in user.get("/eval/datasets").json()] == [created["id"]]

    assert user.delete(f"/eval/datasets/{created['id']}").status_code == 204
    assert user.get(f"/eval/datasets/{created['id']}").status_code == 404


def test_a_question_can_be_edited_by_hand(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    dataset = import_dataset(user, corpus(user, ingest))
    detail = user.get(f"/eval/datasets/{dataset['id']}").json()
    first = detail["items"][0]
    url = f"/eval/datasets/{dataset['id']}/cases/{first['id']}"

    edited = user.patch(url, json={"question": "What does photosynthesis do with light?", "tags": ["edited"]})
    assert edited.status_code == 200
    assert edited.json()["question"] == "What does photosynthesis do with light?"
    assert edited.json()["evidence"] == first["evidence"]  # untouched fields stay

    broken = user.patch(url, json={"evidence": []})
    assert broken.status_code == 422 and broken.json()["code"] == "invalid_case"


def test_the_check_finds_evidence_missing_from_the_materials(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    cases = (*DEFAULT_CASES[:2], case("en-09", "Where is it?", phrase="a sentence that is not in any file"))
    dataset = import_dataset(user, corpus(user, ingest), cases)
    report = user.get(f"/eval/datasets/{dataset['id']}/check").json()
    assert report["materials"] == ["biology.txt", "history.txt"]
    assert report["ok"] == 2 and report["missing"] == 1
    assert [c["key"] for c in report["cases"] if not c["ok"]] == ["en-09"]


# ------------------------------------------------------------------ isolation


def test_other_students_cannot_see_or_run_a_dataset(make_user, ingest, queue, evaluate):  # type: ignore[no-untyped-def]
    alice, bob = make_user(), make_user()
    dataset = import_dataset(alice, corpus(alice, ingest))
    run = start(alice, dataset["id"], queue)[0]
    finish(alice, evaluate, run)

    assert bob.get("/eval/datasets").json() == []
    assert bob.get(f"/eval/datasets/{dataset['id']}").status_code == 404
    assert bob.get(f"/eval/datasets/{dataset['id']}/check").status_code == 404
    assert bob.post("/eval/runs", json={"dataset_id": dataset["id"]}).status_code == 404
    assert bob.get("/eval/runs").json() == []
    assert bob.get(f"/eval/runs/{run['id']}").status_code == 404
    assert bob.get(f"/eval/runs/{run['id']}/results").status_code == 404
    assert bob.get(f"/eval/runs/{run['id']}/export").status_code == 404
    assert bob.post(f"/eval/runs/{run['id']}/cancel").status_code == 404
    assert bob.delete(f"/eval/runs/{run['id']}").status_code == 404
    assert alice.get(f"/eval/runs/{run['id']}").json()["status"] == "completed"


def test_the_lab_needs_a_signed_in_student(anon):  # type: ignore[no-untyped-def]
    assert anon.get("/eval/datasets").status_code == 401
    assert anon.post("/eval/runs", json={}).status_code == 401


# ------------------------------------------------------------------ runs


def test_a_run_needs_processed_materials(make_user):  # type: ignore[no-untyped-def]
    user = make_user()
    empty = user.post("/subjects", json={"name": "Empty"}).json()["id"]
    dataset = import_dataset(user, empty)
    response = user.post("/eval/runs", json={"dataset_id": dataset["id"]})
    assert response.status_code == 409 and response.json()["code"] == "no_materials"


def test_answers_need_a_key_and_judging_needs_answers(make_user, ingest):  # type: ignore[no-untyped-def]
    user = make_user()
    dataset = import_dataset(user, corpus(user, ingest))
    no_key = user.post("/eval/runs", json={"dataset_id": dataset["id"], "generate": True})
    assert no_key.status_code == 409 and no_key.json()["code"] == "no_provider_key"
    judge_only = user.post("/eval/runs", json={"dataset_id": dataset["id"], "judge": True})
    assert judge_only.status_code == 422
    unknown = user.post("/eval/runs", json={"dataset_id": dataset["id"], "modes": ["magic"]})
    assert unknown.status_code == 422


def test_search_modes_can_be_compared_without_any_key(make_user, ingest, queue, evaluate):  # type: ignore[no-untyped-def]
    user = make_user()
    dataset = import_dataset(user, corpus(user, ingest))
    modes = ["baseline", "hybrid", "advanced", "advanced_hybrid"]
    runs = start(user, dataset["id"], queue, modes=modes, label="compare")
    assert [r["config"]["mode"] for r in runs] == modes
    assert all(r["status"] == "queued" and r["total"] == 4 for r in runs)
    assert {(r["id"], user.id) for r in runs} <= set(queue.eval_jobs)

    finished = {r["config"]["mode"]: finish(user, evaluate, r) for r in runs}
    for run in finished.values():
        assert run["status"] == "completed" and run["done"] == run["total"] == 4
        assert run["finished_at"] and run["started_at"]
        metrics = run["summary"]["metrics"]
        assert {"recall_at_1", "recall_at_5", "recall_at_10", "recall_at_k", "mrr", "precision_at_k"} <= set(metrics)
        assert "correctness" not in metrics  # nothing was answered, so nothing was judged
        assert run["summary"]["answerable"] == 2 and run["summary"]["unanswerable"] == 2
        assert run["summary"]["degraded"] == 0

    advanced = finished["advanced"]["summary"]["metrics"]
    assert advanced["mrr"] == 1.0 and advanced["recall_at_k"] == 1.0
    results = {r["case_key"]: r for r in user.get(f"/eval/runs/{finished['advanced']['id']}/results").json()}
    assert results["en-01"]["retrieved"][0]["filename"] == "biology.txt"
    assert results["en-01"]["retrieved"][0]["relevant"] is True
    assert results["en-02"]["retrieved"][0]["filename"] == "history.txt"
    assert results["en-03"]["scores"] == {}  # unanswerable: no retrieval scores
    assert results["en-01"]["answer"] is None

    listed = user.get(f"/eval/runs?dataset_id={dataset['id']}").json()
    assert len(listed) == 4 and listed[0]["dataset_name"] == "rag"


def test_answers_are_generated_cited_and_judged(make_user, ingest, queue, evaluate, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    dataset = import_dataset(user, corpus(user, ingest))

    def responder(system, messages):  # type: ignore[no-untyped-def]
        if system == JUDGE_SYSTEM:
            refusal = "do NOT contain the answer" in messages[-1].content
            return [json.dumps({"correctness": 5, "faithfulness": 4, "relevance": 5, "abstained": refusal})]
        if "SOURCES: none" in system or "Mongolia" in messages[-1].content or "मंगोलिया" in messages[-1].content:
            return ["The materials do not contain that."]
        return ["It happens in the sources [1]."]

    llm.responder = responder
    run = start(user, dataset["id"], queue, generate=True, judge=True, delay_seconds=0)[0]
    assert run["config"]["provider"] == "openai" and run["config"]["generate"] is True
    done = finish(user, evaluate, run)
    assert done["status"] == "completed", done

    metrics = done["summary"]["metrics"]
    assert metrics["correctness"] == 1.0
    assert metrics["faithfulness"] == 0.8
    assert metrics["cited_any"] == 1.0 and metrics["citation_validity"] == 1.0
    assert metrics["citation_accuracy"] == 1.0
    assert metrics["abstain"] == 1.0 and metrics["false_refusal"] == 0.0
    assert done["summary"]["est_tokens_avg"] > 0
    assert done["summary"]["latency"]["answer_ms_p50"] is not None
    assert set(done["summary"]["by_language"]) == {"en", "hi"}

    answers = [c for c in llm.calls if c["system"] != JUDGE_SYSTEM]
    assert len(answers) == 4 and all(c["api_key"] == KEY for c in llm.calls)
    hindi = next(c for c in answers if "मंगोलिया" in c["messages"][-1].content)
    assert "Hindi" in hindi["system"]  # the case's language steers the answer language

    # The key is used for the calls but is nowhere in what the student can read back.
    results = user.get(f"/eval/runs/{done['id']}/results").json()
    assert KEY not in json.dumps([done, results])
    assert KEY not in json.dumps(user.get("/eval/runs").json())


def test_a_rejected_key_fails_the_whole_run(make_user, ingest, queue, evaluate, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    dataset = import_dataset(user, corpus(user, ingest))
    llm.error = "invalid_key"
    done = finish(user, evaluate, start(user, dataset["id"], queue, generate=True)[0])
    assert done["status"] == "failed" and done["error"] == "invalid_key"


def test_a_provider_outage_is_recorded_per_question(make_user, ingest, queue, evaluate, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    dataset = import_dataset(user, corpus(user, ingest))
    llm.error = "provider_unavailable"
    done = finish(user, evaluate, start(user, dataset["id"], queue, generate=True, delay_seconds=0)[0])
    assert done["status"] == "completed"
    assert done["summary"]["failed"] == 4
    results = user.get(f"/eval/runs/{done['id']}/results").json()
    assert {r["error"] for r in results} == {"provider_unavailable"}
    assert results[0]["retrieved"]  # search still ran and was recorded
    assert "recall_at_k" in done["summary"]["metrics"]


def test_search_that_fell_back_is_flagged_as_not_comparable(make_user, ingest, queue, evaluate):  # type: ignore[no-untyped-def]
    class Down:
        async def embed(self, texts):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("model service is down")

        async def rerank(self, query, passages):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("model service is down")

    user = make_user()
    dataset = import_dataset(user, corpus(user, ingest))
    run = start(user, dataset["id"], queue)[0]
    evaluate(run["id"], user.id, Down())
    done = user.get(f"/eval/runs/{run['id']}").json()
    assert done["status"] == "completed" and done["summary"]["degraded"] == 4


def test_a_cancelled_run_stays_cancelled(make_user, ingest, queue, evaluate):  # type: ignore[no-untyped-def]
    user = make_user()
    dataset = import_dataset(user, corpus(user, ingest))
    run = start(user, dataset["id"], queue)[0]
    assert user.post(f"/eval/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    evaluate(run["id"], user.id)  # a worker that picks it up later does nothing
    after = user.get(f"/eval/runs/{run['id']}").json()
    assert after["status"] == "cancelled" and after["done"] == 0
    assert user.get(f"/eval/runs/{run['id']}/results").json() == []
    assert user.delete(f"/eval/runs/{run['id']}").status_code == 204


def test_a_run_can_be_downloaded_with_everything_in_it(make_user, ingest, queue, evaluate, llm):  # type: ignore[no-untyped-def]
    user = make_user()
    user.request("PUT", "/settings/providers/openai", json={"api_key": KEY})
    cases = (
        case("en-01", "=HYPERLINK(\"x\") How does photosynthesis convert light energy?",
             phrase="light energy into chemical energy", file="biology.txt", tags=["factual", "bio"]),
        case("hi-01", "प्रकाश संश्लेषण क्या है?", language="hi", phrase="Photosynthesis converts", file="biology.txt"),
        case("en-03", "What is the capital of Mongolia?", answerable=False),
    )
    dataset = import_dataset(user, corpus(user, ingest), cases)
    llm.responder = lambda system, messages: ["It happens in the sources [1]."]
    run = start(user, dataset["id"], queue, generate=True, delay_seconds=0, label="my run")[0]
    done = finish(user, evaluate, run)
    assert done["status"] == "completed"

    whole = user.get(f"/eval/runs/{run['id']}/export?format=json")
    assert whole.status_code == 200
    assert "attachment" in whole.headers["content-disposition"] and ".json" in whole.headers["content-disposition"]
    data = whole.json()
    assert data["run"]["id"] == run["id"] and data["run"]["summary"]["answerable"] == 2
    assert [r["case_key"] for r in data["results"]] == ["en-01", "en-03", "hi-01"]
    first = data["results"][0]
    assert first["evidence"][0]["phrase"] == "light energy into chemical energy"
    assert first["tags"] == ["bio", "factual"] or set(first["tags"]) == {"factual", "bio"}
    assert first["retrieved"][0]["filename"] == "biology.txt" and "Photosynthesis" in first["retrieved"][0]["text"]
    assert first["answer"] == "It happens in the sources [1]." and first["scores"]["recall_at_k"] == 1.0
    assert "provider" in data["run"]["config"] and KEY not in whole.text

    per_question = user.get(f"/eval/runs/{run['id']}/export?format=questions_csv")
    assert per_question.status_code == 200 and "-questions.csv" in per_question.headers["content-disposition"]
    assert per_question.content.startswith(b"\xef\xbb\xbf")  # a byte-order mark, so Excel shows Hindi
    rows = list(csv.DictReader(io.StringIO(per_question.content.decode("utf-8-sig"))))
    assert [r["case_key"] for r in rows] == ["en-01", "en-03", "hi-01"]
    assert rows[0]["question"].startswith("'=HYPERLINK")  # never run as a formula in a spreadsheet
    assert rows[0]["first_relevant_rank"] == "1" and rows[0]["score_recall_at_k"] == "1.0"
    assert "biology.txt" in rows[0]["retrieved_files"] and "[relevant]" in rows[0]["retrieved_files"]
    assert rows[2]["question"] == "प्रकाश संश्लेषण क्या है?"
    assert "timing_retrieval_ms" in rows[0]

    passages = user.get(f"/eval/runs/{run['id']}/export?format=passages_csv")
    assert passages.status_code == 200 and "-passages.csv" in passages.headers["content-disposition"]
    lines = list(csv.DictReader(io.StringIO(passages.content.decode("utf-8-sig"))))
    assert {"case_key", "rank", "filename", "score", "relevant", "text"} <= set(lines[0])
    assert any(r["case_key"] == "en-01" and r["rank"] == "1" and r["relevant"] == "true" for r in lines)
    assert len(lines) == sum(len(r["retrieved"]) for r in data["results"])

    assert user.get(f"/eval/runs/{run['id']}/export?format=pdf").status_code == 422
