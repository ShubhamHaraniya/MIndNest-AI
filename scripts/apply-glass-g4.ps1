<#
  Glass step G4: Chat: a three-panel glass workspace.

    Panes     history | conversation | source inspector, three floating glass panels with a gap between them.
              The inspector slides in when you open a citation and keeps its passage / document tabs.
    Answers   each answer is a glass card with its steps on top; citations are chips under it; the newest
              answer glows while it is written. Starter questions enter one after another.
    Composer  a dense glass dock with a lit edge while you type. Attachments, scope and model are unchanged.
    Fix       the page transition now keeps the chat page full height.

  Run from the project root in PowerShell, after G1 and the G1 fix are applied, G2 and G3:
      .\scripts\apply-glass-g4.ps1

  Web only: no migration, no Python change, nothing deleted, no new translation keys. The web image is
  rebuilt, and the build type-checks the app.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (type-checks too) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/chat." -ForegroundColor Green
