<#
  .SYNOPSIS
    Finds files that are not needed to run, test or publish MindNest AI, and (only if you ask) removes them.

  .DESCRIPTION
    DRY RUN BY DEFAULT. With no switches this script only LISTS things and changes nothing.

    What it looks at, in three groups:

      A  Regenerable caches and build output. Python and tool caches (__pycache__, .mypy_cache,
         .pytest_cache, .ruff_cache, .hypothesis, htmlcov), setuptools build/ and dist/ folders,
         coverage files, *.log and stray *.whl files in the project root, the Next.js build folder
         (apps\web\.next) and tsconfig.tsbuildinfo. Every one is recreated automatically the next time
         the tool that made it runs, and all of them are already in .gitignore.
         With -Apply these are DELETED.

      B  One-time delivery scripts (only with -IncludeDeliveryScripts). The apply-batch*, apply-glass-*,
         apply-redesign*, redesign-p1 and prune-stale-web scripts were used to deliver changes in
         steps. They are history, not part of the product. With -Apply they are MOVED (not deleted) to
         _to_delete\cleanup-<time>\ keeping their folder names, so you can put any of them back.
         They are skipped unless the glass redesign (steps G1 to G11) is already applied.

      C  Items to LOOK AT yourself. Listed, never touched: a package-lock.json that competes with
         pnpm-lock.yaml, the old _to_delete folder, mindnest.egg-info, generated evaluation reports,
         design notes that may be out of date.

    It also runs a READ-ONLY scan of the files Git would publish for things shaped like real secrets
    (API keys, private keys). Only the file, line and kind are printed, never the secret itself.

    NEVER touched, whatever the switches: .env files, source code, tests, migrations, lock files,
    docs, evals datasets and corpus, node_modules, .git, .venv.

  .PARAMETER Apply
    Actually delete group A and move group B. Without it nothing changes.

  .PARAMETER IncludeDeliveryScripts
    Also include group B.

  .PARAMETER Force
    Include group B even if the glass redesign does not look fully applied.

  .PARAMETER SkipSecretScan
    Skip the secret scan.

  .EXAMPLE
    .\scripts\clean-repo.ps1                                   # look, change nothing
    .\scripts\clean-repo.ps1 -Apply                            # delete caches only
    .\scripts\clean-repo.ps1 -Apply -IncludeDeliveryScripts    # also tidy the one-time scripts
#>
[CmdletBinding()]
param(
  [switch]$Apply,
  [switch]$IncludeDeliveryScripts,
  [switch]$Force,
  [switch]$SkipSecretScan
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path (Join-Path $Root "pyproject.toml")) -or -not (Test-Path (Join-Path $Root "apps/web/package.json"))) {
  throw "Run this from the MindNest AI project (the folder with pyproject.toml and apps/web). Found: $Root"
}

# ---------------------------------------------------------------- helpers

function Format-Size([long]$bytes) {
  if ($bytes -ge 1GB) { return ("{0:N2} GB" -f ($bytes / 1GB)) }
  if ($bytes -ge 1MB) { return ("{0:N1} MB" -f ($bytes / 1MB)) }
  if ($bytes -ge 1KB) { return ("{0:N0} KB" -f ($bytes / 1KB)) }
  return "$bytes B"
}

function Get-TreeSize([string]$path) {
  if (Test-Path -LiteralPath $path -PathType Leaf) { return (Get-Item -LiteralPath $path -Force).Length }
  $sum = 0L
  try {
    foreach ($f in [System.IO.Directory]::EnumerateFiles($path, "*", [System.IO.SearchOption]::AllDirectories)) {
      try { $sum += ([System.IO.FileInfo]$f).Length } catch { }
    }
  } catch { }
  return $sum
}

