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
. (Join-Path $PSScriptRoot 'CDH-Mvp.Common.ps1')

try {
    $projectRoot = Get-CDHProjectRoot
    if (-not $StateDir) { $StateDir = Join-Path $projectRoot 'data\local_mvp\state' }
    if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $projectRoot 'data\local_mvp\runtime' }
    if (-not $LogDir) { $LogDir = Join-Path $projectRoot 'logs\A16' }
    if (-not $PrivateDataRoot) { $PrivateDataRoot = Join-Path $projectRoot 'data\private_user_observations_b15' }

    $runtime = Get-CDHPythonRuntime -ProjectRoot $projectRoot
    Test-CDHMvpInputs -ProjectRoot $projectRoot
    $result = Invoke-CDHMvpControl -Action start -ProjectRoot $projectRoot -Runtime $runtime -Port $Port -StateDir $StateDir -RuntimeRoot $RuntimeRoot -LogDir $LogDir -PrivateDataRoot $PrivateDataRoot

    if ($MachineReadable) { Write-CDHMachineResult -Result $result }
    elseif ($result.ExitCode -eq 0 -and $result.Payload.status -in @('READY', 'ALREADY_RUNNING')) {
        Write-Host ''
        Write-Host 'Coupang Deal Hunter local price-history site is ready.' -ForegroundColor Green
        Write-Host "URL: $($result.Payload.url)" -ForegroundColor Cyan
        Write-Host "Python: $($runtime.Version) ($($runtime.Source))"
        Write-Host "Private data: $PrivateDataRoot"
        Write-Host 'Paste the URL into a browser. The launcher does not open a browser or contact Coupang.'
        Write-Host 'Run Stop-CDH-MVP.cmd when finished.'
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
        Write-Host 'See docs\user-guides\WINDOWS_LOCAL_MVP_FIRST_USE.md for troubleshooting.'
    }
    exit 2
}
