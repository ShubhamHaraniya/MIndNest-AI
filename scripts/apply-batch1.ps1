<#
  Applies update batch 1 (navigation, Materials Library, institution, Settings split) after the
  archive has been extracted over the project.

  Run from the project root in PowerShell:
      .\scripts\apply-batch1.ps1            # export the API contract, rebuild and start the stack, migrate
      .\scripts\apply-batch1.ps1 -Checks    # the same, then lint, type-check and run the tests

  Nothing is deleted. This batch replaces no files, so there is nothing to move into _to_delete\.

  One manual step: the local model service runs on your laptop, not in Docker. Stop it and start it
  again so Settings > Local retrieval models can read its new /status report:
      uvicorn mindnest_models.main:app --port 8100
#>
param([switch]$Checks)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/4  Writing the API contract (packages\contracts\openapi.json) ..." -ForegroundColor Cyan
python scripts/export_openapi.py

Write-Host "2/4  Rebuilding and starting the stack ..." -ForegroundColor Cyan
docker compose up -d --build
Write-Host "     Applying database migration 0018 (Materials Library, institution) ..."
docker compose run --rm migrate
docker compose ps

if ($Checks) {
  Write-Host "3/4  Python checks ..." -ForegroundColor Cyan
  ruff check .
  mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
  pytest services/api/tests/test_library.py services/api/tests/test_model_status.py services/api/tests/test_me.py libs/core/tests/test_librarylogic.py services/models/tests
  Write-Host "     Full test suite ..."
  pytest
  python scripts/export_openapi.py --check
  Write-Host "4/4  Web: the Docker build above already type-checks and builds the site; no host install needed." -ForegroundColor Cyan
} else {
  Write-Host "3/4  Skipped Python checks (add -Checks)." -ForegroundColor Cyan
  Write-Host "4/4  Skipped web checks (add -Checks)." -ForegroundColor Cyan
}
Write-Host "Done. Open http://localhost:3000/materials (restart the model service first, see the note at the top of this script)." -ForegroundColor Green
