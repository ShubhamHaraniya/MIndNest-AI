<#
  One-command agent evaluation: prints REAL metrics for MindNest AI's multi-agent chat.

  Run from the PROJECT ROOT (the folder that contains apps\web and pyproject.toml):

      .\scripts\eval-agents.ps1                    full run, asks for what it needs
      .\scripts\eval-agents.ps1 -Quick             5 cases only (about 2 minutes) to see that it works
      .\scripts\eval-agents.ps1 -Delay 10 -BatchPause 180      slower, gentler on a free AI plan
      .\scripts\eval-agents.ps1 -Only study-mnemonic,materials-summary    just these cases (to re-check after a fix)
      .\scripts\eval-agents.ps1 -CleanLeftovers   delete old 'Eval Biology' subjects left in the TEST account, then stop
      .\scripts\eval-agents.ps1 -Part 1           only the 1st of 5 groups (do 1..5 on different days if your quota is small)
      .\scripts\eval-agents.ps1 -SkipWrites        leave out the 7 cases that add planner items / quizzes
      .\scripts\eval-agents.ps1 -OfflineOnly       only the free guardrail test (no stack, no key)

  What it does, in order
    1. Offline guardrail test (16 cases, free).
    2. Live run: all 53 cases through the real chat API as a TEST student, in 5 groups (batches)
       with a pause between groups so an AI provider's rate limit can recover. One combined report.
       Cases the provider still rate-limited are tried once more at the end; if they still cannot run
       they are listed as skipped (not failed). Takes about 15 to 30 minutes with the default settings.
    3. Optional judge model (Ragas) for faithfulness and topic adherence.
    4. Prints the headline numbers and every failed case, and tells you where the report files are.

  Before the live run you need (once)
    a) The stack running:        docker compose up -d
       and the model service on the host (it reads the test documents):  scripts\start-models.ps1
    b) A SEPARATE TEST ACCOUNT:  sign up at http://localhost:3000 (for example mindnest-eval@example.com),
       NEVER use an address ending in @mindnest-tests.dev: the pytest suite deletes every account with that
       ending. Then in Settings add an AI key and choose a model. Do NOT use your real account: the run creates
       a subject, uploads two small notes, adds planner items and quizzes, and removes them afterwards.
    c) Python packages:          pip install -e ".[dev]"
       For the judge scores also: pip install -e ".[eval]"   (or run this script with -InstallEval)

  Options
    -Email / -Password      test account (or set EVAL_EMAIL / EVAL_PASSWORD; otherwise you are asked)
    -ApiUrl                 default http://localhost:3000/api/v1
    -Provider / -Model      force the model under test (default: the one saved in the test account)
    -JudgeProvider / -JudgeModel
                            the model that SCORES answers; use a different one from the model under test.
                            Its key is asked for (hidden) or taken from EVAL_JUDGE_API_KEY.
                            Leave both empty to skip faithfulness / topic scores (all other metrics still run).
    -Delay                  seconds to wait after EVERY case (default 6). Raise it if you still hit rate limits;
                            a free plan allowing 15 requests a minute needs 15 or more, because one case makes
                            several model calls (router, agent, tools).
    -Batches                number of groups (default 5)
    -BatchPause             seconds to rest between groups (default 90). Raise it to 180 or 300 on a free plan.
    -Part n                 run ONLY group n (1 to -Batches) and stop. Each part gives its own report, so
                            the combined numbers come only from a normal run without -Part.
    -InstallEval            run  pip install -e ".[eval]"  first (needed for the judge scores)

  This script changes no source files. It writes reports to evals\reports\ and never prints your passwords.
#>
[CmdletBinding()]
param(
  [switch]$Quick,
  [switch]$SkipWrites,
  [switch]$OfflineOnly,
  [switch]$InstallEval,
  [string]$Email = "",
  [string]$Password = "",
  [string]$ApiUrl = "http://localhost:3000/api/v1",
  [string]$Provider = "",
  [string]$Model = "",
  [string]$JudgeProvider = "",
  [string]$JudgeModel = "",
  [double]$Delay = 6,
  [int]$Batches = 5,
  [double]$BatchPause = 90,
  [int]$Part = 0,
  [string[]]$Only = @(),
  [switch]$CleanLeftovers
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Root = (Get-Location).Path
$ReportDir = Join-Path $Root "evals/reports"

function Write-Step([string]$Text) { Write-Host ""; Write-Host "== $Text" -ForegroundColor Cyan }

function ConvertTo-PlainText([System.Security.SecureString]$Secure) {
  $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Test-Url([string]$Url) {
  try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
    return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)
  } catch { return $false }
}

