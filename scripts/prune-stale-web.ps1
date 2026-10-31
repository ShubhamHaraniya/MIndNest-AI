<#
  Moves web source files that are NOT in any MindNest update archive into _to_delete\ (nothing is
  deleted). It reads every mindnest-*.tar.gz in your Downloads folder (the redesign and each later
  batch), so files added by a later batch are never treated as stale.
  Run from the project root:
      .\scripts\prune-stale-web.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$archives = Get-ChildItem -Path (Join-Path $HOME "Downloads") -Filter "mindnest-*.tar.gz" -ErrorAction SilentlyContinue
if (-not $archives) { throw "No mindnest-*.tar.gz archives found in Downloads." }
if (-not ($archives | Where-Object { $_.Name -eq "mindnest-redesign.tar.gz" })) {
  throw "mindnest-redesign.tar.gz must still be in Downloads (it lists most of the web files)."
}

$prefix = "mindnest/apps/web/src/"
$keep = @{}
foreach ($archive in $archives) {
  foreach ($line in (tar -tzf $archive.FullName)) {
    if ($line.StartsWith($prefix) -and -not $line.EndsWith("/")) {
      $keep[$line.Substring($prefix.Length).Replace("/", "\")] = $true
    }
  }
}
Write-Host ("Archives read: {0}. Web source files they contain: {1}." -f $archives.Count, $keep.Count)

$root = Join-Path (Get-Location) "apps\web\src"
$moved = 0
Get-ChildItem -Path $root -Recurse -File | ForEach-Object {
  $relative = $_.FullName.Substring($root.Length + 1)
  if (-not $keep.ContainsKey($relative)) {
    $target = Join-Path "_to_delete\apps\web\src" $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Move-Item -Force $_.FullName $target
    Write-Host "moved $relative"
    $moved++
  }
}
Write-Host "$moved stale file(s) moved to _to_delete\apps\web\src"
