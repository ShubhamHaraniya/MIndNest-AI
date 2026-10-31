#!/usr/bin/env python3
"""A small load test for a running MindNest AI server.

    python scripts/loadtest.py https://study.myschool.org --users 20 --seconds 60

It signs up a few throw-away accounts, then runs many "students" at once. Each student keeps
doing ordinary things (open the dashboard, list subjects, view the planner and calendar, create and
delete a subject) and the script reports how long every kind of request took.

It does NOT call the AI (that would cost money and depends on your provider). Test chat
separately, by hand, with a real key.

Safety: it only touches the accounts it creates (email loadtest-<random>@example.org), and
removes the subjects it makes. Disable the accounts afterwards on the Admin page. Point it at a
test copy if you can; if you must use the live site, run it when few students are online.
Sign-ups are limited to 10 per hour per address, so --accounts is capped at 8.

Needs: pip install httpx   (already installed wherever the API's dependencies are)
Exit status: 0 = within the limits you set, 1 = too slow or too many errors.
"""

import argparse
import asyncio
import math
import random
import secrets
import statistics
import sys
import time
from collections import defaultdict

import httpx

PASSWORD = "loadtest-" + secrets.token_hex(8)


class Stats:
    def __init__(self) -> None:
        self.times: dict[str, list[float]] = defaultdict(list)
        self.errors: dict[str, int] = defaultdict(int)
        self.limited: dict[str, int] = defaultdict(int)
        self.first_error: dict[str, str] = {}

    def record(self, name: str, seconds: float, status: int, detail: str = "") -> None:
        if status == 429:
            self.limited[name] += 1
            return
        self.times[name].append(seconds)
        if status >= 400 or status == 0:
            self.errors[name] += 1
            self.first_error.setdefault(name, f"HTTP {status} {detail[:120]}")


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[index]


