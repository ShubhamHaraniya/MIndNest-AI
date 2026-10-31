<#
  Runs MindNest AI's evaluations: one command per kind of measurement.

    .\scripts\run-evals.ps1                     show this help and what each mode costs
    .\scripts\run-evals.ps1 -Mode Dataset       check the RAG question set against the corpus   (free, offline)
    .\scripts\run-evals.ps1 -Mode Guardrails    prompt-injection / safety rail test, 16 cases   (free, offline)
    .\scripts\run-evals.ps1 -Mode Offline       Dataset + Guardrails together                   (free, offline)
    .\scripts\run-evals.ps1 -Mode Agents        live agent run against the running app          (uses your AI key)
    .\scripts\run-evals.ps1 -Mode Rag           check the stack, then walk you through the RAG Lab
    .\scripts\run-evals.ps1 -Mode Reports       list the newest report files

  Common options
    -Limit 5            run only the first 5 cases (a cheap smoke test)
    -Category routing   run one category only (repeat the script for another)
    -Email / -Password  test account for -Mode Agents (or set EVAL_EMAIL and EVAL_PASSWORD).
                        Use a SEPARATE test account, never your real one.
    -JudgeProvider anthropic -JudgeModel claude-haiku-4-5
                        add a judge model so faithfulness and topic scores are filled in
                        (needs:  pip install -e ".[eval]"  and the judge's API key, asked for below)
    -Dataset / -Corpus  use another RAG question file or corpus folder (-Mode Dataset)
    -AgentDataset       use another agent case file (-Mode Guardrails or Agents)
    -AllowWrites        also run cases that add planner items or quizzes to the test account
    -ApiUrl             default http://localhost:3000/api/v1

  What the modes measure
    Dataset     every evidence phrase of evals/datasets/rag_v1.jsonl really occurs in the corpus,
                so a low retrieval score later means retrieval, not a broken question.
    Guardrails  the input safety rail on 16 attack and safe messages: attacks stopped,
                safe messages wrongly stopped, speed. No server, model or key is used.
    Agents      53 cases through the real app (routing, tools, task success, citations,
                latency, tokens). Needs the stack running and one AI key saved on the test account.
    Rag         retrieval quality (Recall@K, MRR, citation validity, latency) of baseline, hybrid
                and advanced retrieval. This runs inside the Evaluation Lab page of the web app,
                because it uses your uploaded files; this script checks the stack and tells you
                exactly what to click.

  Reports are written to evals\reports\ as .md (readable) and .json (data).

  One-time setup:   pip install -e ".[dev]"      (add  ".[eval]"  for Ragas scores)
  This script changes no source files. It only writes report files to evals\reports.
#>
[CmdletBinding()]
param(
  [ValidateSet("Help", "Dataset", "Guardrails", "Offline", "Agents", "Rag", "Reports")]
  [string]$Mode = "Help",
  [int]$Limit = 0,
  [string]$Category = "",
  [string]$Email = "",
  [string]$Password = "",
  [string]$ApiUrl = "http://localhost:3000/api/v1",
  [string]$JudgeProvider = "",
  [string]$JudgeModel = "",
  [switch]$AllowWrites,
  [string]$Dataset = "",
  [string]$AgentDataset = "",
  [string]$Corpus = ""
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$Root = (Get-Location).Path

function Write-Step([string]$Text) {
  Write-Host ""
  Write-Host "== $Text" -ForegroundColor Cyan
}

function Test-Python {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) { throw "python was not found. Activate your virtual environment first." }
  & python -c "import mindnest_agents" 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw "The project is not installed in this Python. Run once:  pip install -e `".[dev]`""
  }
}

function Test-Url([string]$Url) {
  try {
    $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
    return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)
  } catch {
    return $false
  }
}

function Show-Reports {
  Write-Step "Newest reports in evals\reports"
  $dir = Join-Path $Root "evals/reports"
  if (-not (Test-Path $dir)) { Write-Host "   none yet"; return }
  Get-ChildItem $dir -File | Sort-Object LastWriteTime -Descending | Select-Object -First 8 |
    ForEach-Object { Write-Host ("   {0}   {1:N0} KB   {2}" -f $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm"), ($_.Length / 1KB), $_.Name) }
  $md = Get-ChildItem $dir -Filter "*.md" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($md) { Write-Host ""; Write-Host "   Open the latest summary:  notepad `"$($md.FullName)`"" -ForegroundColor Green }
}

function Invoke-DatasetCheck {
  Write-Step "RAG dataset check (offline): are all evidence phrases present in the corpus?"
  Test-Python
  $args2 = @("evals/verify_dataset.py")
  if ($Dataset) { $args2 += @("--dataset", $Dataset) }
  if ($Corpus)  { $args2 += @("--corpus", $Corpus) }
  & python @args2
  if ($LASTEXITCODE -ne 0) {
    Write-Host "   The dataset check reported problems. Read the lines above; a missing phrase usually means a PDF is not downloaded (see evals\corpus\download.ps1)." -ForegroundColor Yellow
  } else {
    Write-Host "   dataset check finished" -ForegroundColor Green
  }
}

function Add-CommonArgs([System.Collections.ArrayList]$List) {
  if ($AgentDataset) { [void]$List.AddRange(@("--dataset", $AgentDataset)) }
  if ($Limit -gt 0) { [void]$List.AddRange(@("--limit", "$Limit")) }
  if ($Category) { [void]$List.AddRange(@("--category", $Category)) }
}

function Invoke-Guardrails {
  Write-Step "Guardrail evaluation (offline): attacks stopped vs safe messages wrongly stopped"
  Test-Python
  $list = New-Object System.Collections.ArrayList
  [void]$list.AddRange(@("-m", "mindnest_agents.evaluation", "offline"))
  Add-CommonArgs $list
  & python $list.ToArray()
  if ($LASTEXITCODE -ne 0) { throw "Guardrail evaluation failed (exit code $LASTEXITCODE)." }
  Write-Host "   guardrail evaluation finished" -ForegroundColor Green
}

function ConvertTo-PlainText([System.Security.SecureString]$Secure) {
  $ptr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
  try { return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Invoke-Agents {
  Write-Step "Live agent evaluation (talks to the running app and uses the test account's AI key)"
  Test-Python

  $apiRoot = $ApiUrl -replace "/api/v1/?$", ""
  Write-Host "   checking that the app answers at $apiRoot ..."
  if (-not (Test-Url ($apiRoot + "/api/v1/health"))) {
    throw "The app did not answer at $ApiUrl. Start it first:  docker compose up -d   (then wait for the web container to be healthy)."
  }

  $mail = $Email
  if (-not $mail) { $mail = $env:EVAL_EMAIL }
  if (-not $mail) { $mail = Read-Host "Test account e-mail (a separate account, not your real one)" }
  $pass = $Password
  if (-not $pass) { $pass = $env:EVAL_PASSWORD }
  if (-not $pass) { $pass = ConvertTo-PlainText (Read-Host "Test account password" -AsSecureString) }

  $list = New-Object System.Collections.ArrayList
  [void]$list.AddRange(@("-m", "mindnest_agents.evaluation", "live", "--api-url", $ApiUrl, "--email", $mail, "--password", $pass))
  Add-CommonArgs $list
  if ($Corpus) { [void]$list.AddRange(@("--corpus", $Corpus)) }
  if ($AllowWrites) { [void]$list.Add("--allow-writes") }

  if ($JudgeProvider -or $JudgeModel) {
    if (-not ($JudgeProvider -and $JudgeModel)) { throw "Give both -JudgeProvider and -JudgeModel, or neither." }
    if (-not $env:EVAL_JUDGE_API_KEY) {
      $env:EVAL_JUDGE_API_KEY = ConvertTo-PlainText (Read-Host "API key of the judge model ($JudgeProvider)" -AsSecureString)
    }
    [void]$list.AddRange(@("--judge-provider", $JudgeProvider, "--judge-model", $JudgeModel))
  } else {
    Write-Host "   no judge model given: faithfulness and topic scores will show n/a (everything else is measured)." -ForegroundColor DarkGray
  }

  Write-Host "   running ... each case waits a few seconds because chat is rate limited (20 per minute)."
  & python $list.ToArray()
  if ($LASTEXITCODE -ne 0) { throw "Live agent evaluation failed (exit code $LASTEXITCODE). Common causes: wrong e-mail or password, no AI key saved on that account, app not running." }
  Write-Host "   live agent evaluation finished" -ForegroundColor Green
}

function Invoke-RagGuide {
  Write-Step "RAG Lab: checking that everything it needs is running"

  $ok = $true
  $apiRoot = $ApiUrl -replace "/api/v1/?$", ""
  if (Test-Url ($apiRoot + "/api/v1/health")) {
    Write-Host "   [ok]  app is up ($apiRoot)" -ForegroundColor Green
  } else {
    Write-Host "   [!!]  app is not answering at $apiRoot  ->  docker compose up -d" -ForegroundColor Red
    $ok = $false
  }
  if (Test-Url "http://localhost:8100/health") {
    Write-Host "   [ok]  model service is up (http://localhost:8100)" -ForegroundColor Green
  } else {
    Write-Host "   [!!]  model service is not answering at http://localhost:8100  ->  start it on the host (README, Quick start, step 2)." -ForegroundColor Red
    Write-Host "         Without it a run is marked 'degraded' and must NOT be compared." -ForegroundColor Yellow
    $ok = $false
  }

  $pdfs = @(Get-ChildItem (Join-Path $Root "evals/corpus") -Filter "*.pdf" -File -ErrorAction SilentlyContinue)
  $synth = @(Get-ChildItem (Join-Path $Root "evals/corpus/synthetic") -File -ErrorAction SilentlyContinue)
  Write-Host ("   [..]  corpus: {0} PDF(s), {1} synthetic file(s)" -f $pdfs.Count, $synth.Count)
  if ($pdfs.Count -eq 0) {
    Write-Host "         No PDFs downloaded. Questions about them will report 'material missing'. Optional: .\evals\corpus\download.ps1" -ForegroundColor Yellow
  }

  Invoke-DatasetCheck

  Write-Step "Now do this in the browser (about 15 minutes, the first three runs are free)"
  Write-Host @"

   1. Open http://localhost:3000 and sign in with a TEST account. Add an AI key in Settings.
   2. Library: create a subject (for example "Eval corpus") and upload everything in
        evals\corpus\            (the PDFs, if you downloaded them)
        evals\corpus\synthetic\  (the shipped text files)
      Wait until every file shows "ready".
   3. Open http://localhost:3000/eval  ->  import evals\datasets\rag_v1.jsonl
      (50 questions: 26 English, 12 Hindi, 12 Gujarati). Press "Check against my materials".
   4. Start one run per retrieval mode, WITHOUT answer generation (free, no AI key used):
        baseline   vector search only
        hybrid     vector + full text, fused with reciprocal rank fusion
        advanced   vector + cross-encoder rerank (this is what chat uses)
   5. Start one more "advanced" run WITH generation and the judge turned on. This is the only
      run that spends tokens; it fills citation and answer-quality scores.
   6. Use "Compare runs" and read Recall@K, MRR, citation validity and p50/p95 latency, overall
      and per language. Copy the numbers into the table in README.md ("Evaluation results").

   Rules: never compare a run marked "degraded". Do not change the corpus between runs.
"@

  if (-not $ok) {
    Write-Host "   Fix the red items above before step 4." -ForegroundColor Yellow
  }
  try { Start-Process "http://localhost:3000/eval" } catch { }
}

switch ($Mode) {
  "Help" {
    $text = Get-Content -LiteralPath $MyInvocation.MyCommand.Path -Raw
    $start = $text.IndexOf("<#") + 2
    $end = $text.IndexOf("#>")
    Write-Host $text.Substring($start, $end - $start)
    exit 0
  }
  "Dataset"    { Invoke-DatasetCheck }
  "Guardrails" { Invoke-Guardrails }
  "Offline"    { Invoke-DatasetCheck; Invoke-Guardrails }
  "Agents"     { Invoke-Agents }
  "Rag"        { Invoke-RagGuide }
  "Reports"    { }
}

Show-Reports
