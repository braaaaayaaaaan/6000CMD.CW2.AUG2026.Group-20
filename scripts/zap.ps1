param(
    [Parameter(Position=0)]
    [ValidateSet('init', 'start', 'stop', 'reset', 'verify', 'status')]
    [string]$Action = 'status'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$branch = & git -C $repoRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch -cne 'test/owasp-zap') {
    throw 'ZAP commands require the existing test/owasp-zap branch. No branch was switched.'
}
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'The existing .venv Python is required. This script does not install dependencies.'
}
& $pythonPath -B (Join-Path $PSScriptRoot 'zap.py') $Action
if ($LASTEXITCODE -ne 0) { throw "ZAP command failed (exit $LASTEXITCODE)." }
