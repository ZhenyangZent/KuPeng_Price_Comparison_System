param()

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$env:PYTHONPATH = Join-Path $Root 'src'

$LogDir = Join-Path $Root 'logs'
$EvidenceDir = Join-Path $Root 'review\C01\evidence'
New-Item -ItemType Directory -Force -Path $LogDir, $EvidenceDir | Out-Null

$DemoDb = Join-Path $EvidenceDir 'demo.sqlite3'
$DemoResult = Join-Path $EvidenceDir 'demo_results.json'
foreach ($Generated in @($DemoDb, $DemoResult)) {
    if (Test-Path -LiteralPath $Generated) {
        Remove-Item -LiteralPath $Generated -Force
    }
}

$EnvironmentLines = @(
    "VALIDATION_STARTED_AT=$([DateTimeOffset]::Now.ToString('o'))",
    "PROJECT_ROOT=$Root",
    "PYTHON_COMMAND=$((Get-Command python).Source)",
    "POWERSHELL_VERSION=$($PSVersionTable.PSVersion)",
    "OS_VERSION=$([Environment]::OSVersion.VersionString)",
    "OS_ARCH=$([Runtime.InteropServices.RuntimeInformation]::OSArchitecture)",
    "PROCESS_ARCH=$([Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture)",
    "GIT_REPOSITORY=$(if (Test-Path -LiteralPath (Join-Path $Root '.git')) { 'true' } else { 'false' })",
    "PACKAGE_INSTALL_COUNT=0",
    "NETWORK_ACCESS_COUNT=0"
)
$EnvironmentLines | Set-Content -LiteralPath (Join-Path $LogDir 'C01_environment.txt') -Encoding utf8
python -VV 1>> (Join-Path $LogDir 'C01_environment.txt') 2>&1
python -c "import platform, sqlite3, sys; print('PYTHON_EXECUTABLE=' + sys.executable); print('PLATFORM=' + platform.platform()); print('SQLITE=' + sqlite3.sqlite_version)" 1>> (Join-Path $LogDir 'C01_environment.txt') 2>&1

$TestWatch = [Diagnostics.Stopwatch]::StartNew()
python -m unittest discover -s tests -v 1> (Join-Path $LogDir 'product_tests_stdout.log') 2> (Join-Path $LogDir 'product_tests_stderr.log')
$TestExit = $LASTEXITCODE
$TestWatch.Stop()

$DemoWatch = [Diagnostics.Stopwatch]::StartNew()
python -m cdh_core.demo --fixtures tests\fixtures\demo_cases.json --db $DemoDb --output $DemoResult 1> (Join-Path $LogDir 'demo_stdout.log') 2> (Join-Path $LogDir 'demo_stderr.log')
$DemoExit = $LASTEXITCODE
$DemoWatch.Stop()

python scripts\generate_traceability.py 1> (Join-Path $LogDir 'traceability_stdout.log') 2> (Join-Path $LogDir 'traceability_stderr.log')
$TraceExit = $LASTEXITCODE

python -c "import pathlib,tomllib; p=pathlib.Path('pyproject.toml'); d=tomllib.loads(p.read_text(encoding='utf-8')); assert d['project']['name']=='cdh-core'; assert d['project']['dependencies']==[]; print('PYPROJECT_PARSE=PASS'); print('BUILD_BACKEND=' + d['build-system']['build-backend'])" 1> (Join-Path $LogDir 'package_metadata_stdout.log') 2> (Join-Path $LogDir 'package_metadata_stderr.log')
$MetadataExit = $LASTEXITCODE

python -m compileall -q src 1> (Join-Path $LogDir 'compileall_stdout.log') 2> (Join-Path $LogDir 'compileall_stderr.log')
$CompileExit = $LASTEXITCODE

$Summary = @(
    "TEST_COMMAND=python -m unittest discover -s tests -v",
    "TEST_EXIT_CODE=$TestExit",
    "TEST_WALL_SECONDS=$([Math]::Round($TestWatch.Elapsed.TotalSeconds, 3))",
    "DEMO_COMMAND=python -m cdh_core.demo --fixtures tests\\fixtures\\demo_cases.json --db review\\C01\\evidence\\demo.sqlite3 --output review\\C01\\evidence\\demo_results.json",
    "DEMO_EXIT_CODE=$DemoExit",
    "DEMO_WALL_SECONDS=$([Math]::Round($DemoWatch.Elapsed.TotalSeconds, 3))",
    "TRACEABILITY_EXIT_CODE=$TraceExit",
    "PACKAGE_METADATA_EXIT_CODE=$MetadataExit",
    "COMPILEALL_EXIT_CODE=$CompileExit",
    "VALIDATION_FINISHED_AT=$([DateTimeOffset]::Now.ToString('o'))"
)
$Summary | Set-Content -LiteralPath (Join-Path $LogDir 'C01_validation_summary.txt') -Encoding utf8

if ($TestExit -ne 0 -or $DemoExit -ne 0 -or $TraceExit -ne 0 -or $MetadataExit -ne 0 -or $CompileExit -ne 0) {
    Get-Content -LiteralPath (Join-Path $LogDir 'C01_validation_summary.txt')
    exit 1
}

Get-Content -LiteralPath (Join-Path $LogDir 'C01_validation_summary.txt')
exit 0

