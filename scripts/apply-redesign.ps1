<#
  Applies the MindNest AI redesign after the update archive has been extracted over the project.

  Run from the project root in PowerShell:
      .\scripts\apply-redesign.ps1            # tidy files, refresh the web lockfile, rebuild and start the stack
      .\scripts\apply-redesign.ps1 -Checks    # the same, then lint, type-check and run the tests

  It never deletes anything: files the redesign replaced are moved into _to_delete\ so you can
  remove that folder yourself once you are happy.
#>
param([switch]$Checks)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "1/4  Moving replaced files into _to_delete\ ..." -ForegroundColor Cyan
$stale = @(
  "apps\web\src\components\chat-view.tsx",
  "apps\web\src\components\dashboard-view.tsx",
  "apps\web\src\components\quiz-trend-chart.tsx",
  "apps\web\src\components\study-chart.tsx",
  "apps\web\src\components\kit\stat.tsx",
  "apps\web\src\components\assignment-detail-view.tsx",
  "apps\web\src\components\quiz-attempt-view.tsx",
  "apps\web\package-lock.json"
)
foreach ($file in $stale) {
  if (Test-Path $file) {
    $target = Join-Path "_to_delete" $file
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Move-Item -Force $file $target
    Write-Host "     moved $file"
  }
}

Write-Host "2/4  Refreshing the web lockfile (new packages: fonts, KaTeX, Recharts, dnd-kit) ..." -ForegroundColor Cyan
Push-Location apps\web
try {
  if (Get-Command pnpm -ErrorAction SilentlyContinue) { pnpm install --lockfile-only }
  elseif (Get-Command corepack -ErrorAction SilentlyContinue) { corepack pnpm install --lockfile-only }
  else { Write-Host "     pnpm not found on the host; skipping (the Docker build installs packages itself)." -ForegroundColor Yellow }
} finally { Pop-Location }

Write-Host "3/4  Rebuilding and starting the stack (this applies migrations 0015-0017) ..." -ForegroundColor Cyan
docker compose up -d --build
docker compose ps

if ($Checks) {
  Write-Host "4/4  Checks ..." -ForegroundColor Cyan
  ruff check .
  mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
  pytest
  python scripts/export_openapi.py --check
  Push-Location apps\web
  try { pnpm typecheck; pnpm build } finally { Pop-Location }
} else {
  Write-Host "4/4  Skipped checks (add -Checks to run ruff, mypy, pytest and the web type-check/build)." -ForegroundColor Cyan
}
Write-Host "Done. Open http://localhost:3000" -ForegroundColor Green
