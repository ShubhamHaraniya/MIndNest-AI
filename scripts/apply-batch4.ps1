<#
  Applies update batch 4 (Study Planner, Calendar and Study Groups) after the archive has been
  extracted over the project.

    Study Planner  Today, Week, Month, Timeline and Tasks views; add, edit, cancel and restore tasks;
                   overload warnings with a suggested day; regenerating keeps your own tasks, finished
                   or cancelled tasks and tasks you moved.
    Calendar       Day, Week, Month and Agenda views; add your own events; sync states (synced,
                   waiting, failed) with retry; no duplicate events on Google Calendar.
    Study Groups   admin role, invitations by email, shared notes, discussions, study sessions with
                   RSVP, and adding a session to your own calendar.

  Run from the project root in PowerShell:
      .\scripts\apply-batch4.ps1            # export the API contract, rebuild and start the stack, migrate
      .\scripts\apply-batch4.ps1 -Checks    # the same, then lint, type-check and run the batch 4 tests

  Nothing is deleted and no file is replaced by a different one, so nothing moves to _to_delete\.
  New database migrations: 0021 (planner states), 0022 (calendar events and sync failures),
  0023 (group collaboration). The api, worker and calendar-mcp images are rebuilt too.
#>
param([switch]$Checks)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/3  Writing the API contract (packages\contracts\openapi.json) ..." -ForegroundColor Cyan
python scripts/export_openapi.py

Write-Host "2/3  Rebuilding and starting the stack (the build type-checks the web app) ..." -ForegroundColor Cyan
docker compose up -d --build
Write-Host "     Applying database migrations 0021, 0022 and 0023 ..."
docker compose run --rm migrate
docker compose ps

if ($Checks) {
  Write-Host "3/3  Python checks ..." -ForegroundColor Cyan
  ruff check .
  mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
  pytest `
    libs/core/tests/test_plannerlogic.py libs/core/tests/test_calsync.py libs/core/tests/test_calevent.py `
    libs/core/tests/test_grouplogic.py libs/core/tests/test_group_rls.py libs/core/tests/test_i18n_catalogs.py `
    services/api/tests/test_planner.py services/api/tests/test_calendar_events.py `
    services/api/tests/test_calendar_workspace.py services/api/tests/test_gcal.py `
    services/api/tests/test_calendar_server.py services/api/tests/test_groups.py `
    services/api/tests/test_group_collab.py
  python scripts/export_openapi.py --check
} else {
  Write-Host "3/3  Skipped Python checks (add -Checks)." -ForegroundColor Cyan
}
Write-Host "Done. Open http://localhost:3000/planner, /calendar and /library (then open a group)." -ForegroundColor Green
