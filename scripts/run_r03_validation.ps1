$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $Root

$LogDir = Join-Path $Root 'review\R03\logs'
$EvidenceDir = Join-Path $Root 'review\R03\evidence\after'
$TempDir = Join-Path $Root 'review\R03\tmp'
New-Item -ItemType Directory -Force -Path $LogDir, $EvidenceDir, $TempDir | Out-Null

$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
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

$pythonVersion = (& python -X utf8 -VV 2>&1 | Out-String).Trim()
$runtimeDetails = (& python -X utf8 -c "import platform,sqlite3,sys; print('PYTHON_EXECUTABLE='+sys.executable); print('PLATFORM='+platform.platform()); print('SQLITE='+sqlite3.sqlite_version)" 2>&1 | Out-String).Trim()
@(
    'TASK_ID=CDH-C01-REWORK-004'
    "PROJECT_ROOT=$Root"
    "PYTHONPATH=$env:PYTHONPATH"
    "TEMP=$env:TEMP"
    'PRODUCT_MODE=OFFLINE_ONLY'
    $pythonVersion
    $runtimeDetails
) | Set-Content -LiteralPath (Join-Path $LogDir 'after_environment.txt') -Encoding utf8

$results = [ordered]@{}
$results['after_original_112'] = Invoke-LoggedPython 'after_original_112' {
    python -X utf8 -m unittest -v tests.test_history_policy tests.test_models_pricing tests.test_orchestrator_r01_new_regressions tests.test_persistence_demo tests.test_r02_positive_regressions tests.test_rework_regressions
}
$results['after_r03_16'] = Invoke-LoggedPython 'after_r03_16' {
    python -X utf8 -m unittest -v tests.test_r03_policy_fee_coupon_regressions
}
$results['after_full_128'] = Invoke-LoggedPython 'after_full_128' {
    python -X utf8 -m unittest discover -s tests -p 'test_*.py' -v
}
$results['after_orchestrator_semantic_7'] = Invoke-LoggedPython 'after_orchestrator_semantic_7' {
    python -X utf8 -m unittest discover -s review\R03\evidence\after -p 'test_orchestrator_r02_counterexamples_after.py' -v
}

$demoDb = Join-Path $EvidenceDir 'demo_r03.sqlite3'
$demoJson = Join-Path $EvidenceDir 'demo_r03_results.json'
if (Test-Path -LiteralPath $demoDb) { Remove-Item -LiteralPath $demoDb -Force }
if (Test-Path -LiteralPath $demoJson) { Remove-Item -LiteralPath $demoJson -Force }
$results['after_demo'] = Invoke-LoggedPython 'after_demo' {
    python -X utf8 -m cdh_core.demo --fixtures tests\fixtures\demo_cases.json --db $demoDb --output $demoJson
}
$results['after_schema_audit'] = Invoke-LoggedPython 'after_schema_audit' {
    python -X utf8 scripts\schema_audit_r03.py
}
$results['after_metadata_audit'] = Invoke-LoggedPython 'after_metadata_audit' {
    python -X utf8 -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['name']=='cdh-core'; assert d['project']['version']=='0.4.0'; assert d['project']['dependencies']==[]; print('METADATA_GATE=PASS'); print('VERSION='+d['project']['version'])"
}

$summary = @(
    'TASK_ID=CDH-C01-REWORK-004'
    'ORIGINAL_TESTS=112'
    'R03_REGRESSION_TESTS=16'
    'FULL_PRODUCT_TESTS=128'
    'SEMANTIC_AFTER_TESTS=7'
)
foreach ($entry in $results.GetEnumerator()) {
    $summary += ($entry.Key.ToUpperInvariant() + '_EXIT_CODE=' + $entry.Value)
}
$overall = if (($results.Values | Where-Object { $_ -ne 0 }).Count -eq 0) { 'PASS' } else { 'FAIL' }
$summary += "OVERALL=$overall"
$summaryPath = Join-Path $LogDir 'R03_validation_summary.txt'
$summary | Set-Content -LiteralPath $summaryPath -Encoding utf8
Get-Content -LiteralPath $summaryPath

if ($overall -ne 'PASS') { exit 1 }