async def timed(
    client: httpx.AsyncClient, stats: Stats, name: str, method: str, path: str, **kwargs: object
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        response = await client.request(method, path, **kwargs)  # type: ignore[arg-type]
    except httpx.HTTPError as exc:
        stats.record(name, time.perf_counter() - started, 0, type(exc).__name__)
        return None
    stats.record(name, time.perf_counter() - started, response.status_code, response.text)
    return response


async def student(base: str, session: str, cookie_name: str, deadline: float, stats: Stats) -> None:
    async with httpx.AsyncClient(
        base_url=base, cookies={cookie_name: session}, timeout=30, headers={"Accept": "application/json"}
    ) as client:
        while time.monotonic() < deadline:
            roll = random.random()
            if roll < 0.30:
                await timed(client, stats, "GET /auth/me", "GET", "/api/v1/auth/me")
            elif roll < 0.55:
                await timed(client, stats, "GET /subjects", "GET", "/api/v1/subjects")
            elif roll < 0.70:
                await timed(client, stats, "GET /stats", "GET", "/api/v1/stats")
            elif roll < 0.80:
                await timed(client, stats, "GET /planner/tasks", "GET", "/api/v1/planner/tasks")
            elif roll < 0.88:
                await timed(client, stats, "GET /exams", "GET", "/api/v1/exams")
            else:
                created = await timed(
                    client, stats, "POST /subjects", "POST", "/api/v1/subjects",
                    json={"name": f"loadtest {secrets.token_hex(3)}"},
                )
                if created is not None and created.status_code == 201:
                    await timed(
                        client, stats, "DELETE /subjects/{id}", "DELETE",
                        f"/api/v1/subjects/{created.json()['id']}?confirm=true",
                    )
            await asyncio.sleep(random.uniform(0.05, 0.4))  # a student reads before clicking


async def make_accounts(base: str, count: int, domain: str) -> tuple[str, list[str]]:
    sessions: list[str] = []
    cookie_name = "mindnest_session"
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        health = await client.get("/api/v1/ready")
        if health.status_code != 200:
            raise SystemExit(f"Server is not ready: HTTP {health.status_code} {health.text[:200]}")
        for _ in range(count):
            email = f"loadtest-{secrets.token_hex(5)}@{domain}"
            response = await client.post(
                "/api/v1/auth/signup",
                json={"email": email, "password": PASSWORD, "display_name": "Load Test"},
            )
            if response.status_code != 201:
                raise SystemExit(f"Could not create a test account: HTTP {response.status_code} {response.text[:200]}")
            client.cookies.clear()
            cookie = next((c for c in response.headers.get_list("set-cookie") if "=" in c), "")
            name, _, rest = cookie.partition("=")
            cookie_name = name or cookie_name
            sessions.append(rest.split(";", 1)[0])
            print(f"  created {email}")
    return cookie_name, sessions


def report(stats: Stats, seconds: float, max_p95_ms: float, max_error_rate: float) -> bool:
    print(f"\n{'request':24} {'count':>7} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'errors':>7} {'429':>5}")
    total = errors = 0
    worst_p95 = 0.0
    for name in sorted(stats.times):
        values = stats.times[name]
        p50, p95, p99 = (percentile(values, p) * 1000 for p in (50, 95, 99))
        worst_p95 = max(worst_p95, p95)
        total += len(values)
        errors += stats.errors[name]
        print(f"{name:24} {len(values):7d} {p50:8.0f} {p95:8.0f} {p99:8.0f} {stats.errors[name]:7d} {stats.limited[name]:5d}")
    rate = errors / total if total else 1.0
    mean = statistics.fmean(v for values in stats.times.values() for v in values) * 1000 if total else 0
    print(f"\n{total} requests in {seconds:.0f}s = {total / seconds:.1f} requests/second, "
          f"mean {mean:.0f} ms, error rate {rate:.2%}, slowest p95 {worst_p95:.0f} ms")
    for name, message in stats.first_error.items():
        print(f"  first error on {name}: {message}")
    ok = rate <= max_error_rate and worst_p95 <= max_p95_ms and total > 0
    print("RESULT: " + ("within limits" if ok else f"OVER LIMITS (p95 limit {max_p95_ms:.0f} ms, error limit {max_error_rate:.1%})"))
    return ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="site address, e.g. https://study.myschool.org or http://localhost:8000")
    parser.add_argument("--users", type=int, default=10, help="students active at the same time (default 10)")
    parser.add_argument("--seconds", type=int, default=30, help="how long to run (default 30)")
    parser.add_argument("--accounts", type=int, default=3, help="test accounts to create, 1-8 (default 3)")
    parser.add_argument("--email-domain", default="example.org",
                        help="domain for the test accounts' addresses (default example.org). Sign-up sends each "
                             "a verification email, which will bounce; with a real mail provider keep --accounts small")
    parser.add_argument("--max-p95-ms", type=float, default=1500, help="fail if any request type is slower (default 1500)")
    parser.add_argument("--max-error-rate", type=float, default=0.01, help="fail above this share of errors (default 0.01)")
    args = parser.parse_args()
    if not 1 <= args.accounts <= 8 or args.users < 1 or args.seconds < 1:
        parser.error("--accounts must be 1-8, --users and --seconds at least 1")

    base = args.url.rstrip("/")
    print(f"Creating {args.accounts} test account(s) on {base} ...")
    cookie_name, sessions = await make_accounts(base, args.accounts, args.email_domain)
    print(f"Running {args.users} students for {args.seconds}s ...")
    stats = Stats()
    started = time.monotonic()
    deadline = started + args.seconds
    await asyncio.gather(
        *(student(base, sessions[i % len(sessions)], cookie_name, deadline, stats) for i in range(args.users))
    )
    ok = report(stats, time.monotonic() - started, args.max_p95_ms, args.max_error_rate)
    print("Remember to disable the loadtest-*@example.org accounts (search \"loadtest-\") on the Admin page.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
