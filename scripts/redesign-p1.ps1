# Redesign phase 1: rebuild, migrate, test. Run from the project root:
#   powershell -ExecutionPolicy Bypass -File scripts\redesign-p1.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# A stray lockfile would pin old packages in the web image build.
if (Test-Path apps\web\package-lock.json) { Remove-Item apps\web\package-lock.json }

Write-Host "== 1/4 Rebuild and start (runs migration 0014 through the migrate service) ==" -ForegroundColor Cyan
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw "docker compose failed" }

Write-Host "== 2/4 Migration status ==" -ForegroundColor Cyan
docker compose logs migrate --tail 5
docker compose run --rm migrate alembic current

Write-Host "== 3/4 pytest, ruff, mypy, openapi check ==" -ForegroundColor Cyan
pytest -q
if ($LASTEXITCODE -ne 0) { Write-Host "pytest failed" -ForegroundColor Red }
ruff check .
mypy -p mindnest_core -p mindnest_api -p mindnest_worker -p mindnest_models
python scripts\export_openapi.py --check
if ($LASTEXITCODE -ne 0) {
  Write-Host "openapi.json out of date, regenerating" -ForegroundColor Yellow
  python scripts\export_openapi.py
}

Write-Host "== 4/4 Web ==" -ForegroundColor Cyan
docker compose ps web
Write-Host "Open http://localhost:3000 and press Ctrl+K on the dashboard." -ForegroundColor Green
