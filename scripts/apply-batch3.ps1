<#
  Applies update batch 3, part 1 (Chat: search inside conversations, grouping, attached files, what the
  chat may search, write an answer again, thumbs up/down, follow-up questions and options, drawn
  diagrams) after the archive has been extracted over the project.

  Run from the project root in PowerShell:
      .\scripts\apply-batch3.ps1            # export the API contract, rebuild and start the stack, migrate
      .\scripts\apply-batch3.ps1 -Checks    # the same, then lint, type-check and run the chat tests

  Nothing is deleted and no file is replaced by a different one, so nothing moves to _to_delete\.
  New database migration: 0020 (conversation scope, attached files, answer feedback, rewritten answers).
  The worker needs the rebuild too: it now reads attached files.
#>
param([switch]$Checks)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/3  Writing the API contract (packages\contracts\openapi.json) ..." -ForegroundColor Cyan
python scripts/export_openapi.py

Write-Host "2/3  Rebuilding and starting the stack (the build type-checks the web app) ..." -ForegroundColor Cyan
docker compose up -d --build
Write-Host "     Applying database migration 0020 (chat features) ..."
docker compose run --rm migrate
docker compose ps

if ($Checks) {
  Write-Host "3/3  Python checks ..." -ForegroundColor Cyan
  ruff check .
  mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
  pytest libs/core/tests/test_chatlogic.py libs/core/tests/test_i18n_catalogs.py services/api/tests/test_chat_extras.py services/api/tests/test_chat.py services/api/tests/test_agent_chat.py services/api/tests/test_guardrails_chat.py
  python scripts/export_openapi.py --check
} else {
  Write-Host "3/3  Skipped Python checks (add -Checks)." -ForegroundColor Cyan
}
Write-Host "Done. Open http://localhost:3000/chat. Attached files are read by the worker; the first scanned page can take a few seconds." -ForegroundColor Green
