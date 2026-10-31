<#
  Glass step G7: Assignments: hub cards, writing workspace, rubric scores.

    Hub        the 'due next' cards are glass with a lit edge and pointer glow.
    Workspace  a glass hero header with a setup ring, the draft in serif type on a glass panel, the drop
               overlay is a blurred glass sheet, the help / rubric aside is a sticky glass panel.
    Feedback   rubric scores show an overall ring and a meter per criterion. Needs G5 (ring) applied first.

  Run from the project root in PowerShell, after G1, the G1 fix and G2-G4 are applied, G5 and G6:
      .\scripts\apply-glass-g7.ps1

  Web only: no migration, no Python change, nothing deleted, no new translation keys. The web image is
  rebuilt, and the build type-checks the app.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (type-checks too) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/assignments." -ForegroundColor Green
