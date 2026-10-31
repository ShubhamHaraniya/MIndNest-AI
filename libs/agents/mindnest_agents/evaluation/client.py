"""Running cases against a live MindNest API, as a signed-in student, over HTTP.

This drives the real thing: real login, real chat stream, the student's own provider key stored in
Settings. Use a test account: the planner cases add exams and tasks (removed again afterwards when
possible), and the calendar cases only ever ASK to change the calendar, they never approve."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from mindnest_agents.evaluation.cases import Case
from mindnest_agents.evaluation.trace import RunRecord, record_from_events


class EvalError(RuntimeError):
    pass


RATE_LIMIT_WAITS = (30.0, 60.0, 90.0)  # seconds to wait before trying a rate-limited case again

INGEST_HINTS = {
    "embedding_failed": (
        "The model service that reads documents is not reachable. Start it (scripts/start-models.ps1) "
        "and check MODEL_SERVICE_URL for the worker."
    ),
}


class EvalClient:
    def __init__(
        self, base_url: str, email: str, password: str, *, timeout: float = 240.0,
        case_timeout: float = 200.0, transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.email, self.password = email, password
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0), transport=transport)
        self.case_timeout = case_timeout  # one case may take no longer than this (the server stops a run at 180 s)
        self.conversations: list[str] = []

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _json(self, method: str, path: str, **kw: Any) -> Any:
        response = await self.http.request(method, f"{self.base}{path}", **kw)
        if response.status_code >= 400:
            raise EvalError(f"{method} {path} -> {response.status_code}: {response.text[:200]}")
        return response.json() if response.content else None

    async def login(self) -> None:
        await self._json("POST", "/auth/login", json={"email": self.email, "password": self.password})

    async def google_connected(self) -> bool:
        try:
            return bool((await self._json("GET", "/integrations/google-calendar/status")).get("connected"))
        except EvalError:
            return False

    # ----- test data

    async def make_subject(self, name: str, files: list[Path]) -> str:
        subject = await self._json("POST", "/subjects", json={"name": name})
        subject_id = str(subject["id"])
        try:
            for path in files:
                await self._json(
                    "POST", f"/subjects/{subject_id}/materials",
                    files={"file": (path.name, path.read_bytes())},
                )
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                items = await self._json("GET", f"/subjects/{subject_id}/materials")
                failed = [m for m in items if m["status"] == "failed"]
                if failed:
                    code = str(failed[0].get("error") or "unknown")
                    hint = INGEST_HINTS.get(code, "look at the worker log: docker compose logs worker")
                    raise EvalError(f"the test document {failed[0]['filename']} could not be processed ({code}). {hint}")
                if items and all(m["status"] == "ready" for m in items):
                    return subject_id
                await asyncio.sleep(2)
            raise EvalError("the test documents were not ready in time (is the worker running?)")
        except BaseException:
            await self._quiet("DELETE", f"/subjects/{subject_id}?confirm=true")  # do not leave a half-made subject behind
            raise

    async def remove_leftover_subjects(self, name: str) -> int:
        """Delete this test account's subjects called exactly `name` (what earlier runs left behind
        when they stopped early). Returns how many were deleted."""
        page = await self._json("GET", "/subjects?limit=100&state=all") or {}
        ids = [s["id"] for s in page.get("items", []) if s.get("name") == name]
        for subject_id in ids:
            await self._json("DELETE", f"/subjects/{subject_id}?confirm=true")
        return len(ids)

    async def snapshot_planner(self) -> tuple[set[str], set[str]]:
        exams = {e["id"] for e in (await self._json("GET", "/exams") or [])}
        page = await self._json("GET", "/planner/tasks") or {}
        return exams, {t["id"] for t in page.get("items", [])}

    async def cleanup(self, subject_id: str | None, before: tuple[set[str], set[str]] | None) -> None:
        """Best effort: nothing here may fail the report (the app may be down by now)."""
        for cid in self.conversations:
            await self._quiet("DELETE", f"/conversations/{cid}")
        if before is not None:
            try:
                exams, tasks = await self.snapshot_planner()
            except (EvalError, httpx.HTTPError):
                exams, tasks = before  # cannot see what was added: leave the planner as it is
            for eid in exams - before[0]:
                await self._quiet("DELETE", f"/exams/{eid}")
            for tid in tasks - before[1]:
                await self._quiet("DELETE", f"/planner/tasks/{tid}")
        if subject_id:
            await self._quiet("DELETE", f"/subjects/{subject_id}?confirm=true")

    async def _quiet(self, method: str, path: str) -> None:
        try:
            await self.http.request(method, f"{self.base}{path}")
        except httpx.HTTPError:
            pass

    # ----- one case

    async def _send(
        self, cid: str, payload: dict[str, Any], started: float
    ) -> tuple[int, str, list[tuple[str, dict[str, Any]]], int | None]:
        """One POST of a message and the events it streams back."""
        events: list[tuple[str, dict[str, Any]]] = []
        first: int | None = None
        async with self.http.stream("POST", f"{self.base}/conversations/{cid}/messages", json=payload) as r:
            if r.status_code >= 400:
                text = (await r.aread()).decode("utf-8", "replace")[:200]
                return r.status_code, text, events, first
            name, data = "", ""
            async for line in r.aiter_lines():
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    data = line[6:]
                elif not line and name and data:
                    parsed = json.loads(data)
                    if name == "token" and first is None:
                        first = int((time.perf_counter() - started) * 1000)
                    events.append((name, parsed))
                    name, data = "", ""
            return r.status_code, "", events, first

    async def run_case(
        self, case: Case, subject_id: str | None, provider: str | None, model: str | None
    ) -> RunRecord:
        """Run one case. A provider that is rate limiting says nothing about the agents, so such a
        run is tried again after a wait (in a fresh conversation) and, if it still cannot run, is
        reported as skipped rather than failed."""
        for wait in (*RATE_LIMIT_WAITS, None):
            record = await self._run_once(case, subject_id, provider, model)
            if not (record.status == "error" and record.error == "rate_limited"):
                return record
            if wait is None:
                break
            await asyncio.sleep(wait)
        return RunRecord(status="skipped", skipped_because="the AI provider's rate limit; run these cases again later")

    async def _run_once(
        self, case: Case, subject_id: str | None, provider: str | None, model: str | None
    ) -> RunRecord:
        body: dict[str, Any] = {"subject_id": subject_id if case.subject else None}
        conversation = await self._json("POST", "/conversations", json=body)
        cid = str(conversation["id"])
        self.conversations.append(cid)
        payload: dict[str, Any] = {"content": case.message}
        if provider and model:
            payload.update(provider=provider, model=model)
        for attempt in range(4):
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self.case_timeout):
                    status, error_text, events, first = await self._send(cid, payload, started)
            except TimeoutError:
                return RunRecord(status="error", error=f"timeout_after_{int(self.case_timeout)}s")
            if status == 429:  # the app's own per-minute chat limit: wait it out
                await asyncio.sleep(20 * (attempt + 1))
                continue
            if status >= 400:
                return RunRecord(status="error", error=f"http_{status}:{error_text}")
            total = int((time.perf_counter() - started) * 1000)
            return record_from_events(events, total_ms=total, first_token_ms=first)
        return RunRecord(status="error", error="rate_limited")
