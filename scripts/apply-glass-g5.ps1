<#
  Glass step G5: Subjects: course shelf, topic map, syllabus ribbon, document shelf.

    Subjects   course cards on glass; the page header and course header lift into glass.
    Modules    a topic map above the module table: modules as connected nodes you can open.
    Overview   a syllabus ribbon (module progress along one line) above the module table.
    Documents  table or shelf layout (toggle); the shelf shows documents as cards with their progress.
    Shared     a glass tab strip with a sliding highlight (used on every tabbed page) and a self-drawing
               progress ring (components/motion/ring.tsx, also used by G6 and G7).

  Run from the project root in PowerShell, after G1, the G1 fix and G2-G4 are applied:
      .\scripts\apply-glass-g5.ps1

  Web only: no migration, no Python change, nothing deleted, no new translation keys. The web image is
  rebuilt, and the build type-checks the app.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (type-checks too) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/subjects." -ForegroundColor Green
