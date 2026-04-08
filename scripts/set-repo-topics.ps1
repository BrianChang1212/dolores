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

# Core topics (owner list) + mempalace (stack); add more with --add-topic as needed.
$topics = @(
    "python",
    "ollama",
    "mcp",
    "chromadb",
    "tts",
    "cli",
    "local-ai",
    "companion",
    "mempalace"
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