function Get-NewestReport([string]$Pattern) {
  if (-not (Test-Path $ReportDir)) { return $null }
  return Get-ChildItem $ReportDir -Filter $Pattern -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

function Format-Pct($Value) {
  if ($null -eq $Value) { return "n/a" }
  return ("{0:P0}" -f [double]$Value)
}

function Format-Ms($Value) {
  if ($null -eq $Value) { return "n/a" }
  return ("{0:N0} ms" -f [double]$Value)
}

function Show-Summary([string]$JsonPath) {
  $data = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $s = $data.summary
  Write-Host ""
  Write-Host ("Report: " + $JsonPath) -ForegroundColor DarkGray
  $rows = @(
    @("Cases run / passed",                 ("{0} / {1}  (skipped {2})" -f $s.task_success.cases, $s.task_success.passed, $s.task_success.skipped)),
    @("Task success",                       (Format-Pct $s.task_success.rate)),
    @("Routing: exact agents / first agent", ("{0} / {1}  ({2} cases)" -f (Format-Pct $s.routing.exact), (Format-Pct $s.routing.first_agent), $s.routing.cases)),
    @("Tools: needed tool was called",      ("{0}  ({1} checks)" -f (Format-Pct $s.tools.recall), $s.tools.expected_calls)),
    @("Tools: forbidden tool used",         ("{0} of {1} checks" -f $s.tools.forbidden_used, $s.tools.forbidden_checks)),
    @("Guardrails: blocked when it should", ("{0}  (missed {1})" -f (Format-Pct $s.guardrails.recall), $s.guardrails.missed)),
    @("Guardrails: safe message wrongly blocked", ("{0}  ({1})" -f (Format-Pct $s.guardrails.false_block_rate), $s.guardrails.false_block)),
    @("Answers cite a source",              ("{0}  ({1} cases)" -f (Format-Pct $s.grounding.citation_rate), $s.grounding.citation_cases)),
    @("Cited numbers are all real sources", (Format-Pct $s.grounding.citations_all_real)),
    @("Faithfulness (judge)",               (Format-Pct $s.grounding.faithfulness)),
    @("Topic adherence (judge)",            (Format-Pct $s.topic.adherence)),
    @("Time to first word p50 / p95",       ("{0} / {1}" -f (Format-Ms $s.speed_and_cost.first_token_ms.p50), (Format-Ms $s.speed_and_cost.first_token_ms.p95))),
    @("Time to finish p50 / p95",           ("{0} / {1}" -f (Format-Ms $s.speed_and_cost.total_ms.p50), (Format-Ms $s.speed_and_cost.total_ms.p95))),
    @("Tokens per run (total)",             ("{0} ({1})" -f $s.speed_and_cost.tokens_per_run, $s.speed_and_cost.tokens_total))
  )
  foreach ($r in $rows) { Write-Host ("  {0,-42} {1}" -f $r[0], $r[1]) }

  if ($s.task_success.by_category) {
    Write-Host ""
    Write-Host "  Task success by category" -ForegroundColor White
    foreach ($p in $s.task_success.by_category.PSObject.Properties) {
      Write-Host ("    {0,-12} {1,3} cases   {2}" -f $p.Name, $p.Value.cases, (Format-Pct $p.Value.rate))
    }
  }

  $failed = @($data.cases | Where-Object { $_.status -ne "skipped" -and -not $_.passed })
  Write-Host ""
  if ($failed.Count -eq 0) {
    Write-Host "  Every case that ran passed." -ForegroundColor Green
  } else {
    Write-Host ("  Failed cases ({0}):" -f $failed.Count) -ForegroundColor Yellow
    foreach ($f in $failed) { Write-Host ("    {0,-28} {1}" -f $f.id, ($f.failures -join "; ")) }
    Write-Host "  Read these before trusting a number: a failing case can mean a wrong expectation, not a bug." -ForegroundColor DarkGray
  }
  $skipped = @($data.cases | Where-Object { $_.status -eq "skipped" })
  if ($skipped.Count -gt 0) {
    Write-Host ("  Skipped ({0}): {1}" -f $skipped.Count, (($skipped | ForEach-Object { $_.id }) -join ", ")) -ForegroundColor DarkGray
  }
}

# ----------------------------------------------------------------------------- checks

if (-not (Test-Path (Join-Path $Root "apps/web/package.json")) -or -not (Test-Path (Join-Path $Root "pyproject.toml"))) {
  throw "Run this from the project root (the folder that contains apps\web and pyproject.toml). Current folder: $Root"
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "python was not found. Activate your virtual environment first." }
& python -c "import mindnest_agents" 2>$null
if ($LASTEXITCODE -ne 0) { throw "The project is not installed in this Python. Run once:  pip install -e `".[dev]`"" }

if ($InstallEval) {
  Write-Step "Installing the judge scorers (pip install -e `".[eval]`")"
  & python -m pip install -e ".[eval]"
  if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit code $LASTEXITCODE)." }
}

