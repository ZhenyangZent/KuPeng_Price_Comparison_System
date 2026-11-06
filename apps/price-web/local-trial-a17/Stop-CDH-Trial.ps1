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
    $result = Invoke-CDHMvpControl -Action stop -ProjectRoot $projectRoot -BundleRoot $bundleRoot -Runtime $runtime -Port $Port -StateDir $StateDir -RuntimeRoot $RuntimeRoot -LogDir $LogDir -PrivateDataRoot $PrivateDataRoot
    if ($MachineReadable) { Write-CDHMachineResult -Result $result }
    elseif ($result.ExitCode -eq 0 -and $result.Payload.status -in @('STOPPED', 'ALREADY_STOPPED')) {
        Write-Host ''
        Write-Host 'Coupang Deal Hunter local site is stopped.' -ForegroundColor Green
        Write-Host 'Private history remains in the project and is available after the next start.'
    } else {
        $detail = if ($result.Payload.error) { $result.Payload.error } else { $result.Lines -join [Environment]::NewLine }
        throw "LOCAL_MVP_STOP_FAILED: $detail"
    }
    exit $result.ExitCode
} catch {
    if ($MachineReadable) { [pscustomobject]@{ status = 'FAILED'; error = $_.Exception.Message } | ConvertTo-Json -Compress }
    else {
        Write-Host 'The site was not safely stopped.' -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        Write-Host 'The tool will not kill an unknown PID. Preserve the state files for manual review.'
    }
    exit 2
}
