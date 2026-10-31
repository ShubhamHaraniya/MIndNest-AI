<#
  Applies redesign step R4 "Focus Studio": the Plan and Community hubs.

    Planner      a "Focus now" card on top (the one task to do, with Mark done / Open, and today's
                 progress ring), four figures beside it (today, time left, overdue, next exam),
                 round tick boxes, softer day cards.
    Calendar     one toolbar card (previous / next / title / Today, view switch, Add event), a colour
                 key with dots, events as chips with a coloured edge, today highlighted, and a slim
                 green line when there are no conflicts.
    Assignments  "Due next": the three nearest deadlines as cards above the list; the assignment
                 page opens with a card that shows how much of the setup is done as a ring.
    Study groups group cards with a coloured initial and the whole card opens the group; the group page
                 has a header card with the role badge.
    Materials    header card, filters in a card, a file icon on every row.

  Run from the project root in PowerShell:
      .\scripts\apply-redesign-r4.ps1

  Web only: no migration and no Python change; only the web image is rebuilt (the build type-checks
  the app). Nothing is deleted. Apply redesign R1, R2 and R3 first.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (the build type-checks it) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/planner, /calendar, /assignments, /library and /materials." -ForegroundColor Green
