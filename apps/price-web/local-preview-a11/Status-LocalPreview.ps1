$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $Here '..\..\..')).Path
$ProjectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $ProjectPython -PathType Leaf) {
    & $ProjectPython (Join-Path $Here 'control.py') status @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 (Join-Path $Here 'control.py') status @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python (Join-Path $Here 'control.py') status @args
} else {
    throw 'Python 3 not found.'
}
exit $LASTEXITCODE
