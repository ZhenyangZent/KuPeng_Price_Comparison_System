function Get-CDHProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
}

function Get-CDHSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $algorithm = [System.Security.Cryptography.SHA256]::Create()
        try { return [System.BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $algorithm.Dispose() }
    } finally { $stream.Dispose() }
}

function Get-CDHPythonRuntime {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $candidates = New-Object System.Collections.Generic.List[object]
    $projectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $projectPython -PathType Leaf) {
        $candidates.Add([pscustomobject]@{ Executable = $projectPython; Prefix = @(); Source = 'PROJECT_VENV' })
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates.Add([pscustomobject]@{ Executable = 'py'; Prefix = @('-3'); Source = 'PY_LAUNCHER' })
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates.Add([pscustomobject]@{ Executable = 'python'; Prefix = @(); Source = 'PATH_PYTHON' })
    }

    $localPrograms = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\Python'
    if (Test-Path -LiteralPath $localPrograms -PathType Container) {
        Get-ChildItem -LiteralPath $localPrograms -Directory -Filter 'Python*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $executable = Join-Path $_.FullName 'python.exe'
                if (Test-Path -LiteralPath $executable -PathType Leaf) {
                    $candidates.Add([pscustomobject]@{ Executable = $executable; Prefix = @(); Source = 'STANDARD_USER_INSTALL' })
                }
            }
    }

    $tooOld = New-Object System.Collections.Generic.List[string]
    foreach ($runtime in $candidates) {
        $prefix = @($runtime.Prefix)
        $savedPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $versionText = @(& $runtime.Executable @prefix -c 'import sys; print(sys.version_info[0],sys.version_info[1],sys.version_info[2])' 2>$null)
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedPreference
        }
        if ($exitCode -ne 0 -or -not $versionText) { continue }
        try {
            $parts = (($versionText | Select-Object -Last 1).ToString().Trim() -split '\s+')
            if ($parts.Count -ne 3) { continue }
            $version = [version]("$($parts[0]).$($parts[1]).$($parts[2])")
        } catch { continue }
        if ($version -lt [version]'3.11.0') {
            $tooOld.Add("$($runtime.Source)=$version")
            continue
        }
        $runtime | Add-Member -NotePropertyName Version -NotePropertyValue $version.ToString()
        return $runtime
    }
    if ($tooOld.Count) { throw "PYTHON_TOO_OLD: $($tooOld -join ', '); Python 3.11 or newer is required." }
    throw 'PYTHON_NOT_FOUND: install Python 3.11 or newer, or create the project-local .venv.'
}

function Test-CDHTrialInputs {
    param([Parameter(Mandatory = $true)][string]$BundleRoot)

    $manifestPath = Join-Path $BundleRoot 'A17_RUNTIME_MANIFEST.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "A17_RUNTIME_MANIFEST_MISSING: $manifestPath"
    }
    try { $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "A17_RUNTIME_MANIFEST_INVALID: $($_.Exception.Message)" }
    if ($manifest.schema_version -ne 'CDH-A17-RUNTIME-BUNDLE-MANIFEST-1') {
        throw "A17_RUNTIME_MANIFEST_SCHEMA_MISMATCH: $($manifest.schema_version)"
    }
    $seen = @{}
    foreach ($entry in @($manifest.files)) {
        $relative = [string]$entry.path
        if (-not $relative -or [IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)' -or $seen.ContainsKey($relative)) {
            throw "A17_RUNTIME_MANIFEST_PATH_INVALID_OR_DUPLICATE: $relative"
        }
        $seen[$relative] = $true
        $path = Join-Path (Join-Path $BundleRoot 'vendor') $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "A17_RUNTIME_FILE_MISSING: $relative" }
        $item = Get-Item -LiteralPath $path
        if ($item.Length -ne [int64]$entry.size) { throw "A17_RUNTIME_FILE_SIZE_MISMATCH: $relative" }
        $actual = Get-CDHSha256 -Path $path
        if ($actual -ne [string]$entry.sha256) { throw "A17_RUNTIME_FILE_SHA256_MISMATCH: $relative" }
    }
    $actualFiles = @(Get-ChildItem -LiteralPath (Join-Path $BundleRoot 'vendor') -File -Recurse | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc' })
    if ($actualFiles.Count -ne $seen.Count) {
        throw "A17_RUNTIME_UNDECLARED_FILE: expected=$($seen.Count) actual=$($actualFiles.Count)"
    }
}

function Invoke-CDHMvpControl {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('start', 'status', 'stop')][string]$Action,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)]$Runtime,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$StateDir,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][string]$PrivateDataRoot
    )

    $control = Join-Path $BundleRoot 'control.py'
    if (-not (Test-Path -LiteralPath $control -PathType Leaf)) {
        throw "CONTROL_ENTRY_MISSING: $control"
    }
    $arguments = @(
        $control, $Action,
        '--project-root', $ProjectRoot,
        '--bundle-root', $BundleRoot,
        '--port', $Port.ToString(),
        '--state-dir', $StateDir,
        '--runtime-root', $RuntimeRoot,
        '--log-dir', $LogDir,
        '--private-data-root', $PrivateDataRoot
    )
    $prefix = @($Runtime.Prefix)
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $Runtime.Executable @prefix @arguments 2>&1 | ForEach-Object { $_.ToString() })
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }

    $payload = $null
    foreach ($line in ($lines | Select-Object -Last 5)) {
        try {
            $candidate = $line | ConvertFrom-Json -ErrorAction Stop
            if ($candidate.status) { $payload = $candidate }
        } catch { }
    }
    return [pscustomobject]@{ ExitCode = $exitCode; Payload = $payload; Lines = $lines }
}

function Write-CDHMachineResult {
    param([Parameter(Mandatory = $true)]$Result)
    if ($Result.Payload) {
        $Result.Payload | ConvertTo-Json -Compress -Depth 8
    } else {
        [pscustomobject]@{ status = 'FAILED'; error = ($Result.Lines -join [Environment]::NewLine) } | ConvertTo-Json -Compress
    }
}
