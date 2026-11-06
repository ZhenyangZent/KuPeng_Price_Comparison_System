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
    $result = Invoke-CDHMvpControl -Action status -ProjectRoot $projectRoot -BundleRoot $bundleRoot -Runtime $runtime -Port $Port -StateDir $StateDir -RuntimeRoot $RuntimeRoot -LogDir $LogDir -PrivateDataRoot $PrivateDataRoot
    if ($MachineReadable) { Write-CDHMachineResult -Result $result }
    elseif ($result.Payload.status -eq 'READY') {
        Write-Host "Site is running: $($result.Payload.url)" -ForegroundColor Green
    } elseif ($result.Payload.status -eq 'STOPPED') {
        Write-Host 'Site is not running.' -ForegroundColor Yellow
    } else {
        Write-Host "Manual review required: $($result.Payload.status)" -ForegroundColor Red
        if ($result.Payload.receipt) { Write-Host "Receipt: $($result.Payload.receipt)" }
    }
    if ($result.Payload.status -eq 'STOPPED' -and $result.ExitCode -eq 3) { exit 0 }
    exit $result.ExitCode
} catch {
    if ($MachineReadable) { [pscustomobject]@{ status = 'FAILED'; error = $_.Exception.Message } | ConvertTo-Json -Compress }
    else { Write-Host $_.Exception.Message -ForegroundColor Red }
    exit 2
}