function Get-Rel([string]$path) {
  $full = [System.IO.Path]::GetFullPath($path)
  $base = [System.IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
  if ($full.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $full.Substring($base.Length).TrimStart('\', '/')
  }
  return $full
}

# Folders the walk never enters.
$Prune = @("node_modules", ".git", ".venv", "venv", "_to_delete", ".pnpm-store")
# Folder names that are caches wherever they appear.
$CacheNames = @("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis", "htmlcov")

function Find-CacheDirs([string]$dir, $found) {
  foreach ($d in [System.IO.Directory]::EnumerateDirectories($dir)) {
    $name = [System.IO.Path]::GetFileName($d)
    if ($Prune -contains $name) { continue }
    if ($CacheNames -contains $name) { [void]$found.Add($d); continue }
    Find-CacheDirs $d $found
  }
}

# ---------------------------------------------------------------- group A: caches and build output

$groupA = New-Object System.Collections.Generic.List[object]

function Add-A([string]$path, [string]$why) {
  if (Test-Path -LiteralPath $path) {
    $size = Get-TreeSize $path
    $groupA.Add([pscustomobject]@{ Path = $path; Rel = (Get-Rel $path); Size = $size; Why = $why })
  }
}

$cacheDirs = New-Object System.Collections.Generic.List[string]
Find-CacheDirs $Root $cacheDirs
foreach ($d in $cacheDirs) { Add-A $d "cache, recreated automatically" }

# setuptools output in the project root: only when it really looks like setuptools output.
$buildDir = Join-Path $Root "build"
if (Test-Path -LiteralPath $buildDir -PathType Container) {
  $kids = @(Get-ChildItem -LiteralPath $buildDir -Force | ForEach-Object { $_.Name })
  if (($kids | Where-Object { $_ -eq "lib" -or $_ -like "bdist*" -or $_ -like "temp*" }).Count -gt 0) {
    Add-A $buildDir "setuptools build output"
  }
}
$distDir = Join-Path $Root "dist"
if (Test-Path -LiteralPath $distDir -PathType Container) {
  $odd = @(Get-ChildItem -LiteralPath $distDir -Force | Where-Object { $_.Name -notlike "*.whl" -and $_.Name -notlike "*.tar.gz" })
  if ($odd.Count -eq 0) { Add-A $distDir "built packages" }
}

foreach ($pattern in @("*.whl", "*.log", ".coverage", "coverage.xml")) {
  foreach ($f in Get-ChildItem -LiteralPath $Root -Filter $pattern -File -Force -ErrorAction SilentlyContinue) {
    Add-A $f.FullName "generated file in the project root"
  }
}
Add-A (Join-Path $Root "apps/web/.next") "Next.js build output"
Add-A (Join-Path $Root "apps/web/tsconfig.tsbuildinfo") "TypeScript incremental build cache"

# An item inside another listed item (a __pycache__ inside build\) is covered by its parent.
$dedup = New-Object System.Collections.Generic.List[object]
foreach ($i in ($groupA | Sort-Object { $_.Path.Length })) {
  $inside = $false
  foreach ($k in $dedup) {
    if ($i.Path.StartsWith($k.Path + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) { $inside = $true; break }
  }
  if (-not $inside) { $dedup.Add($i) }
}
$groupA = $dedup

# ---------------------------------------------------------------- group B: one-time delivery scripts

$groupB = New-Object System.Collections.Generic.List[object]
$glassApplied = $false
$css = Join-Path $Root "apps/web/src/app/globals.css"
if (Test-Path -LiteralPath $css) {
  $glassApplied = [bool](Select-String -LiteralPath $css -Pattern "forced-colors" -Quiet)
}
$deliveryPatterns = @("apply-batch*.ps1", "apply-glass-*.ps1", "apply-redesign*.ps1", "redesign-p1.ps1", "prune-stale-web.ps1")
$scriptsDir = Join-Path $Root "scripts"
foreach ($pattern in $deliveryPatterns) {
  foreach ($f in Get-ChildItem -LiteralPath $scriptsDir -Filter $pattern -File -ErrorAction SilentlyContinue) {
    $groupB.Add([pscustomobject]@{ Path = $f.FullName; Rel = (Get-Rel $f.FullName); Size = $f.Length; Why = "one-time delivery script" })
  }
}

# ---------------------------------------------------------------- group C: look at these yourself

$groupC = New-Object System.Collections.Generic.List[object]
function Add-C([string]$rel, [string]$note) {
  $p = Join-Path $Root $rel
  if (Test-Path -LiteralPath $p) {
    $groupC.Add([pscustomobject]@{ Rel = $rel; Size = (Get-TreeSize $p); Note = $note })
  }
}
Add-C "apps/web/package-lock.json" "an npm lock file in a pnpm project (pnpm-lock.yaml is the real one); delete it if nothing uses npm"
Add-C "_to_delete" "older leftovers moved aside earlier; review, then delete the folder yourself"
Add-C "mindnest.egg-info" "created by 'pip install -e .'; safe to delete, 'pip install -e .' recreates it"
Add-C "apps/web/BRIEF.md" "the original design brief; keep it out of the public repo if it is private"
Add-C "apps/web/DESIGN.md" "design notes; check they match the current dark glass design"
Add-C "evals/reports" "evaluation reports are evidence of results; keep the ones you cite in the README (agents-offline-*, agents-live-*)"
Add-C "focus-studio-redesign.md" "a planning note in the project root"

# Web dependencies that are declared but never imported (found by searching apps\web\src).
$webPackage = Join-Path $Root "apps/web/package.json"
$webSrc = Join-Path $Root "apps/web/src"
if ((Test-Path -LiteralPath $webPackage) -and (Test-Path -LiteralPath $webSrc)) {
  $pkgText = Get-Content -LiteralPath $webPackage -Raw
  foreach ($dep in @("recharts", "@dnd-kit/core")) {
    if ($pkgText -match [regex]::Escape('"' + $dep + '"')) {
      $used = Get-ChildItem -LiteralPath $webSrc -Recurse -File -Include *.ts, *.tsx |
        Select-String -SimpleMatch -Pattern $dep -List | Select-Object -First 1
      if (-not $used) {
        $groupC.Add([pscustomobject]@{ Rel = "apps/web/package.json -> $dep"; Size = 0; Note = "listed as a dependency but nothing in apps\web\src imports it; remove with 'pnpm remove $dep' in apps\web if you agree" })
      }
    }
  }
}

# ---------------------------------------------------------------- report

Write-Host ""
$mode = "DRY RUN (nothing will be changed)"
if ($Apply) { $mode = "APPLY" }
Write-Host "MindNest AI cleanup: $mode" -ForegroundColor Cyan
Write-Host "Project: $Root"
Write-Host ""

$aTotal = 0L
foreach ($i in $groupA) { $aTotal += $i.Size }
Write-Host "A  Regenerable caches and build output ($($groupA.Count) items, $(Format-Size $aTotal))" -ForegroundColor Yellow
if ($groupA.Count -eq 0) { Write-Host "   nothing to clean" -ForegroundColor DarkGray }
$top = $groupA | Sort-Object Size -Descending | Select-Object -First 12
foreach ($i in $top) { Write-Host ("   {0,10}  {1}" -f (Format-Size $i.Size), $i.Rel) }
if ($groupA.Count -gt 12) { Write-Host "   ... and $($groupA.Count - 12) smaller items" -ForegroundColor DarkGray }

$useB = $IncludeDeliveryScripts.IsPresent
Write-Host ""
if ($IncludeDeliveryScripts) {
  $bTotal = 0L
  foreach ($i in $groupB) { $bTotal += $i.Size }
  Write-Host "B  One-time delivery scripts ($($groupB.Count) files, $(Format-Size $bTotal))" -ForegroundColor Yellow
  if (-not $glassApplied -and -not $Force) {
    Write-Host "   SKIPPED: the glass redesign does not look fully applied yet (globals.css has no forced-colors rules)." -ForegroundColor Red
    Write-Host "   Apply steps G1 to G11 first, check the site, then run this again. Use -Force to override." -ForegroundColor Red
    $useB = $false
  } else {
    foreach ($i in $groupB) { Write-Host "   $($i.Rel)" }
  }
} else {
  Write-Host "B  One-time delivery scripts: $($groupB.Count) found; not included (add -IncludeDeliveryScripts)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "C  For you to review (never touched by this script)" -ForegroundColor Yellow
if ($groupC.Count -eq 0) { Write-Host "   nothing" -ForegroundColor DarkGray }
foreach ($i in $groupC) { Write-Host ("   {0,10}  {1}" -f (Format-Size $i.Size), $i.Rel); Write-Host ("              {0}" -f $i.Note) -ForegroundColor DarkGray }

# ---------------------------------------------------------------- secret scan (read only)

if (-not $SkipSecretScan) {
  Write-Host ""
  Write-Host "Secret scan (read only: file, line and kind are shown, never the secret)" -ForegroundColor Yellow

  $patterns = [ordered]@{
    "Google API key"           = 'AIza[0-9A-Za-z_\-]{35}'
    "Google OAuth secret"      = 'GOCSPX-[0-9A-Za-z_\-]{20,}'
    "Anthropic key"            = 'sk-ant-[0-9A-Za-z_\-]{20,}'
    "OpenAI-style key"         = '(?<![A-Za-z0-9_])sk-(?:proj-)?(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{32,}'
    "Groq key"                 = 'gsk_[0-9A-Za-z]{30,}'
    "GitHub token"             = 'gh[pousr]_[0-9A-Za-z]{30,}'
    "AWS access key id"        = 'AKIA[0-9A-Z]{16}'
    "Slack token"              = 'xox[baprs]-[0-9A-Za-z\-]{10,}'
    "LangSmith key"            = 'lsv2_(pt|sk)_[0-9a-f]{20,}'
    "Private key block"        = '-----BEGIN ([A-Z]+ )?PRIVATE KEY-----'
  }

  # Which files would be published? Ask Git if possible, otherwise walk the tree.
  $files = New-Object System.Collections.Generic.List[string]
  $usedGit = $false
  if ((Test-Path -LiteralPath (Join-Path $Root ".git")) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    $listed = & git -C $Root ls-files --cached --others --exclude-standard 2>$null
    if ($LASTEXITCODE -eq 0 -and $listed) {
      foreach ($line in $listed) { $files.Add((Join-Path $Root $line)) }
      $usedGit = $true
    }
  }
  if (-not $usedGit) {
    Write-Host "   (no Git repository yet: scanning the tree and skipping ignored folders and .env files)" -ForegroundColor DarkGray
    $skipDirs = $Prune + $CacheNames + @(".next", "backups", "build", "dist", "mindnest.egg-info", "corpus")
    $stack = New-Object System.Collections.Generic.Stack[string]
    $stack.Push($Root)
    while ($stack.Count -gt 0) {
      $dir = $stack.Pop()
      foreach ($d in [System.IO.Directory]::EnumerateDirectories($dir)) {
        if ($skipDirs -notcontains [System.IO.Path]::GetFileName($d)) { $stack.Push($d) }
      }
      foreach ($f in [System.IO.Directory]::EnumerateFiles($dir)) {
        $n = [System.IO.Path]::GetFileName($f)
        if ($n -like ".env*" -and $n -notlike "*.example") { continue }
        $files.Add($f)
      }
    }
  }

  $binaryExt = @(".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".pdf", ".docx", ".pptx", ".woff", ".woff2",
                 ".ttf", ".gz", ".zip", ".tar", ".whl", ".pyc", ".dump", ".enc", ".lock")
  $hits = New-Object System.Collections.Generic.List[string]
  foreach ($f in $files) {
    if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { continue }
    $info = Get-Item -LiteralPath $f -Force
    if ($binaryExt -contains $info.Extension.ToLower() -or $info.Length -gt 2MB) { continue }
    if ($info.Name -eq "pnpm-lock.yaml" -or $info.Name -eq "package-lock.json") { continue }
    $lineNo = 0
    try { $lines = [System.IO.File]::ReadAllLines($f) } catch { continue }
    foreach ($line in $lines) {
      $lineNo++
      if ($line.Length -gt 2000) { continue }
      foreach ($kind in $patterns.Keys) {
        if ($line -cmatch $patterns[$kind]) {
          $hits.Add(("   {0}:{1}  looks like: {2}" -f (Get-Rel $f), $lineNo, $kind))
          break
        }
      }
    }
  }
  if ($hits.Count -eq 0) {
    Write-Host "   nothing that looks like a real secret" -ForegroundColor Green
  } else {
    foreach ($h in $hits) { Write-Host $h -ForegroundColor Red }
    Write-Host "   Test fixtures can look like keys. Check each one. A real key must be removed AND rotated" -ForegroundColor Red
    Write-Host "   (revoked at the provider and replaced), even if you delete it from Git history later." -ForegroundColor Red
  }
}

# ---------------------------------------------------------------- act

Write-Host ""
if (-not $Apply) {
  Write-Host "Nothing was changed. To clean up for real:" -ForegroundColor Cyan
  Write-Host "   .\scripts\clean-repo.ps1 -Apply" -ForegroundColor White
  Write-Host "   .\scripts\clean-repo.ps1 -Apply -IncludeDeliveryScripts   (also tidy the one-time scripts)" -ForegroundColor White
  return
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$removed = 0
$freed = 0L
foreach ($i in $groupA) {
  if (-not (Test-Path -LiteralPath $i.Path)) { continue }   # inside a folder already removed
  try {
    Remove-Item -LiteralPath $i.Path -Recurse -Force
    $removed++
    $freed += $i.Size
  } catch {
    Write-Host "   could not remove $($i.Rel): $($_.Exception.Message)" -ForegroundColor Yellow
  }
}
Write-Host "Deleted $removed cache/build items, freed $(Format-Size $freed)." -ForegroundColor Green

if ($useB -and $groupB.Count -gt 0) {
  $dest = Join-Path $Root "_to_delete/cleanup-$stamp"
  $moved = 0
  foreach ($i in $groupB) {
    $target = Join-Path $dest $i.Rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Move-Item -LiteralPath $i.Path -Destination $target
    $moved++
  }
  Write-Host "Moved $moved delivery scripts to _to_delete\cleanup-$stamp (put back with Move-Item if needed)." -ForegroundColor Green
}

Write-Host ""
Write-Host "Done. Group C items were left alone: review them yourself." -ForegroundColor Cyan
