<#
  Applies update batch 3, part 3 (Assignment Helper: drag-and-drop upload on the assignment page and
  on the new-assignment form, and the tabs Overview, Files, Instructions, Rubric, AI assistance,
  Draft feedback, History) after the archive has been extracted over the project.

  Run from the project root in PowerShell:
      .\scripts\apply-batch3c.ps1

  Web only: no database migration and no Python change, so only the web image is rebuilt (the build
  type-checks the app). Nothing is deleted.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (the build type-checks it) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/assignments, drop a file on the form, then open the assignment." -ForegroundColor Green
