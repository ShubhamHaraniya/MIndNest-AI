<#
  Runs the same checks as CI, in one go, and tells you which ones failed.

    .\scripts\check.ps1            Python side: ruff, mypy, pytest, OpenAPI contract
    .\scripts\check.ps1 -Web       also type-check and build the web app (needs Node 22 and pnpm)
    .\scripts\check.ps1 -SkipTests only the quick static checks

  One-time setup:   pip install -e ".[dev]"      (and copy .env.example to .env)
  The API tests need the stack's database:  docker compose up -d postgres redis
  (tests that need it skip themselves when it is not reachable).

  This script only reads and tests. It changes no files.
#>
[CmdletBinding()]
param(
  [switch]$Web,
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$script:failed = @()

function Invoke-Step([string]$Name, [scriptblock]$Command) {
  Write-Host ""
  Write-Host "== $Name" -ForegroundColor Cyan
  $global:LASTEXITCODE = 0
  try {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
    Write-Host "   ok" -ForegroundColor Green
  } catch {
    $script:failed += $Name
    Write-Host "   FAILED: $($_.Exception.Message)" -ForegroundColor Red
  }
}

Invoke-Step "ruff (lint)" { ruff check . }
Invoke-Step "mypy (types)" { mypy -p mindnest_core -p mindnest_agents -p mindnest_api -p mindnest_worker -p mindnest_models }
Invoke-Step "OpenAPI contract is up to date" { python scripts/export_openapi.py --check }
if (-not $SkipTests) {
  Invoke-Step "pytest" { pytest -q }
}
if ($Web) {
  Push-Location "apps/web"
  try {
    Invoke-Step "web: type check" { pnpm typecheck }
    Invoke-Step "web: build" { pnpm build }
  } finally {
    Pop-Location
  }
}

Write-Host ""
if ($script:failed.Count -eq 0) {
  Write-Host "All checks passed." -ForegroundColor Green
} else {
  Write-Host ("Failed: " + ($script:failed -join ", ")) -ForegroundColor Red
  exit 1
}
