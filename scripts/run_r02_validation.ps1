$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $Root

$LogDir = Join-Path $Root 'review\R02\logs'
$EvidenceDir = Join-Path $Root 'review\R02\evidence'
$TempDir = Join-Path $Root 'review\R02\tmp'
New-Item -ItemType Directory -Force -Path $LogDir, $EvidenceDir, $TempDir | Out-Null

$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $Root 'src'
$env:TEMP = $TempDir
$env:TMP = $TempDir

function Invoke-LoggedPython {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    $stdout = Join-Path $LogDir ($Name + '_stdout.log')
    $stderr = Join-Path $LogDir ($Name + '_stderr.log')
    $started = Get-Date
    $savedErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Action 1> $stdout 2> $stderr
    $code = $LASTEXITCODE
    $ErrorActionPreference = $savedErrorActionPreference
    $wall = ((Get-Date) - $started).TotalSeconds
    @(
        "NAME=$Name"
        "EXIT_CODE=$code"
        "WALL_SECONDS=$([math]::Round($wall, 3))"
        "STDOUT=$stdout"
        "STDERR=$stderr"
    ) | Set-Content -LiteralPath (Join-Path $LogDir ($Name + '_result.txt')) -Encoding utf8
    return $code
}

$environment = Join-Path $LogDir 'after_environment.txt'
$savedEnvironmentErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$pythonVersion = (& python -X utf8 -VV 2>&1 | Out-String).Trim()
$runtimeDetails = (& python -X utf8 -c "import platform,sqlite3,sys; print('PYTHON_EXECUTABLE='+sys.executable); print('PLATFORM='+platform.platform()); print('SQLITE='+sqlite3.sqlite_version)" 2>&1 | Out-String).Trim()
$ErrorActionPreference = $savedEnvironmentErrorActionPreference
@(
    "TASK_ID=CDH-C01-REWORK-003"
    "PROJECT_ROOT=$Root"
    "PYTHONPATH=$env:PYTHONPATH"
    "TEMP=$env:TEMP"
    "PRODUCT_MODE=OFFLINE_ONLY"
    $pythonVersion
    $runtimeDetails
) | Set-Content -LiteralPath $environment -Encoding utf8

$results = [ordered]@{}
$results['after_original_96'] = Invoke-LoggedPython 'after_original_96' {
    python -X utf8 -m unittest -v tests.test_history_policy tests.test_models_pricing tests.test_persistence_demo tests.test_rework_regressions
}
$results['after_independent_9'] = Invoke-LoggedPython 'after_independent_9' {
    python -X utf8 -m unittest -v tests.test_orchestrator_r01_new_regressions
}
$results['after_positive_7'] = Invoke-LoggedPython 'after_positive_7' {
    python -X utf8 -m unittest -v tests.test_r02_positive_regressions
}
$results['after_full_112'] = Invoke-LoggedPython 'after_full_112' {
    python -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
}

$demoDb = Join-Path $EvidenceDir 'demo_r02.sqlite3'
$demoJson = Join-Path $EvidenceDir 'demo_r02_results.json'
if (Test-Path -LiteralPath $demoDb) { Remove-Item -LiteralPath $demoDb -Force }
if (Test-Path -LiteralPath $demoJson) { Remove-Item -LiteralPath $demoJson -Force }
$results['after_demo'] = Invoke-LoggedPython 'after_demo' {
    python -X utf8 -m cdh_core.demo --fixtures tests\fixtures\demo_cases.json --db $demoDb --output $demoJson
}
$results['after_compileall'] = Invoke-LoggedPython 'after_compileall' {
    python -X utf8 -m compileall -q src tests scripts
}
$results['after_schema_audit'] = Invoke-LoggedPython 'after_schema_audit' {
    python -X utf8 scripts\schema_audit_r02.py
}
$results['after_traceability'] = Invoke-LoggedPython 'after_traceability' {
    python -X utf8 scripts\generate_r02_traceability.py
}
$results['after_metadata_audit'] = Invoke-LoggedPython 'after_metadata_audit' {
    python -X utf8 -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['name']=='cdh-core'; assert d['project']['version']=='0.3.0'; assert d['project']['dependencies']==[]; print('METADATA_GATE=PASS'); print('VERSION='+d['project']['version'])"
}

$summary = @(
    'TASK_ID=CDH-C01-REWORK-003'
    'ORIGINAL_TESTS=96'
    'INDEPENDENT_TESTS=9'
    'POSITIVE_TESTS=7'
    'FULL_TESTS=112'
)
foreach ($entry in $results.GetEnumerator()) {
    $summary += ($entry.Key.ToUpperInvariant() + '_EXIT_CODE=' + $entry.Value)
}
$overall = if (($results.Values | Where-Object { $_ -ne 0 }).Count -eq 0) { 'PASS' } else { 'FAIL' }
$summary += "OVERALL=$overall"
$summaryPath = Join-Path $LogDir 'R02_validation_summary.txt'
$summary | Set-Content -LiteralPath $summaryPath -Encoding utf8
Get-Content -LiteralPath $summaryPath

if ($overall -ne 'PASS') {
    exit 1
}
