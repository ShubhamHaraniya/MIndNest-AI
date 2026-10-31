<#
  Applies redesign step R1 "Focus Studio": the new look for the whole app plus the new navigation.

    Look        cool soft-grey surfaces, one blue accent, rounded cards and controls, quiet shadows,
                Inter for all text (the serif headings are gone). Light and dark themes.
    Navigation  five hubs in the sidebar: Home, Study (courses, chat, quizzes), Plan (planner, calendar,
                assignments), Community (materials library, study groups) and Lab (evaluation).
                Settings, Help and Admin are in the profile menu. Each hub's pages also show as a tab
                strip under the top bar. The phone tab bar follows the hubs.

  Run from the project root in PowerShell:
      .\scripts\apply-redesign-r1.ps1

  Web only: no database migration and no Python change, so only the web image is rebuilt (the build
  type-checks the app). Nothing is deleted.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (the build type-checks it) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/dashboard (try the light and dark theme, then the Plan and Study tabs)." -ForegroundColor Green
