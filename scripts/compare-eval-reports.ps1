<#
  Compares two live agent evaluation reports (before a change and after it) and writes a short
  Markdown summary you can paste into the README or an interview note.

    .\scripts\compare-eval-reports.ps1                       the two NEWEST live reports (older = before)
    .\scripts\compare-eval-reports.ps1 -Before evals\reports\agents-live-A.json -After evals\reports\agents-live-B.json
    .\scripts\compare-eval-reports.ps1 -Label "citation marks fix"

  It prints, for each measure, the value before, the value after and the change, then lists the cases
  that were fixed and the cases that got worse. The summary is saved as evals\reports\compare-<time>.md.

  Read it honestly: a model answers a little differently on every run, so a change of one or two
  cases (about 2 to 4 points of task success) can be noise. Speed depends on the AI provider's load
  and on your rate-limit waits, so do not claim a speed gain from it. Compare runs that used the same
  dataset, the same model and the same test account.

  This script only reads reports and writes one summary file.
#>
[CmdletBinding()]
param(
  [string]$Before = "",
  [string]$After = "",
  [string]$Label = "change"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$ReportDir = Join-Path (Get-Location).Path "evals/reports"

function Read-Report([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { throw "Report not found: $Path" }
  return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

if (-not $Before -or -not $After) {
  $live = @(Get-ChildItem $ReportDir -Filter "agents-live-*.json" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 2)
  if ($live.Count -lt 2) { throw "Need two live reports in evals\reports (before and after). Found $($live.Count)." }
  $After = $live[0].FullName
  $Before = $live[1].FullName
}
$b = Read-Report $Before
$a = Read-Report $After

Write-Host ""
Write-Host ("Before: " + (Split-Path $Before -Leaf) + "   (" + $b.summary.cases + " cases)") -ForegroundColor DarkGray
Write-Host ("After:  " + (Split-Path $After -Leaf)  + "   (" + $a.summary.cases + " cases)") -ForegroundColor DarkGray
if ($b.summary.cases -ne $a.summary.cases) {
  Write-Host "WARNING: the two runs do not have the same number of cases; compare only like with like." -ForegroundColor Yellow
}

# kind: "rate" (higher is better), "low" (lower is better), "info" (no judgement)
function Get-Rows($r) {
  $s = $r.summary
  return [ordered]@{
    "Task success"                         = @($s.task_success.rate, "rate")
    "Routing: exact agents"                = @($s.routing.exact, "rate")
    "Tools: needed tool was called"        = @($s.tools.recall, "rate")
    "Guardrails: blocked when it should"   = @($s.guardrails.recall, "rate")
    "Guardrails: safe wrongly blocked"     = @($s.guardrails.false_block_rate, "low")
    "Answers cite a source"                = @($s.grounding.citation_rate, "rate")
    "Cited numbers are all real sources"   = @($s.grounding.citations_all_real, "rate")
    "Faithfulness (judge)"                 = @($s.grounding.faithfulness, "rate")
    "Topic adherence (judge)"              = @($s.topic.adherence, "rate")
    "Time to finish p50 (ms)"              = @($s.speed_and_cost.total_ms.p50, "info")
    "Time to finish p95 (ms)"              = @($s.speed_and_cost.total_ms.p95, "info")
    "Tokens per run"                       = @($s.speed_and_cost.tokens_per_run, "info")
  }
}
$rb = Get-Rows $b
$ra = Get-Rows $a

function Format-Value($v, [string]$kind) {
  if ($null -eq $v) { return "n/a" }
  if ($kind -eq "info") { return ("{0:N0}" -f [double]$v) }
  return ("{0:P0}" -f [double]$v)
}

$lines = New-Object System.Collections.ArrayList
[void]$lines.Add("# Agent evaluation: before and after ($Label)")
[void]$lines.Add("")
[void]$lines.Add("Before: ``" + (Split-Path $Before -Leaf) + "`` (" + $b.summary.cases + " cases). After: ``" + (Split-Path $After -Leaf) + "`` (" + $a.summary.cases + " cases).")
[void]$lines.Add("")
[void]$lines.Add("| Measure | Before | After | Change |")
[void]$lines.Add("| --- | --- | --- | --- |")

Write-Host ""
Write-Host ("  {0,-38} {1,10} {2,10}   {3}" -f "Measure", "Before", "After", "Change") -ForegroundColor White
foreach ($name in $rb.Keys) {
  $vb = $rb[$name][0]; $va = $ra[$name][0]; $kind = $rb[$name][1]
  $sb = Format-Value $vb $kind; $sa = Format-Value $va $kind
  $change = "-"
  $color = "Gray"
  if ($null -ne $vb -and $null -ne $va) {
    $d = [double]$va - [double]$vb
    if ($kind -eq "info") {
      $change = ("{0:+#,##0;-#,##0;0}" -f $d)
    } else {
      $points = $d * 100
      $change = ("{0:+0.#;-0.#;0} pts" -f $points)
      if ([Math]::Abs($points) -ge 0.05) {
        $better = if ($kind -eq "low") { $d -lt 0 } else { $d -gt 0 }
        $color = if ($better) { "Green" } else { "Red" }
      }
    }
  }
  Write-Host ("  {0,-38} {1,10} {2,10}   {3}" -f $name, $sb, $sa, $change) -ForegroundColor $color
  [void]$lines.Add("| $name | $sb | $sa | $change |")
}

# cases that changed
$idsB = @{}; foreach ($c in $b.cases) { $idsB[$c.id] = $c }
$fixed = @(); $worse = @(); $same = 0; $missing = @()
foreach ($c in $a.cases) {
  if (-not $idsB.ContainsKey($c.id)) { $missing += $c.id; continue }
  $o = $idsB[$c.id]
  if ($o.status -eq "skipped" -or $c.status -eq "skipped") { continue }
  if (-not $o.passed -and $c.passed) { $fixed += ("{0}  (was: {1})" -f $c.id, ($o.failures -join "; ")) }
  elseif ($o.passed -and -not $c.passed) { $worse += ("{0}  (now: {1})" -f $c.id, ($c.failures -join "; ")) }
  else { $same++ }
}

Write-Host ""
Write-Host ("  Fixed: {0}   Got worse: {1}   Unchanged: {2}" -f $fixed.Count, $worse.Count, $same) -ForegroundColor White
[void]$lines.Add("")
[void]$lines.Add(("Cases fixed: {0}. Cases that got worse: {1}. Unchanged: {2}." -f $fixed.Count, $worse.Count, $same))
if ($fixed.Count -gt 0) {
  Write-Host "  Fixed:" -ForegroundColor Green
  [void]$lines.Add(""); [void]$lines.Add("Fixed:")
  foreach ($f in $fixed) { Write-Host "    $f" -ForegroundColor Green; [void]$lines.Add("- ``$f``") }
}
if ($worse.Count -gt 0) {
  Write-Host "  Got worse:" -ForegroundColor Red
  [void]$lines.Add(""); [void]$lines.Add("Got worse:")
  foreach ($w in $worse) { Write-Host "    $w" -ForegroundColor Red; [void]$lines.Add("- ``$w``") }
}
if ($missing.Count -gt 0) {
  Write-Host ("  Only in the after report (not compared): " + ($missing -join ", ")) -ForegroundColor DarkGray
}

$note = "A model answers slightly differently on each run, so one or two cases can be noise. Speed depends on the provider's load and rate-limit waits and is not evidence of a speed change. Same dataset, model and test account in both runs."
[void]$lines.Add("")
[void]$lines.Add("> $note")
Write-Host ""
Write-Host "  Note: $note" -ForegroundColor DarkGray

$out = Join-Path $ReportDir ("compare-agents-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".md")
Set-Content -LiteralPath $out -Value ($lines -join "`r`n") -Encoding UTF8
Write-Host ""
Write-Host "Saved: $out" -ForegroundColor Green
