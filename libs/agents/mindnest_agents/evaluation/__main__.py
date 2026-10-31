"""Command line for the agent evaluation. See `python -m mindnest_agents.evaluation --help`."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx

from mindnest_agents.evaluation.cases import Case, load_cases
from mindnest_agents.evaluation.client import EvalClient, EvalError
from mindnest_agents.evaluation.metrics import CaseResult, check_case
from mindnest_agents.evaluation.offline import run_offline
from mindnest_agents.evaluation.report import build_report, push_langsmith_feedback, write_report
from mindnest_agents.evaluation.trace import RunRecord

DEFAULT_DATASET = Path("evals/agents/agent_v1.jsonl")
DEFAULT_CORPUS = Path("evals/agents/corpus")
DEFAULT_OUT = Path("evals/reports")


def _batches(items: list[Case], count: int) -> list[list[Case]]:
    """Split the cases into `count` consecutive groups of almost equal size (never an empty group)."""
    count = max(1, min(count, len(items))) if items else 1
    size, extra = divmod(len(items), count)
    out: list[list[Case]] = []
    start = 0
    for i in range(count):
        end = start + size + (1 if i < extra else 0)
        out.append(items[start:end])
        start = end
    return [group for group in out if group]


def _was_rate_limited(rec: RunRecord) -> bool:
    return rec.status == "skipped" and "rate limit" in (rec.skipped_because or "")


def _select(cases: list[Case], args: argparse.Namespace) -> list[Case]:
    if args.category:
        cases = [c for c in cases if c.category in args.category]
    if args.only:
        cases = [c for c in cases if c.id in args.only]
    return cases[: args.limit] if args.limit else cases


async def _offline(args: argparse.Namespace) -> int:
    cases = [c for c in _select(load_cases(args.dataset), args) if c.offline]
    results = await run_offline(cases)
    report = build_report(results, {"mode": "offline", "dataset": str(args.dataset)})
    json_path, md_path = write_report(report, args.out)
    _print(results, md_path)
    return 1 if any(r.failures for r in results) else 0


async def _run_one(
    client: EvalClient, case: Case, number: int, total: int, subject_id: str | None, google: bool,
    args: argparse.Namespace,
) -> CaseResult:
    skip = None
    if case.writes and not args.allow_writes:
        skip = "changes the planner or quizzes; run with --allow-writes on a test account"
    elif "google" in case.requires and not google:
        skip = "needs a connected Google Calendar"
    if skip:
        rec = RunRecord(status="skipped", skipped_because=skip)
    else:
        print(f"[{number:>2}/{total}] ...  {case.id}", flush=True)
        try:
            rec = await client.run_case(case, subject_id, args.provider, args.model)
        except (EvalError, httpx.HTTPError) as exc:  # the app failed on this case: record it, go on
            rec = RunRecord(status="error", error=f"{type(exc).__name__}: {str(exc)[:160]}")
        await asyncio.sleep(args.delay)
    result = CaseResult(case=case, record=rec, failures=check_case(case, rec))
    mark = "skip" if rec.status == "skipped" else ("ok  " if result.passed else "FAIL")
    print(f"[{number:>2}/{total}] {mark} {case.id}" + (f"  {result.failures}" if result.failures else ""))
    return result


async def _live(args: argparse.Namespace) -> int:
    email = args.email or os.environ.get("EVAL_EMAIL", "")
    password = args.password or os.environ.get("EVAL_PASSWORD", "")
    if not email or not password:
        print("Set --email/--password or EVAL_EMAIL/EVAL_PASSWORD (use a test account).", file=sys.stderr)
        return 2
    cases = _select(load_cases(args.dataset), args)
    client = EvalClient(args.api_url, email, password, case_timeout=args.case_timeout)
    subject_id: str | None = None
    before = None
    results: list[CaseResult] = []
    try:
        await client.login()
        google = await client.google_connected()
        if args.allow_writes:
            before = await client.snapshot_planner()
        print("Setting up the test subject and documents ...")
        subject_id = await client.make_subject("Eval Biology", sorted(args.corpus.glob("*.txt")))
        groups = _batches(cases, args.batches)
        total = len(cases)
        number = 0
        for index, group in enumerate(groups, start=1):
            if len(groups) > 1:
                if index > 1 and args.batch_pause > 0:
                    print(f"\n--- pausing {args.batch_pause:.0f} s so the provider's rate limit can recover ---", flush=True)
                    await asyncio.sleep(args.batch_pause)
                print(f"\n=== batch {index} of {len(groups)} ({len(group)} cases) ===", flush=True)
            for case in group:
                number += 1
                results.append(await _run_one(client, case, number, total, subject_id, google, args))
        # A provider that was rate limiting says nothing about the agents: try those cases once more.
        limited = [i for i, r in enumerate(results) if _was_rate_limited(r.record)]
        if limited:
            wait = max(args.batch_pause, 60.0)
            print(f"\n--- {len(limited)} case(s) were held back by the provider's rate limit; "
                  f"trying them again after {wait:.0f} s ---", flush=True)
            await asyncio.sleep(wait)
            for i in limited:
                case = results[i].case
                results[i] = await _run_one(client, case, i + 1, total, subject_id, google, args)
        judge_name = None
        key = os.environ.get("EVAL_JUDGE_API_KEY", "")
        if args.judge_provider and args.judge_model and key:
            from mindnest_agents.evaluation.judges import RagasJudge, RagasMissing, score_results
            from mindnest_agents.models import build_chat_model

            try:
                judge = RagasJudge(build_chat_model(args.judge_provider, args.judge_model, key, temperature=0.0))
                print("Scoring with Ragas ...")
                await score_results(results, judge)
                judge_name = f"{args.judge_provider}/{args.judge_model}"
            except RagasMissing as exc:
                print(str(exc), file=sys.stderr)
        else:
            print("No judge model given (--judge-provider, --judge-model, EVAL_JUDGE_API_KEY): "
                  "faithfulness and topic adherence are left out.")
    except (EvalError, httpx.HTTPError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        if results:
            partial = {"mode": "live", "dataset": str(args.dataset), "api_url": args.api_url, "partial": True}
            _, md_partial = write_report(build_report(results, partial), args.out)
            print(f"The {len(results)} case(s) finished before this were saved: {md_partial}", file=sys.stderr)
        return 2
    finally:
        await client.cleanup(subject_id, before)
        await client.aclose()
    meta = {
        "mode": "live", "dataset": str(args.dataset), "api_url": args.api_url,
        "model": f"{args.provider}/{args.model}" if args.provider and args.model else None, "judge": judge_name,
    }
    report = build_report(results, meta)
    json_path, md_path = write_report(report, args.out)
    if args.langsmith:
        key = os.environ.get("LANGSMITH_API_KEY", "")
        if key:
            sent = push_langsmith_feedback(results, api_key=key)
            print(f"Sent {sent} scores to LangSmith (needs AGENT_TRACING=true on the server).")
        else:
            print("--langsmith needs LANGSMITH_API_KEY in the environment.", file=sys.stderr)
    _print(results, md_path)
    return 0


async def _cleanup(args: argparse.Namespace) -> int:
    email = args.email or os.environ.get("EVAL_EMAIL", "")
    password = args.password or os.environ.get("EVAL_PASSWORD", "")
    if not email or not password:
        print("Set --email/--password or EVAL_EMAIL/EVAL_PASSWORD (the TEST account).", file=sys.stderr)
        return 2
    client = EvalClient(args.api_url, email, password)
    try:
        await client.login()
        removed = await client.remove_leftover_subjects("Eval Biology")
        print(f"Removed {removed} leftover 'Eval Biology' subject(s) from {email}.")
    except (EvalError, httpx.HTTPError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2
    finally:
        await client.aclose()
    return 0


def _print(results: list[CaseResult], md_path: Path) -> None:
    ran = [r for r in results if r.record.status != "skipped"]
    passed = sum(r.passed for r in ran)
    print(f"\n{passed} of {len(ran)} cases passed ({len(results) - len(ran)} skipped). Report: {md_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mindnest_agents.evaluation", description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for name, help_text in (
        ("offline", "check the guardrails alone (no server, no model)"),
        ("live", "run every case against a running MindNest API as a student"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
        p.add_argument("--out", type=Path, default=DEFAULT_OUT)
        p.add_argument("--category", action="append", help="only this category (repeatable)")
        p.add_argument("--only", action="append", help="only this case id (repeatable)")
        p.add_argument("--limit", type=int, default=0)
    live = sub.choices["live"]
    live.add_argument("--api-url", default=os.environ.get("EVAL_API_URL", "http://localhost:3000/api/v1"))
    live.add_argument("--email")
    live.add_argument("--password")
    live.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    live.add_argument("--provider", help="provider of the app under test (default: the account's)")
    live.add_argument("--model", help="model of the app under test")
    live.add_argument("--judge-provider", help="provider of the judge model (with --judge-model)")
    live.add_argument("--judge-model")
    live.add_argument("--allow-writes", action="store_true", help="also run cases that add planner items or quizzes")
    live.add_argument("--delay", type=float, default=4.0, help="seconds between cases (the app allows 20 chat messages a minute; raise this if your AI provider limits you)")
    live.add_argument("--batches", type=int, default=1, help="split the run into this many groups, with a pause between them")
    live.add_argument("--batch-pause", type=float, default=60.0, help="seconds to wait between groups (lets a provider's rate limit recover)")
    live.add_argument("--case-timeout", type=float, default=200.0, help="seconds one case may take before it counts as an error")
    live.add_argument("--langsmith", action="store_true", help="attach scores to the LangSmith traces")
    tidy = sub.add_parser("cleanup", help="delete the 'Eval Biology' subjects that stopped runs left in the TEST account")
    tidy.add_argument("--api-url", default=os.environ.get("EVAL_API_URL", "http://localhost:3000/api/v1"))
    tidy.add_argument("--email")
    tidy.add_argument("--password")
    args = parser.parse_args(argv)
    try:
        if args.mode == "cleanup":
            return asyncio.run(_cleanup(args))
        return asyncio.run(_offline(args) if args.mode == "offline" else _live(args))
    except KeyboardInterrupt:
        print("\nStopped by you. The test subject and conversations were removed where possible.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
