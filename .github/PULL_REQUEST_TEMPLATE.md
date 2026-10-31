## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## How it was checked

- [ ] `ruff check .` and `mypy` are clean
- [ ] `pytest` passes (new behaviour has a test)
- [ ] If an API route or response changed: `python scripts/export_openapi.py` was run and `packages/contracts/openapi.json` is committed
- [ ] If the interface changed: `pnpm --filter @mindnest/web typecheck` passes, and strings exist in all three catalogs (en, hi, gu)
- [ ] If a table changed: a new Alembic migration (never edit an old one), with row-level security for student data

## Notes for the reviewer

<!-- Anything surprising, trade-offs, follow-ups. -->
