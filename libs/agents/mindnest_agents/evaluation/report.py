"""Reports: one JSON file for machines and one Markdown file for people, plus (optionally) scores
attached to the LangSmith traces of the same runs."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mindnest_agents.evaluation.metrics import CaseResult, summarize

logger = logging.getLogger("mindnest.eval")


def build_report(results: list[CaseResult], meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": {**meta, "created_at": datetime.now(UTC).isoformat(timespec="seconds")},
        "summary": summarize(results),
        "cases": [r.as_dict() for r in results],
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def to_markdown(report: dict[str, Any]) -> str:
    s, meta = report["summary"], report["meta"]
    ts, ro, tl, gr = s["task_success"], s["routing"], s["tools"], s["guardrails"]
    gd, tp, sp = s["grounding"], s["topic"], s["speed_and_cost"]
    lines = [
        f"# MindNest agent evaluation - {meta.get('mode', 'live')}",
        "",
        f"Run at {meta['created_at']}. Dataset `{meta.get('dataset', '')}` ({s['cases']} cases). "
        + (f"App model: {meta.get('model', 'the account default')}. " if meta.get("mode") != "offline" else "")
        + (f"Judge model: {meta['judge']}." if meta.get("judge") else "No judge model: model-judged scores are n/a."),
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Task success | {_pct(ts['rate'])} ({ts['passed']} of {ts['cases']}; {ts['skipped']} skipped) |",
        f"| Routing: right agents | {_pct(ro['exact'])} (first agent {_pct(ro['first_agent'])}, {ro['cases']} cases) |",
        f"| Tools: needed ones used | {_pct(tl['recall'])} ({tl['expected_calls']} expected calls); forbidden used: {tl['forbidden_used']} |",
        f"| Guardrails: attacks stopped | {_pct(gr['recall'])} (missed {gr['missed']}) |",
        f"| Guardrails: safe messages wrongly stopped | {_pct(gr['false_block_rate'])} ({gr['false_block']}) |",
        f"| Guardrails: second opinions asked | {gr['second_opinions']}; tool calls blocked: {gr['tool_calls_blocked']} |",
        f"| Grounding: answers cite a real source | {_pct(gd['citations_all_real'])} of {gd['citation_cases']} |",
        f"| Grounding: faithfulness (Ragas) | {_pct(gd['faithfulness'])} over {gd['faithfulness_cases']} answers |",
        f"| Topic adherence on off-topic requests | {_pct(tp['adherence'])} over {tp['cases']} |",
        f"| Speed: first word / finished (median) | {_ms(sp['first_token_ms']['p50'])} / {_ms(sp['total_ms']['p50'])} |",
        f"| Speed: first word / finished (95th pct) | {_ms(sp['first_token_ms']['p95'])} / {_ms(sp['total_ms']['p95'])} |",
        f"| Tokens per run | {sp['tokens_per_run'] if sp['tokens_per_run'] is not None else 'n/a'} (total {sp['tokens_total']}) |",
        "",
        "## By category",
        "",
        "| Category | Cases | Success |",
        "|---|---|---|",
        *[f"| {name} | {v['cases']} | {_pct(v['rate'])} |" for name, v in ts["by_category"].items()],
    ]
    if ro["confusion"]:
        lines += ["", "## Routing: expected agent (rows) and what was chosen", ""]
        for expected, got in ro["confusion"].items():
            lines.append(f"- **{expected}** -> " + ", ".join(f"{k} x{v}" for k, v in sorted(got.items())))
    failed = [c for c in report["cases"] if not c["passed"] and c["status"] != "skipped"]
    if failed:
        lines += ["", "## Failed cases", ""]
        for c in failed:
            lines.append(f"- `{c['id']}` ({c['category']}): {', '.join(c['failures']) or c['error']}")
    skipped = [c for c in report["cases"] if c["status"] == "skipped"]
    if skipped:
        lines += ["", "## Skipped", ""]
        lines += [f"- `{c['id']}`: {c['skipped_because']}" for c in skipped]
    if ts["failure_kinds"]:
        lines += ["", "## Failure kinds", "", ", ".join(f"{k} x{v}" for k, v in ts["failure_kinds"].items())]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], directory: Path, stem: str | None = None) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = stem or f"agents-{report['meta'].get('mode', 'live')}-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    json_path, md_path = directory / f"{stem}.json", directory / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path


def push_langsmith_feedback(
    results: list[CaseResult], *, api_key: str, endpoint: str = "https://api.smith.langchain.com", client: Any = None
) -> int:
    """Attach each run's scores to its trace (the trace id is the agent run id). Needs AGENT_TRACING
    on the server, otherwise there is no trace to attach to. Returns how many scores were sent."""
    if client is None:
        from langsmith import Client

        client = Client(api_key=api_key, api_url=endpoint)
    sent = 0
    for r in results:
        run_id = r.record.run_id
        if not run_id or r.record.status == "skipped":
            continue
        scores: dict[str, float | None] = {
            "task_success": 1.0 if r.passed else 0.0,
            "faithfulness": r.faithfulness,
            "topic_adherence": r.topic,
        }
        for key, score in scores.items():
            if score is None:
                continue
            try:
                client.create_feedback(
                    run_id, key, score=score,
                    comment=("; ".join(r.failures)[:300] if key == "task_success" and r.failures else None),
                )
                sent += 1
            except Exception:
                logger.warning("could not send feedback %s for %s", key, r.case.id, exc_info=False)
    return sent
