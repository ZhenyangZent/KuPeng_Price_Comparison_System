$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
& python (Join-Path $projectRoot 'scripts\d02\d02_sync.py') @args
exit $LASTEXITCODE
