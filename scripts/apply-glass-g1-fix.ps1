<#
  Glass step G1 fix: three things seen in the first screenshots.

    Theme     the theme cookie was renamed, so a browser that had saved "light" or "system" earlier now
              opens in dark glass once. The Light / System / Dark buttons in the profile menu still work
              and the choice is remembered from then on.
    Menus     the profile, notification and course menus now paint above the cards under them (the top
              bar and sidebar form their own layer) and use a denser fill, so nothing shows through.
    Ask AI    a slimmer button, a little lower in the corner, so it covers less.

  Run from the project root in PowerShell, after G1 is applied:
      .\scripts\apply-glass-g1-fix.ps1

  Web only: no migration, no Python change, nothing deleted.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (type-checks too) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Hard-refresh http://localhost:3000/dashboard (Ctrl+Shift+R): dark glass, menus on top." -ForegroundColor Green
