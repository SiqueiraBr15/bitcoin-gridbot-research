# Manual process only. No elevation, policy changes, service or scheduled task.
[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [string]$ArchiveRoot,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Error 'Python local ausente. Crie .venv e instale o projeto conforme docs/RESEARCH_CONSOLE.md, ou informe -Python.'
    exit 1
}
& $Python -X utf8 -c "import sys, gridbot, research_console; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Ambiente incompleto ou Python anterior a 3.13. Consulte as instrucoes de instalacao.'
    exit 1
}
$consoleArguments = @('-X', 'utf8', '-m', 'research_console', '--port', "$Port")
if ($ArchiveRoot) { $consoleArguments += @('--archive-root', $ArchiveRoot) }
Write-Host "GridBot PAPER / OFFLINE: http://127.0.0.1:$Port - Ctrl+C para encerrar."
Push-Location -LiteralPath $PSScriptRoot
try {
    & $Python @consoleArguments
    $consoleExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $consoleExit
