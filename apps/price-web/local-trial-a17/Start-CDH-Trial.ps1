[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 4174,
    [string]$StateDir = '',
    [string]$RuntimeRoot = '',
    [string]$LogDir = '',
    [string]$PrivateDataRoot = '',
    [switch]$MachineReadable
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
. (Join-Path $PSScriptRoot 'CDH-Trial.Common.ps1')

try {
    $projectRoot = Get-CDHProjectRoot
    $bundleRoot = $PSScriptRoot
    if (-not $StateDir) { $StateDir = Join-Path $projectRoot 'data\A17_trial\state' }
    if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $projectRoot 'data\A17_trial\runtime' }
    if (-not $LogDir) { $LogDir = Join-Path $projectRoot 'logs\A17' }
    if (-not $PrivateDataRoot) { $PrivateDataRoot = Join-Path $projectRoot 'data\A17_private_history' }

    $runtime = Get-CDHPythonRuntime -ProjectRoot $projectRoot
    Test-CDHTrialInputs -BundleRoot $bundleRoot
    $result = Invoke-CDHMvpControl -Action start -ProjectRoot $projectRoot -BundleRoot $bundleRoot -Runtime $runtime -Port $Port -StateDir $StateDir -RuntimeRoot $RuntimeRoot -LogDir $LogDir -PrivateDataRoot $PrivateDataRoot

    if ($MachineReadable) { Write-CDHMachineResult -Result $result }
    elseif ($result.ExitCode -eq 0 -and $result.Payload.status -in @('READY', 'ALREADY_RUNNING')) {
        Write-Host ''
        Write-Host 'Coupang Deal Hunter Windows trial is ready.' -ForegroundColor Green
        Write-Host "URL: $($result.Payload.url)" -ForegroundColor Cyan
        Write-Host "Python: $($runtime.Version) ($($runtime.Source))"
        Write-Host "Private data: $PrivateDataRoot"
        Write-Host 'Paste the URL into a browser. The launcher does not open a browser or contact Coupang.'
        Write-Host 'Run Stop-CDH-Trial.cmd when finished.'
    } else {
        $detail = if ($result.Payload.error) { $result.Payload.error } else { $result.Lines -join [Environment]::NewLine }
        throw "LOCAL_MVP_START_FAILED: $detail"
    }
    exit $result.ExitCode
} catch {
    if ($MachineReadable) {
        [pscustomobject]@{ status = 'FAILED'; error = $_.Exception.Message } | ConvertTo-Json -Compress
    } else {
        Write-Host ''
        Write-Host 'The local site did not start.' -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        Write-Host 'See README_FIRST_USE.md in this folder for troubleshooting.'
    }
    exit 2
}
