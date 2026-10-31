# Contributing to MindNest AI

Thanks for helping. This guide gets you from a fresh clone to a pull request.

## Set up

Follow **Quick start** in the [README](README.md). For code changes you also need:

```bash
pip install -e ".[dev]"           # ruff, mypy, pytest (Python 3.12)
cp .env.example .env              # development defaults only
docker compose up -d postgres redis   # enough for most tests
alembic upgrade head              # the API tests need a migrated database
```

Windows users can run everything with PowerShell; `scripts/check.ps1` bundles the checks below and `scripts/run-evals.ps1` runs the evaluations.

## Before you open a pull request

```bash
ruff check .
mypy -p mindnest_core -p mindnest_agents -p mindnest_api -p mindnest_worker -p mindnest_models
pytest
python scripts/export_openapi.py --check
pnpm --filter @mindnest/web typecheck && pnpm --filter @mindnest/web build
```

CI runs exactly these. Tests that need the database skip themselves when it is not reachable, so
make sure it is running if you changed anything that touches data.

## Where things go

| If you are changing... | Put it in |
| --- | --- |
| A rule that needs no database or network (scoring, scheduling, validation) | `libs/core/mindnest_core/` as a pure function, with a unit test next to it |
| An HTTP endpoint | `services/api/mindnest_api/routes/`, then regenerate the contract: `python scripts/export_openapi.py` |
| Background work | `services/worker/mindnest_worker/` |
| A new agent | one module in `services/api/mindnest_api/agent/agents/` plus a `register(AgentSpec(...))` call |
| Interface text | `apps/web/src/i18n/messages/en.json` first (it is the source of truth); `hi.json` and `gu.json` fall back to English until translated |
| A table or column | a **new** Alembic migration in `infra/migrations/versions/` (never edit an applied one) |

## Rules that protect students

1. **Every student-owned table needs row-level security.** In the migration that creates it:
   `ENABLE ROW LEVEL SECURITY` and a policy keyed to `app_current_user_id()` (or `EXISTS` through
   its parent). Add an isolation test in the style of `libs/core/tests/test_rls.py`.
2. **Every route requires sign-in** unless it is deliberately public. `test_protected_routes.py`
   will fail otherwise.
3. **Run queries through `user_session`** so row-level security applies. Never connect as the owner role.
4. **Treat text from documents, tool results and models as untrusted.** Do not interpolate it into
   prompts without the helpers in `mindnest_core.aisafety`.
5. **Never log or store provider keys, tokens or message text.** Use `redact` for anything that
   might contain a secret. Safety events record kinds and counts only.
6. **A tool that changes something outside MindNest must use `approval=True`.**
7. **No secrets in Git.** `.env` files are ignored; use the `*.example` templates.

## Style

* Python: ruff (rules E, F, B, UP; line length 100), type hints everywhere, small pure functions.
* TypeScript: strict mode; no `any`; strings via `t("key")`, never hard-coded.
* Commit messages: a short imperative summary line; explain *why* in the body when it is not obvious.
* Keep pull requests focused. A bug fix needs a test that fails without it.

## Documentation

If you change behaviour, update the docs in the same pull request: [DOC.md](DOC.md) describes how
the code works, [docs/security.md](docs/security.md) the safety model, the runbooks the operations.
Docs describe the code as it is; if you are unsure, read the code.

## Reporting security problems

Please do not open a public issue. Contact the maintainer privately (GitHub profile) with the details.
