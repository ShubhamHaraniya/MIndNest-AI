<#
  Applies redesign step R2 "Focus Studio": Home and the Study hub.

    Home    a clear "next step" card chosen from your real data (finish setup, today's first task,
            cards due, an assignment due soon, or ask a question) with four small figures:
            day streak, tasks done today, cards due and quiz average.
    Study   My Subjects is a grid of course cards (readable files, quiz average, next exam, quick
            actions) with a Cards / Table switch that remembers your choice; the course page header
            is a card with a fact tile row.

  Run from the project root in PowerShell:
      .\scripts\apply-redesign-r2.ps1

  Web only: no migration and no Python change; only the web image is rebuilt (the build type-checks
  the app). Nothing is deleted. Apply redesign R1 first.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (the build type-checks it) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/dashboard and /subjects." -ForegroundColor Green
