<#
  Glass step G2: landing, sign-in and onboarding.

    Landing   a floating glass bar, a headline with a gradient, three layers of glass that tilt toward the
              pointer, a bento grid of features, a line that draws itself through the three steps, and a
              closing panel. Orbs drift at their own speed as you scroll.
    Sign-in   a split screen: orbit rings and benefit chips on the left, one dense glass card on the right.
              The same layout serves sign-up, forgot / reset password and verify e-mail.
    Setup     the five onboarding steps sit on a glowing rail that fills as you go; each step slides in.

  Run from the project root in PowerShell, after G1 and the G1 fix are applied:
      .\scripts\apply-glass-g2.ps1

  Web only: no migration, no Python change, nothing deleted, no new translation keys. The web image is
  rebuilt, and the build type-checks the app.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (type-checks too) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/ (signed out), then /login and /onboarding." -ForegroundColor Green
