$script:CDHExpectedReleases = @(
    [pscustomobject]@{ Name = 'A10 R08'; File = 'CDH_A_R08_001_REVIEW.zip'; Sha256 = '0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd' },
    [pscustomobject]@{ Name = 'B11 R07'; File = 'CDH_B_R07_001_REVIEW.zip'; Sha256 = '6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a' },
    [pscustomobject]@{ Name = 'B13 R09'; File = 'CDH_B_R09_001_REVIEW.zip'; Sha256 = 'aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638' },
    [pscustomobject]@{ Name = 'B14 R10'; File = 'CDH_B_R10_001_REVIEW.zip'; Sha256 = 'db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9' },
    [pscustomobject]@{ Name = 'C11 REV2 R10'; File = 'CDH_C_R10_002_REVIEW.zip'; Sha256 = '9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa' },
    [pscustomobject]@{ Name = 'A14 R11'; File = 'CDH_A_R11_004_REVIEW.zip'; Sha256 = '19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160' },
    [pscustomobject]@{ Name = 'B15 REV2'; File = 'CDH_B_R11_002_REVIEW.zip'; Sha256 = '48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe' },
    [pscustomobject]@{ Name = 'B16 REV3'; File = 'CDH_B_R12_003_REVIEW.zip'; Sha256 = 'f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7' }
)

function Get-CDHProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
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

function Test-CDHMvpInputs {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $releaseRoot = Join-Path $ProjectRoot 'review\releases'
    foreach ($release in $script:CDHExpectedReleases) {
        $path = Join-Path $releaseRoot $release.File
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "PINNED_RELEASE_MISSING: $($release.Name) is missing at $path"
        }
        $actual = Get-CDHSha256 -Path $path
        if ($actual -ne $release.Sha256) {
            throw "PINNED_RELEASE_SHA256_MISMATCH: $($release.Name) expected=$($release.Sha256) actual=$actual"
        }
    }

    $distIndex = Join-Path $ProjectRoot 'apps\price-web\frontend\dist\index.html'
    $distManifest = Join-Path $ProjectRoot 'apps\price-web\frontend\dist\A11_DIST_MANIFEST.json'
    if (-not (Test-Path -LiteralPath $distIndex -PathType Leaf) -or -not (Test-Path -LiteralPath $distManifest -PathType Leaf)) {
        throw 'FRONTEND_BUILD_MISSING: dist/index.html or dist/A11_DIST_MANIFEST.json is missing.'
    }
}

function Invoke-CDHMvpControl {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('start', 'status', 'stop')][string]$Action,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)]$Runtime,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$StateDir,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][string]$PrivateDataRoot
    )

    $control = Join-Path $ProjectRoot 'apps\price-web\local-preview-a11\control.py'
    if (-not (Test-Path -LiteralPath $control -PathType Leaf)) {
        throw "CONTROL_ENTRY_MISSING: $control"
    }
    $arguments = @(
        $control, $Action,
        '--project-root', $ProjectRoot,
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
