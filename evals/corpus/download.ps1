# OPTIONAL: these downloads are not used by evals/datasets/rag_v1.jsonl (see MANIFEST.md).
# Downloads a small, freely available corpus used by the evaluation questions.
# Run it from PowerShell on your own PC (the internet is not reachable from Claude's session):
#   cd "C:\Users\Shubham Haraniya\Desktop\Gen AI\Project\MindNest AI"
#   .\evals\corpus\download.ps1
# Files that already exist are skipped. A failed download is reported and does not stop the rest.

$ErrorActionPreference = "Continue"
$dir = $PSScriptRoot

$files = @(
    # English: AI papers (arXiv). Typed text, equations, tables, figures.
    @{ name = "en_react_paper.pdf";            url = "https://arxiv.org/pdf/2210.03629" },
    @{ name = "en_rewoo_paper.pdf";            url = "https://arxiv.org/pdf/2305.18323" },
    @{ name = "en_attention_paper.pdf";        url = "https://arxiv.org/pdf/1706.03762" },
    @{ name = "en_rag_paper.pdf";              url = "https://arxiv.org/pdf/2005.11401" },
    # English: school science chapters (NCERT, Class 10), plain textbook prose.
    @{ name = "en_ncert_science10_ch01.pdf";   url = "https://ncert.nic.in/textbook/pdf/jesc101.pdf" },
    @{ name = "en_ncert_science10_ch06.pdf";   url = "https://ncert.nic.in/textbook/pdf/jesc106.pdf" },
    # Hindi: the same NCERT chapters in the Hindi-medium book.
    @{ name = "hi_ncert_science10_ch01.pdf";   url = "https://ncert.nic.in/textbook/pdf/jhsc101.pdf" },
    @{ name = "hi_ncert_science10_ch06.pdf";   url = "https://ncert.nic.in/textbook/pdf/jhsc106.pdf" }
)

foreach ($file in $files) {
    $out = Join-Path $dir $file.name
    if (Test-Path $out) { Write-Host "skip    $($file.name) (already there)"; continue }
    try {
        Invoke-WebRequest -Uri $file.url -OutFile $out -UseBasicParsing -UserAgent "Mozilla/5.0 MindNestEval"
        $kb = [math]::Round((Get-Item $out).Length / 1KB)
        Write-Host "ok      $($file.name) ($kb KB)"
    } catch {
        if (Test-Path $out) { Remove-Item $out }
        Write-Host "FAILED  $($file.name)  <-  $($file.url)"
    }
}

Write-Host ""
Write-Host "Gujarati: copy your own Gujarati PDFs into this folder (for example the two Gujarat High Court"
Write-Host "judgments you already uploaded, named gu_judgment_*.pdf), and any Gujarati school chapter you like."
Write-Host "Then tell Claude, who will read the files and write the questions."
