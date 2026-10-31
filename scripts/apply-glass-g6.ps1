<#
  Glass step G6: Quiz: quiz hub, immersive glass exam, results.

    Exam     a focused glass exam: countdown ring in the header, a lit question card, an answer
             navigator with glow on the current question, a docked footer.
    Results  a large score ring, per-topic meters, and review rows with a verdict bar.
    Hub      resume card and revision box restyled. Needs G5 (ring, tabs) and G3 (meter) applied first.

  Run from the project root in PowerShell, after G1, the G1 fix and G2-G4 are applied, and G5:
      .\scripts\apply-glass-g6.ps1

  Web only: no migration, no Python change, nothing deleted, no new translation keys. The web image is
  rebuilt, and the build type-checks the app.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (type-checks too) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/quizzes." -ForegroundColor Green
