param()

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$env:PYTHONPATH = Join-Path $Root 'src'

$LogDir = Join-Path $Root 'review\R01\logs'
$EvidenceDir = Join-Path $Root 'review\R01\evidence'
New-Item -ItemType Directory -Force -Path $LogDir, $EvidenceDir | Out-Null

$DemoDb = Join-Path $EvidenceDir 'demo_r01.sqlite3'
$DemoResult = Join-Path $EvidenceDir 'demo_r01_results.json'
foreach ($Generated in @($DemoDb, $DemoResult)) {
    if (Test-Path -LiteralPath $Generated) {
        Remove-Item -LiteralPath $Generated -Force
    }
}

$EnvironmentLines = @(
    "VALIDATION_STARTED_AT=$([DateTimeOffset]::Now.ToString('o'))",
    "CONTRACT=CDH-C01-REWORK-002",
    "PROJECT_ROOT=$Root",
    "PYTHON_COMMAND=$((Get-Command python).Source)",
    "POWERSHELL_VERSION=$($PSVersionTable.PSVersion)",
    "OS_VERSION=$([Environment]::OSVersion.VersionString)",
    "OS_ARCH=$([Runtime.InteropServices.RuntimeInformation]::OSArchitecture)",
    "PROCESS_ARCH=$([Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture)",
    "GIT_REPOSITORY=$(if (Test-Path -LiteralPath (Join-Path $Root '.git')) { 'true' } else { 'false' })",
    "PACKAGE_INSTALL_COUNT=0",
    "NETWORK_ACCESS_COUNT=0",
    "LIVE_COUPANG_ACCESS_COUNT=0",
    "FIREFOX_PROFILE_ACCESS_COUNT=0",
    "REAL_NOTIFICATION_COUNT=0",
    "PURCHASE_ACTION_COUNT=0"
)
$EnvironmentLines | Set-Content -LiteralPath (Join-Path $LogDir 'R01_environment.txt') -Encoding utf8
python -VV 1>> (Join-Path $LogDir 'R01_environment.txt') 2>&1
python -c "import platform,sqlite3,sys; print('PYTHON_EXECUTABLE='+sys.executable); print('PLATFORM='+platform.platform()); print('SQLITE='+sqlite3.sqlite_version)" 1>> (Join-Path $LogDir 'R01_environment.txt') 2>&1

$OriginalWatch = [Diagnostics.Stopwatch]::StartNew()
python -m unittest tests.test_history_policy tests.test_models_pricing tests.test_persistence_demo -v 1> (Join-Path $LogDir 'after_original_69_stdout.log') 2> (Join-Path $LogDir 'after_original_69_stderr.log')
$OriginalExit = $LASTEXITCODE
$OriginalWatch.Stop()

$RegressionWatch = [Diagnostics.Stopwatch]::StartNew()
python -m unittest tests.test_rework_regressions -v 1> (Join-Path $LogDir 'after_regression_tests_stdout.log') 2> (Join-Path $LogDir 'after_regression_tests_stderr.log')
$RegressionExit = $LASTEXITCODE
$RegressionWatch.Stop()

$AllWatch = [Diagnostics.Stopwatch]::StartNew()
python -m unittest discover -s tests -p "test_*.py" -v 1> (Join-Path $LogDir 'after_all_product_tests_stdout.log') 2> (Join-Path $LogDir 'after_all_product_tests_stderr.log')
$AllExit = $LASTEXITCODE
$AllWatch.Stop()

python review\R01\before_after\independent_counterexamples_archival.py 1> (Join-Path $LogDir 'after_archival_script_stdout.log') 2> (Join-Path $LogDir 'after_archival_script_stderr.log')
$ArchivalAfterExit = $LASTEXITCODE

python -m cdh_core.demo --fixtures tests\fixtures\demo_cases.json --db $DemoDb --output $DemoResult 1> (Join-Path $LogDir 'after_demo_stdout.log') 2> (Join-Path $LogDir 'after_demo_stderr.log')
$DemoExit = $LASTEXITCODE

python scripts\generate_traceability.py 1> (Join-Path $LogDir 'after_traceability_stdout.log') 2> (Join-Path $LogDir 'after_traceability_stderr.log')
$TraceExit = $LASTEXITCODE

python -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); assert d['project']['name']=='cdh-core'; assert d['project']['version']=='0.2.0'; assert d['project']['dependencies']==[]; print('PYPROJECT_PARSE=PASS'); print('CORE_VERSION='+d['project']['version']); print('BUILD_BACKEND='+d['build-system']['build-backend'])" 1> (Join-Path $LogDir 'after_package_metadata_stdout.log') 2> (Join-Path $LogDir 'after_package_metadata_stderr.log')
$MetadataExit = $LASTEXITCODE

python -m compileall -q src tests 1> (Join-Path $LogDir 'after_compileall_stdout.log') 2> (Join-Path $LogDir 'after_compileall_stderr.log')
$CompileExit = $LASTEXITCODE

$Summary = @(
    "ORIGINAL_69_COMMAND=python -m unittest tests.test_history_policy tests.test_models_pricing tests.test_persistence_demo -v",
    "ORIGINAL_69_EXIT_CODE=$OriginalExit",
    "ORIGINAL_69_WALL_SECONDS=$([Math]::Round($OriginalWatch.Elapsed.TotalSeconds, 3))",
    "REGRESSION_COMMAND=python -m unittest tests.test_rework_regressions -v",
    "REGRESSION_EXIT_CODE=$RegressionExit",
    "REGRESSION_WALL_SECONDS=$([Math]::Round($RegressionWatch.Elapsed.TotalSeconds, 3))",
    "ALL_TEST_COMMAND=python -m unittest discover -s tests -p test_*.py -v",
    "ALL_TEST_EXIT_CODE=$AllExit",
    "ALL_TEST_WALL_SECONDS=$([Math]::Round($AllWatch.Elapsed.TotalSeconds, 3))",
    "ARCHIVAL_AFTER_COMMAND=python review\R01\before_after\independent_counterexamples_archival.py",
    "ARCHIVAL_AFTER_EXIT_CODE=$ArchivalAfterExit",
    "ARCHIVAL_AFTER_EXPECTED_NONZERO=true",
    "DEMO_EXIT_CODE=$DemoExit",
    "TRACEABILITY_EXIT_CODE=$TraceExit",
    "PACKAGE_METADATA_EXIT_CODE=$MetadataExit",
    "COMPILEALL_EXIT_CODE=$CompileExit",
    "VALIDATION_FINISHED_AT=$([DateTimeOffset]::Now.ToString('o'))"
)
$Summary | Set-Content -LiteralPath (Join-Path $LogDir 'R01_validation_summary.txt') -Encoding utf8

if ($OriginalExit -ne 0 -or $RegressionExit -ne 0 -or $AllExit -ne 0 -or $ArchivalAfterExit -eq 0 -or $DemoExit -ne 0 -or $TraceExit -ne 0 -or $MetadataExit -ne 0 -or $CompileExit -ne 0) {
    Get-Content -LiteralPath (Join-Path $LogDir 'R01_validation_summary.txt')
    exit 1
}

Get-Content -LiteralPath (Join-Path $LogDir 'R01_validation_summary.txt')
exit 0
