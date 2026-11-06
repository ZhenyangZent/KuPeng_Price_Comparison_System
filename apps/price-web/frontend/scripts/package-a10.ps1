param(
  [ValidateSet('R07','R08')]
  [string]$Round = 'R07'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
if ($Round -eq 'R08') {
  $DeliveryName = 'CDH_A_R08_001_REVIEW'
  $ReviewFolder = 'A10_R08'
  $ContractBundle = 'UNIFIED_CONTINUOUS_20261105_R08'
  $ContractFiles = @('00_START_HERE.md','01_SHARED_RULES.md','02_CENTRAL_REVIEW_R07.md','03_CANONICAL_DEPENDENCIES.md','04_COMMON_START_TEXT.md','ASSIGNMENTS.json','RECEIPT_ACK.json','MANIFEST.json')
  $ManifestSchema = 'CDH-A10-R08-CONTINUATION-REVIEW-MANIFEST-1'
  $TaskId = 'CDH-A10-CONTINUE-R07'
  $Authority = 'R08_BOUNDED_OFFLINE_SYNTHETIC_A_CONTINUATION_ONLY'
  $InputSha = '61d75b334fd7073202691bab887186261c85d1fa42af05e79f16d1a46f24b144'
} else {
  $DeliveryName = 'CDH_A_R07_001_REVIEW'
  $ReviewFolder = 'A10'
  $ContractBundle = 'UNIFIED_CONTINUOUS_20261105_R07'
  $ContractFiles = @('00_START_HERE.md','01_SHARED_BOUNDARIES.md','02_R06_INDEPENDENT_FINDINGS.md','03_R07_CANONICAL_WIRE_DECISION.md','ASSIGNMENTS.json','MANIFEST.json')
  $ManifestSchema = 'CDH-A10-R07-REVIEW-MANIFEST-1'
  $TaskId = 'CDH-A10-B10-ACTUAL-API-UI-INTEGRATION-001'
  $Authority = 'AUTHORIZED_SYNTHETIC_OFFLINE_R07_A_ONLY'
  $InputSha = '76b1332c3e2cd82a05e5f26e6d3e0c01cdf65e828f82d5b586902bdfacda2827'
}
$ReviewRoot = Join-Path $ProjectRoot "review\$ReviewFolder"
$PackageRoot = Join-Path $ReviewRoot "package\$DeliveryName"
$VerifyRoot = Join-Path $ReviewRoot 'verify_extracted'
$Release = Join-Path $ProjectRoot "review\releases\$DeliveryName.zip"
$Queue = Join-Path $ProjectRoot "review\00_TO_UPLOAD\$DeliveryName.zip"
$B10Archive = Join-Path $ProjectRoot 'review\releases\CDH_B_R06_001_REVIEW.zip'
$B11Archive = Join-Path $ProjectRoot 'review\releases\CDH_B_R07_001_REVIEW.zip'

foreach ($ArchiveGate in @(
  @{ Path = $B10Archive; Sha = 'dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549' },
  @{ Path = $B11Archive; Sha = '6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a' }
)) {
  if (-not (Test-Path -LiteralPath $ArchiveGate.Path -PathType Leaf)) { throw "Missing pinned upstream: $($ArchiveGate.Path)" }
  $Actual = (Get-FileHash -LiteralPath $ArchiveGate.Path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($Actual -ne $ArchiveGate.Sha) { throw "Pinned upstream hash mismatch: $($ArchiveGate.Path)" }
}

foreach ($Target in @($PackageRoot, $VerifyRoot)) {
  $Full = [IO.Path]::GetFullPath($Target)
  if (-not $Full.StartsWith([IO.Path]::GetFullPath($ReviewRoot), [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe cleanup target: $Full" }
  if (Test-Path -LiteralPath $Full) { Remove-Item -LiteralPath $Full -Recurse -Force }
}
foreach ($Target in @($Release, $Queue)) {
  if (Test-Path -LiteralPath $Target) { throw "Refusing to overwrite existing delivery: $Target" }
}

New-Item -ItemType Directory -Path @($PackageRoot, (Split-Path $Release), (Split-Path $Queue)) -Force | Out-Null
$FrontendDestination = Join-Path $PackageRoot 'apps\price-web\frontend'
New-Item -ItemType Directory -Path $FrontendDestination -Force | Out-Null
$FrontendFiles = @(
  'index.html','package.json','package-lock.json','README.md','tsconfig.json','tsconfig.app.json','tsconfig.node.json',
  'vite.config.ts','vite.role.config.ts','vite.a08.config.ts','vite.a09.config.ts','vite.a10.config.ts'
)
foreach ($Name in $FrontendFiles) {
  Copy-Item -LiteralPath (Join-Path $ProjectRoot "apps\price-web\frontend\$Name") -Destination (Join-Path $FrontendDestination $Name)
}
foreach ($Name in @('src','tests','scripts','upstream')) {
  Copy-Item -LiteralPath (Join-Path $ProjectRoot "apps\price-web\frontend\$Name") -Destination $FrontendDestination -Recurse
}

$RoleParent = Join-Path $PackageRoot 'tests\web'
New-Item -ItemType Directory -Path $RoleParent -Force | Out-Null
foreach ($Role in @('frontend_a07','frontend_a08','frontend_a09','frontend_a10')) {
  Copy-Item -LiteralPath (Join-Path $ProjectRoot "tests\web\$Role") -Destination $RoleParent -Recurse
}

$ReportDestination = Join-Path $PackageRoot 'reports\A10'
New-Item -ItemType Directory -Path $ReportDestination -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'reports\A10') -Force |
  Where-Object { $_.Name -notin @('headless_runtime','test_tmp','test_tmp_a07_role','test_tmp_a08_role','test_tmp_a09_role','test_tmp_a10_role','b10_release_extract','b11_release_extract') } |
  Copy-Item -Destination $ReportDestination -Recurse

$ContractDestination = Join-Path $PackageRoot 'input_contract'
New-Item -ItemType Directory -Path (Join-Path $ContractDestination 'ROLES') -Force | Out-Null
$ContractRoot = Join-Path $ProjectRoot "input\orchestrator_bundles\$ContractBundle\extracted"
foreach ($Name in $ContractFiles) {
  Copy-Item -LiteralPath (Join-Path $ContractRoot $Name) -Destination (Join-Path $ContractDestination $Name)
}
Copy-Item -LiteralPath (Join-Path $ContractRoot 'ROLES\A.md') -Destination (Join-Path $ContractDestination 'ROLES\A.md')
Copy-Item -LiteralPath (Join-Path $ContractRoot 'EVIDENCE') -Destination $ContractDestination -Recurse
if ($Round -eq 'R08') {
  $R07Evidence = Join-Path $ProjectRoot 'input\orchestrator_bundles\UNIFIED_CONTINUOUS_20261105_R07\extracted\EVIDENCE'
  foreach ($Name in @('A09_B10_PARSER_ACTUAL.txt','B10_REAL_SEARCH.json','B10_REAL_DETAIL.json')) {
    Copy-Item -LiteralPath (Join-Path $R07Evidence $Name) -Destination (Join-Path $ContractDestination 'EVIDENCE')
  }
}

$UpstreamArchiveDestination = Join-Path $PackageRoot 'upstream_archives'
New-Item -ItemType Directory -Path $UpstreamArchiveDestination -Force | Out-Null
Copy-Item -LiteralPath $B10Archive -Destination $UpstreamArchiveDestination
Copy-Item -LiteralPath $B11Archive -Destination $UpstreamArchiveDestination

# Execute the full suite from the staged handoff tree. Only node_modules is a
# temporary junction to the already-installed local dependency tree; it is
# removed before manifest generation and never enters the archive.
$StagedNodeModules = Join-Path $FrontendDestination 'node_modules'
$SourceNodeModules = Join-Path $ProjectRoot 'apps\price-web\frontend\node_modules'
if (-not (Test-Path -LiteralPath $SourceNodeModules -PathType Container)) { throw 'Source node_modules is unavailable for staged replay' }
$ReplayLog = Join-Path $ReportDestination 'evidence\STAGED_HANDOFF_REPLAY.log'
cmd.exe /c "mklink /J `"$StagedNodeModules`" `"$SourceNodeModules`"" | Out-Null
try {
  Push-Location $FrontendDestination
  try {
    & npm.cmd run validate:a10 2>&1 | Tee-Object -FilePath $ReplayLog
    $ReplayExit = $LASTEXITCODE
  } finally { Pop-Location }
} finally {
  if (Test-Path -LiteralPath $StagedNodeModules) { cmd.exe /c "rmdir `"$StagedNodeModules`"" | Out-Null }
}
if ($ReplayExit -ne 0) { throw "Staged handoff replay failed with exit $ReplayExit" }

# Browser profiles, generated SQLite files and empty role-test scratch folders
# are execution temporaries, not review payloads. Resolve and constrain every
# deletion to this staged package before removing them.
$StagedPackageRoot = [IO.Path]::GetFullPath($PackageRoot) + [IO.Path]::DirectorySeparatorChar
foreach ($Temporary in @('reports\A10\headless_runtime','reports\A10\test_tmp_a10_role','node_modules')) {
  $TemporaryPath = [IO.Path]::GetFullPath((Join-Path $PackageRoot $Temporary))
  if (-not $TemporaryPath.StartsWith($StagedPackageRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe staged cleanup target: $TemporaryPath" }
  if (Test-Path -LiteralPath $TemporaryPath) { Remove-Item -LiteralPath $TemporaryPath -Recurse -Force }
}

$ReplayResult = [ordered]@{
  schema_version = 'CDH-A10-STAGED-REPLAY-1'
  command = 'npm run validate:a10'
  exit_code = $ReplayExit
  source_node_modules_junction_removed = (-not (Test-Path -LiteralPath $StagedNodeModules))
  result = 'PASS'
}
$ReplayResult | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $ReportDestination 'evidence\STAGED_HANDOFF_REPLAY.json') -Encoding UTF8

$Payload = Get-ChildItem -LiteralPath $PackageRoot -Recurse -File | Sort-Object FullName
$Entries = foreach ($File in $Payload) {
  [ordered]@{
    path = $File.FullName.Substring($PackageRoot.Length + 1).Replace('\','/')
    size = $File.Length
    sha256 = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}
$Manifest = [ordered]@{
  schema_version = $ManifestSchema
  task_id = $TaskId
  parent_task_id = 'CDH-A10-B10-ACTUAL-API-UI-INTEGRATION-001'
  authority = $Authority
  input_zip_sha256 = $InputSha
  b10_release_sha256 = 'dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549'
  b11_release_sha256 = '6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a'
  generated_at_utc = [DateTime]::UtcNow.ToString('o')
  payload_count = $Entries.Count
  files = $Entries
}
$Manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $PackageRoot 'MANIFEST.json') -Encoding UTF8

Compress-Archive -LiteralPath $PackageRoot -DestinationPath $Release -CompressionLevel Optimal
Copy-Item -LiteralPath $Release -Destination $Queue
Expand-Archive -LiteralPath $Release -DestinationPath $VerifyRoot
$ExtractedRoot = Join-Path $VerifyRoot $DeliveryName
$ReadManifest = Get-Content -Raw -LiteralPath (Join-Path $ExtractedRoot 'MANIFEST.json') | ConvertFrom-Json

$Mismatch = @()
foreach ($Entry in $ReadManifest.files) {
  $Path = Join-Path $ExtractedRoot ($Entry.path.Replace('/','\'))
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { $Mismatch += "missing:$($Entry.path)"; continue }
  $Item = Get-Item -LiteralPath $Path
  if ($Item.Length -ne [int64]$Entry.size) { $Mismatch += "size:$($Entry.path)" }
  $Hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($Hash -ne $Entry.sha256) { $Mismatch += "hash:$($Entry.path)" }
}
$ActualPayload = Get-ChildItem -LiteralPath $ExtractedRoot -Recurse -File |
  ForEach-Object { $_.FullName.Substring($ExtractedRoot.Length + 1).Replace('\','/') } |
  Where-Object { $_ -ne 'MANIFEST.json' }
$Undeclared = @($ActualPayload | Where-Object { $_ -notin @($ReadManifest.files.path) })
$CaseCollisions = @($ActualPayload | Group-Object { $_.ToLowerInvariant() } | Where-Object Count -gt 1)
$Symlinks = @(Get-ChildItem -LiteralPath $ExtractedRoot -Recurse -Force | Where-Object { $_.LinkType })
$SensitiveNames = @($ActualPayload | Where-Object { [IO.Path]::GetFileName($_) -match '^\.env($|\.)' -and [IO.Path]::GetFileName($_) -ne '.env.example' })

$Archive = [IO.Compression.ZipFile]::OpenRead($Release)
try {
  $Unsafe = @($Archive.Entries | Where-Object { $_.FullName -match '(^|/|\\)\.\.(/|\\)' -or [IO.Path]::IsPathRooted($_.FullName) })
  $ArchiveCaseCollisions = @($Archive.Entries | Group-Object { $_.FullName.ToLowerInvariant() } | Where-Object Count -gt 1)
  foreach ($Entry in $Archive.Entries | Where-Object { -not [String]::IsNullOrEmpty($_.Name) }) {
    $Stream = $Entry.Open()
    try { $Buffer = New-Object byte[] 8192; while ($Stream.Read($Buffer, 0, $Buffer.Length) -gt 0) {} } finally { $Stream.Dispose() }
  }
  $EntryCount = $Archive.Entries.Count
} finally { $Archive.Dispose() }

$ReleaseHash = (Get-FileHash -LiteralPath $Release -Algorithm SHA256).Hash.ToLowerInvariant()
$QueueHash = (Get-FileHash -LiteralPath $Queue -Algorithm SHA256).Hash.ToLowerInvariant()
$ManifestHash = (Get-FileHash -LiteralPath (Join-Path $ExtractedRoot 'MANIFEST.json') -Algorithm SHA256).Hash.ToLowerInvariant()
$Result = [ordered]@{
  release = $Release
  queue = $Queue
  release_size = (Get-Item -LiteralPath $Release).Length
  sha256 = $ReleaseHash
  queue_sha256 = $QueueHash
  byte_identical = ($ReleaseHash -eq $QueueHash)
  payload_count = $ReadManifest.payload_count
  manifest_sha256 = $ManifestHash
  manifest_mismatch_count = $Mismatch.Count
  undeclared_count = $Undeclared.Count
  unsafe_entry_count = $Unsafe.Count
  case_collision_count = $CaseCollisions.Count + $ArchiveCaseCollisions.Count
  symlink_count = $Symlinks.Count
  sensitive_filename_count = $SensitiveNames.Count
  zip_entry_count = $EntryCount
  crc_read = 'PASS'
  staged_replay = 'PASS'
  pass = ($Mismatch.Count -eq 0 -and $Undeclared.Count -eq 0 -and $Unsafe.Count -eq 0 -and $CaseCollisions.Count -eq 0 -and $ArchiveCaseCollisions.Count -eq 0 -and $Symlinks.Count -eq 0 -and $SensitiveNames.Count -eq 0 -and $ReleaseHash -eq $QueueHash)
}
$Result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $ReviewRoot 'PACKAGE_VERIFICATION.json') -Encoding UTF8
$Result | ConvertTo-Json -Compress
if (-not $Result.pass) { exit 1 }