# ----------------------------------------------------------------------------- tidy the test account

if ($CleanLeftovers) {
  Write-Step "Removing leftover 'Eval Biology' subjects from the TEST account"
  $cleanMail = $Email
  if (-not $cleanMail) { $cleanMail = $env:EVAL_EMAIL }
  if (-not $cleanMail) { $cleanMail = Read-Host "   Test account e-mail" }
  $cleanPass = $Password
  if (-not $cleanPass) { $cleanPass = $env:EVAL_PASSWORD }
  if (-not $cleanPass) { $cleanPass = ConvertTo-PlainText (Read-Host "   Test account password" -AsSecureString) }
  & python -m mindnest_agents.evaluation cleanup --api-url $ApiUrl --email $cleanMail --password $cleanPass
  if ($LASTEXITCODE -ne 0) { throw "Cleanup failed (exit code $LASTEXITCODE). Is the app running and the e-mail and password right?" }
  exit 0
}

# ----------------------------------------------------------------------------- 1. offline

Write-Step "1. Offline guardrail test (free, no stack needed)"
& python -m mindnest_agents.evaluation offline
$offlineCode = $LASTEXITCODE
if ($offlineCode -ne 0) {
  Write-Host "   Some guardrail cases failed (see above). Continuing." -ForegroundColor Yellow
}
$off = Get-NewestReport "agents-offline-*.json"
if ($off) { Show-Summary $off.FullName }

if ($OfflineOnly) {
  Write-Host ""
  Write-Host "Offline only: done. For the live run use  .\scripts\eval-agents.ps1" -ForegroundColor Green
  exit 0
}

# ----------------------------------------------------------------------------- 2. live

Write-Step "2. Live agent run (real chat API, real model, test account)"

$apiRoot = $ApiUrl -replace "/api/v1/?$", ""
Write-Host "   checking that the app answers at $apiRoot ..."
if (-not (Test-Url ($apiRoot + "/api/v1/health"))) {
  throw "The app did not answer at $ApiUrl. Start it first:  docker compose up -d   (wait until the web container is healthy)."
}
if (-not (Test-Url "http://localhost:8100/health")) {
  Write-Host "   WARNING: the model service is not answering on http://localhost:8100." -ForegroundColor Yellow
  Write-Host "            The run uploads two small notes and needs it to read them. Start it with  scripts\start-models.ps1" -ForegroundColor Yellow
  $go = Read-Host "   Continue anyway? (y/N)"
  if ($go -ne "y" -and $go -ne "Y") { exit 1 }
}

$mail = $Email
if (-not $mail) { $mail = $env:EVAL_EMAIL }
if (-not $mail) { $mail = Read-Host "   Test account e-mail (a SEPARATE account with an AI key saved in Settings)" }
$pass = $Password
if (-not $pass) { $pass = $env:EVAL_PASSWORD }
if (-not $pass) { $pass = ConvertTo-PlainText (Read-Host "   Test account password" -AsSecureString) }

if (-not $JudgeProvider -and -not $JudgeModel) {
  Write-Host ""
  Write-Host "   Judge model (scores faithfulness and topic adherence). Use a different model from the one under test." -ForegroundColor White
  Write-Host "   Examples: openai gpt-4o-mini | anthropic claude-haiku-4-5 | gemini gemini-2.0-flash | groq llama-3.3-70b-versatile"
  $JudgeProvider = Read-Host "   Judge provider (press Enter to skip the judge scores)"
  if ($JudgeProvider) { $JudgeModel = Read-Host "   Judge model" }
}

if ($Batches -lt 1) { throw "-Batches must be 1 or more." }
$TotalParts = $Batches
if ($Delay -lt 0 -or $BatchPause -lt 0) { throw "-Delay and -BatchPause cannot be negative." }
$help = (& python -m mindnest_agents.evaluation live --help) -join "`n"
if ($help -notmatch "--batches") {
  throw "Your evaluation tool does not know --batches yet. Copy the updated libs\agents\mindnest_agents\evaluation\__main__.py from the package (apply-repo-ready is not needed; see the message that came with this script)."
}

