# Sets GitHub repository topics via GitHub CLI.
# Prerequisite: winget install GitHub.cli  (or https://cli.github.com/)
# Then: gh auth login
# Usage (from repo root): pwsh ./scripts/set-repo-topics.ps1

$ErrorActionPreference = "Stop"
$repo = "BrianChang1212/dolores"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Error "GitHub CLI (gh) not found. Install: winget install GitHub.cli"
    exit 1
}

$topics = @(
    "python",
    "ollama",
    "cli",
    "rich",
    "local-ai",
    "offline",
    "tts",
    "chromadb",
    "memory",
    "chatbot",
    "companion",
    "mempalace",
    "pyyaml",
    "edge-tts",
    "piper-tts"
)

$ghArgs = @("repo", "edit", $repo)
foreach ($t in $topics) {
    $ghArgs += "--add-topic"
    $ghArgs += $t
}

& gh @ghArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Host "Topics applied to $repo"
