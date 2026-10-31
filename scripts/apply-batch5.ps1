<#
  Applies update batch 5 (Evaluation Lab, Help and language, Settings security, polish and tests)
  after the archive has been extracted over the project.

    Evaluation Lab  Runs, Datasets, Compare and Scores-glossary tabs; import a question set; start a run
                    from a dataset; run and dataset pages with filters, downloads and plain-language
                    explanations of every score.
    Help            a "Help" link on each main page that opens the matching section of the guide; the
                    guide has search, and new sections for Library, Evaluation and Settings (en, hi, gu).
    Language        dates and times follow the chosen language everywhere; 16 more error messages are
                    translated.
    Settings        a new Security tab: change password (signs out other devices), see where you are
                    signed in, sign out other devices, download your data.
    Polish          shared table and empty-state components on the Admin and Library screens.
    Tests           every API error code must have a translation; provider keys, password hashes and
                    session tokens must never appear in a response or a log.

  Run from the project root in PowerShell:
      .\scripts\apply-batch5.ps1            # export the API contract, rebuild and start the stack
      .\scripts\apply-batch5.ps1 -Checks    # the same, then lint, type-check and run the batch 5 tests
      .\scripts\apply-batch5.ps1 -Full      # -Checks, then the WHOLE test suite (takes a while)

  No database migration. Nothing is deleted. The api and web images are rebuilt.
#>
param([switch]$Checks, [switch]$Full)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/3  Writing the API contract (packages\contracts\openapi.json) ..." -ForegroundColor Cyan
python scripts/export_openapi.py

Write-Host "2/3  Rebuilding and starting the stack (the build type-checks the web app) ..." -ForegroundColor Cyan
docker compose up -d --build api web
docker compose ps

if ($Checks -or $Full) {
  Write-Host "3/3  Python checks ..." -ForegroundColor Cyan
  ruff check .
  mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
  python scripts/build_guide_docs.py --check
  pytest `
    services/api/tests/test_account.py services/api/tests/test_error_codes_mapped.py `
    services/api/tests/test_secret_hygiene.py services/api/tests/test_protected_routes.py `
    services/api/tests/test_me.py services/api/tests/test_providers.py services/api/tests/test_security.py `
    services/api/tests/test_evaluation.py libs/core/tests/test_guide_content.py libs/core/tests/test_i18n_catalogs.py
  python scripts/export_openapi.py --check
} else {
  Write-Host "3/3  Skipped Python checks (add -Checks)." -ForegroundColor Cyan
}

if ($Full) {
  Write-Host "Running the whole test suite ..." -ForegroundColor Cyan
  pytest
}
Write-Host "Done. Open http://localhost:3000/eval, /guide and /settings?tab=security." -ForegroundColor Green
