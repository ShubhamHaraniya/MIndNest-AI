<#
  Applies glass step G1 "Dark Liquid Glass": the foundation.

    Look      midnight/obsidian canvas with a slow aurora, translucent blurred panels with a lit edge,
              emerald as the action colour and a muted cyan second accent, an editorial serif for
              headings. DARK is the default for everyone; the Light option in the profile menu (or the
              theme buttons) switches to a daylight variant of the same design.
    Motion    the `motion` package (Framer Motion) is added to package.json. Page changes fade and lift,
              the sidebar and hub tabs have a lit highlight that slides, the glow follows the pointer on
              cards, reveals/stagger/parallax/count-up helpers are ready for the next steps.
              Everything respects the system "reduce motion" setting.
    Shell     a floating glass sidebar, a floating glass top bar, a floating bottom bar on phones,
              glass menus, dialogs, toasts and the Ask AI drawer.

  Run from the project root in PowerShell:
      .\scripts\apply-glass-g1.ps1

  Web only: no migration and no Python change. The web image is rebuilt (it installs `motion`, then the
  build type-checks the app). Nothing is deleted. Redesign R1-R5 (Focus Studio) must already be applied.
  Do NOT commit a package-lock.json. If the Docker build complains that the lockfile is out of date,
  run `pnpm install` once inside apps\web and re-run this script.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/2  Adding the new package (motion) to the web lockfile ..." -ForegroundColor Cyan
Push-Location apps\web
try {
  if (Get-Command pnpm -ErrorAction SilentlyContinue) { pnpm install --lockfile-only }
  elseif (Get-Command corepack -ErrorAction SilentlyContinue) { corepack pnpm install --lockfile-only }
  else { Write-Host "     pnpm not found on the host; skipping (the Docker build installs packages itself)." -ForegroundColor Yellow }
} finally { Pop-Location }

Write-Host "2/2  Rebuilding the web app (installs motion, then type-checks) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/dashboard - the whole app is dark glass now." -ForegroundColor Green