$cliArgs = New-Object System.Collections.ArrayList
[void]$cliArgs.AddRange(@("-m", "mindnest_agents.evaluation", "live", "--api-url", $ApiUrl, "--email", $mail, "--password", $pass, "--delay", "$Delay"))
if ($Only.Count -gt 0) {
  foreach ($id in $Only) { [void]$cliArgs.AddRange(@("--only", $id)) }
  $Batches = 1
} elseif ($Quick) {
  $Batches = 1
} elseif ($Part -gt 0) {
  # same split as the tool: consecutive groups of almost equal size
  if ($Part -gt $Batches) { throw "-Part must be between 1 and -Batches ($Batches)." }
  $ids = New-Object System.Collections.ArrayList
  foreach ($line in (Get-Content (Join-Path $Root "evals/agents/agent_v1.jsonl") -Encoding UTF8)) {
    if ($line.Trim() -eq "" -or $line.TrimStart().StartsWith("#")) { continue }
    [void]$ids.Add(($line | ConvertFrom-Json).id)
  }
  $n = [Math]::Min($Batches, $ids.Count)
  $size = [Math]::Floor($ids.Count / $n)
  $extra = $ids.Count % $n
  $from = 0
  for ($i = 1; $i -lt $Part; $i++) { $from += $size + $(if ($i -le $extra) { 1 } else { 0 }) }
  $count = $size + $(if ($Part -le $extra) { 1 } else { 0 })
  foreach ($id in $ids.GetRange($from, $count)) { [void]$cliArgs.AddRange(@("--only", $id)) }
  Write-Host ("   Part {0} of {1}: {2} cases ({3} ... {4})" -f $Part, $Batches, $count, $ids[$from], $ids[$from + $count - 1]) -ForegroundColor DarkGray
  $Batches = 1
}
[void]$cliArgs.AddRange(@("--batches", "$Batches", "--batch-pause", "$BatchPause"))
if (-not $SkipWrites) { [void]$cliArgs.Add("--allow-writes") }
if ($Quick) { [void]$cliArgs.AddRange(@("--category", "study", "--limit", "5")) }
if ($Provider -and $Model) { [void]$cliArgs.AddRange(@("--provider", $Provider, "--model", $Model)) }

if ($JudgeProvider -and $JudgeModel) {
  & python -c "import ragas" 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw "Ragas is not installed, so the judge cannot run. Run once:  pip install -e `".[eval]`"   (or add -InstallEval), then run this script again."
  }
  if (-not $env:EVAL_JUDGE_API_KEY) {
    $env:EVAL_JUDGE_API_KEY = ConvertTo-PlainText (Read-Host "   API key of the judge model ($JudgeProvider)" -AsSecureString)
  }
  [void]$cliArgs.AddRange(@("--judge-provider", $JudgeProvider, "--judge-model", $JudgeModel))
} elseif ($JudgeProvider -or $JudgeModel) {
  throw "Give both a judge provider and a judge model, or neither."
} else {
  Write-Host "   No judge model: faithfulness and topic scores will show n/a. Everything else is measured." -ForegroundColor DarkGray
}

if ($Only.Count -gt 0) {
  Write-Host ("   Only these cases: " + ($Only -join ", ") + ". Delay between cases: $Delay s.") -ForegroundColor DarkGray
} elseif ($Quick) {
  Write-Host "   Quick mode: 5 study cases." -ForegroundColor DarkGray
} else {
  if ($Part -gt 0) {
    Write-Host ("   Part {0} of {1}. Delay between cases: {2} s." -f $Part, $TotalParts, $Delay)
  } else {
    Write-Host ("   Full run: 53 cases in {0} groups. Delay between cases: {1} s. Rest between groups: {2} s." -f $Batches, $Delay, $BatchPause)
    Write-Host "   Rate-limit messages mean the AI provider is slowing you down: the tool waits and retries by itself. To go gentler next time:  -Delay 10 -BatchPause 180"
  }
}
Write-Host ""

& python $cliArgs.ToArray()
$liveCode = $LASTEXITCODE
if ($liveCode -ne 0) {
  throw "The live run stopped (exit code $liveCode). Common causes: wrong e-mail or password, no AI key saved on that account, e-mail not confirmed, the app or model service not running. The message above says which."
}

# ----------------------------------------------------------------------------- 3. results

Write-Step "3. Results"
$live = Get-NewestReport "agents-live-*.json"
if ($live) {
  Show-Summary $live.FullName
  $md = [System.IO.Path]::ChangeExtension($live.FullName, ".md")
  Write-Host ""
  Write-Host "Readable report:  notepad `"$md`"" -ForegroundColor Green
}
Write-Host ""
Write-Host "Next: copy the numbers you want to quote into README.md (section Evaluation, Results) and commit evals\reports\ with them." -ForegroundColor Green
