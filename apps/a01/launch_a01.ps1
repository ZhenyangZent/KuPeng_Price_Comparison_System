[CmdletBinding()]
param(
    [string]$Screenshot,
    [int]$ScreenshotTab = 0,
    [int]$ExitAfterMs = 0
)

$ErrorActionPreference = 'Stop'
$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $AppRoot '.venv\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'A01 project-local Python is missing. Follow README_A01.md; no global installation is performed.'
}
$env:PYTHONPATH = $AppRoot
$Arguments = @('-m', 'a01_app.main')
if ($Screenshot) { $Arguments += @('--screenshot', $Screenshot, '--screenshot-tab', $ScreenshotTab) }
if ($ExitAfterMs -gt 0) { $Arguments += @('--exit-after-ms', $ExitAfterMs) }
& $Python @Arguments
exit $LASTEXITCODE
