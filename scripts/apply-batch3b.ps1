<#
  Applies update batch 3, part 2 (My Subjects: Modules, Assignments and Analytics tabs, "recommended
  next", rename or merge a module) after the archive has been extracted over the project.

  Run from the project root in PowerShell:
      .\scripts\apply-batch3b.ps1            # export the API contract, rebuild and start the stack
      .\scripts\apply-batch3b.ps1 -Checks    # the same, then lint, type-check and run the course tests

  No database migration. Nothing is deleted.
#>
param([switch]$Checks)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/3  Writing the API contract (packages\contracts\openapi.json) ..." -ForegroundColor Cyan
python scripts/export_openapi.py

Write-Host "2/3  Rebuilding and starting the stack (the build type-checks the web app) ..." -ForegroundColor Cyan
docker compose up -d --build
docker compose ps

if ($Checks) {
  Write-Host "3/3  Python checks ..." -ForegroundColor Cyan
  ruff check .
  mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
  pytest libs/core/tests/test_subjectlogic.py libs/core/tests/test_i18n_catalogs.py services/api/tests/test_course_tabs.py services/api/tests/test_subjects.py services/api/tests/test_courses.py
  python scripts/export_openapi.py --check
} else {
  Write-Host "3/3  Skipped Python checks (add -Checks)." -ForegroundColor Cyan
}
Write-Host "Done. Open a course at http://localhost:3000/subjects and look at the Modules, Assignments and Analytics tabs." -ForegroundColor Green
