$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
& python (Join-Path $projectRoot 'scripts\d03\local_operator.py') @args
exit $LASTEXITCODE
