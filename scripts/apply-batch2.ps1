<#
  Applies update batch 2 (quiz lifecycle and archive, one "cards due" rule, dashboard states and
  getting-started checklist) after the archive has been extracted over the project.

  Run from the project root in PowerShell:
      .\scripts\apply-batch2.ps1            # export the API contract, rebuild and start the stack, migrate
      .\scripts\apply-batch2.ps1 -Checks    # the same, then lint, type-check and run the tests

  Nothing is deleted and no file is replaced by a different one, so nothing moves to _to_delete\.
  New database migration: 0019 (adds quizzes.archived_at).
#>
param([switch]$Checks)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/3  Writing the API contract (packages\contracts\openapi.json) ..." -ForegroundColor Cyan
python scripts/export_openapi.py

Write-Host "2/3  Rebuilding and starting the stack (the build type-checks the web app) ..." -ForegroundColor Cyan
docker compose up -d --build
Write-Host "     Applying database migration 0019 (quiz archive) ..."
docker compose run --rm migrate
docker compose ps

if ($Checks) {
  Write-Host "3/3  Python checks ..." -ForegroundColor Cyan
  ruff check .
  mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
  pytest libs/core/tests/test_dashlogic.py libs/core/tests/test_taskstate.py libs/core/tests/test_quiz_lifecycle_logic.py libs/core/tests/test_quizlogic.py libs/core/tests/test_i18n_catalogs.py services/api/tests/test_quiz_lifecycle.py services/api/tests/test_quizzes.py services/api/tests/test_quiz_exam.py
  Write-Host "     Full test suite ..."
  pytest
  python scripts/export_openapi.py --check
} else {
  Write-Host "3/3  Skipped Python checks (add -Checks)." -ForegroundColor Cyan
}
Write-Host "Done. Open http://localhost:3000/quizzes and http://localhost:3000/dashboard." -ForegroundColor Green
