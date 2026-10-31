<#
  Glass step G3: Dashboard command center.

    Layout    a different composition from every other page: a greeting row, then a large progress ring with
              the next step beside today's timeline, a row of count-up figures, three analytics panels
              (study-time bars, quiz-score line, countdown rail of deadlines), the course dock, the week
              ahead, a shelf of recent documents, and the right-hand column of assignments, weak topics
              and activity.
    Charts    the ring, bars and line draw themselves once, when first seen. Every chart keeps a text label.
    Timeline  ticking a task still saves to the planner straight away (and reverts if the server refuses).

  Run from the project root in PowerShell, after G1 and the G1 fix are applied and G2:
      .\scripts\apply-glass-g3.ps1

  Web only: no migration, no Python change, nothing deleted, no new translation keys. The web image is
  rebuilt, and the build type-checks the app.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (type-checks too) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/dashboard." -ForegroundColor Green
