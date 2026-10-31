<#
  Applies redesign step R3 "Focus Studio": Chat, the Ask AI panel and Quizzes.

    Ask AI   a button in the corner of every page (except Chat) opens the chat in a side panel, so you can
             ask about the page you are on. It is the same conversation, history and sources as the Chat
             page, and it keeps your place while closed. Ctrl/Cmd+J opens and closes it.
    Chat     your messages are blue bubbles, answers have a small AI badge, sources sit in a soft box,
             starter questions are cards, the message box is rounded.
    Quizzes  a "Continue where you left off" card for a quiz you started, rounded answer choices in the
             exam, and a score ring on the results page.

  Run from the project root in PowerShell:
      .\scripts\apply-redesign-r3.ps1

  Web only: no migration and no Python change; only the web image is rebuilt (the build type-checks
  the app). Nothing is deleted. Apply redesign R1 and R2 first.
#>
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Rebuilding the web app (the build type-checks it) ..." -ForegroundColor Cyan
docker compose up -d --build web
docker compose ps web
Write-Host "Done. Open http://localhost:3000/dashboard, click Ask AI, then try /chat and /quizzes." -ForegroundColor Green
