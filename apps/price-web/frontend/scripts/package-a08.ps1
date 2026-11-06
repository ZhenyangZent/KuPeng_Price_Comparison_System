$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$ReviewRoot = Join-Path $ProjectRoot 'review\A08'
$PackageRoot = Join-Path $ReviewRoot 'package\CDH_A08_001_REVIEW'
$VerifyRoot = Join-Path $ReviewRoot 'verify_extracted'
$Release = Join-Path $ProjectRoot 'review\releases\CDH_A08_001_REVIEW.zip'
$Queue = Join-Path $ProjectRoot 'review\00_TO_UPLOAD\CDH_A08_001_REVIEW.zip'
foreach ($Target in @($PackageRoot, $VerifyRoot)) {
  $Full=[IO.Path]::GetFullPath($Target)
  if(-not $Full.StartsWith([IO.Path]::GetFullPath($ReviewRoot),[StringComparison]::OrdinalIgnoreCase)){throw "Unsafe cleanup target: $Full"}
  if(Test-Path -LiteralPath $Full){Remove-Item -LiteralPath $Full -Recurse -Force}
}
foreach($Target in @($Release,$Queue)){if(Test-Path -LiteralPath $Target){throw "Refusing to overwrite existing release: $Target"}}
New-Item -ItemType Directory -Path @($PackageRoot,(Split-Path $Release),(Split-Path $Queue)) -Force|Out-Null
$FrontendDestination=Join-Path $PackageRoot 'apps\price-web\frontend';New-Item -ItemType Directory -Path $FrontendDestination -Force|Out-Null
$FrontendFiles=@('index.html','package.json','package-lock.json','README.md','tsconfig.json','tsconfig.app.json','tsconfig.node.json','vite.config.ts','vite.role.config.ts','vite.a08.config.ts')
foreach($Name in $FrontendFiles){Copy-Item -LiteralPath (Join-Path $ProjectRoot "apps\price-web\frontend\$Name") -Destination (Join-Path $FrontendDestination $Name)}
foreach($Name in @('src','tests','scripts')){Copy-Item -LiteralPath (Join-Path $ProjectRoot "apps\price-web\frontend\$Name") -Destination $FrontendDestination -Recurse}
foreach($Role in @('frontend_a07','frontend_a08')){$Parent=Join-Path $PackageRoot 'tests\web';New-Item -ItemType Directory -Path $Parent -Force|Out-Null;Copy-Item -LiteralPath (Join-Path $ProjectRoot "tests\web\$Role") -Destination $Parent -Recurse}
$ReportDestination=Join-Path $PackageRoot 'reports\A08';New-Item -ItemType Directory -Path $ReportDestination -Force|Out-Null
Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'reports\A08') -Force|Where-Object{$_.Name -notin @('headless_runtime','test_tmp','test_tmp_before','test_tmp_a07_role','test_tmp_a08_role')}|Copy-Item -Destination $ReportDestination -Recurse
$ContractDestination=Join-Path $PackageRoot 'input_contract';New-Item -ItemType Directory -Path $ContractDestination -Force|Out-Null
$ContractRoot=Join-Path $ProjectRoot 'input\orchestrator_bundles\UNIFIED_CONTINUOUS_20261105_R05\extracted'
foreach($Name in @('00_START_HERE.md','01_SHARED_HARD_RULES.md','02_ORCHESTRATOR_R04_REVIEW.md','03_CANONICAL_INTEGRATION_DECISION.md','ASSIGNMENTS.json','MANIFEST.json')){Copy-Item -LiteralPath (Join-Path $ContractRoot $Name) -Destination (Join-Path $ContractDestination $Name)}
New-Item -ItemType Directory -Path (Join-Path $ContractDestination 'ROLES'),(Join-Path $ContractDestination 'EVIDENCE') -Force|Out-Null
Copy-Item -LiteralPath (Join-Path $ContractRoot 'ROLES\A.md') -Destination (Join-Path $ContractDestination 'ROLES\A.md')
Copy-Item -LiteralPath (Join-Path $ContractRoot 'EVIDENCE\a07_b08_crossline.json') -Destination (Join-Path $ContractDestination 'EVIDENCE\a07_b08_crossline.json')
$Payload=Get-ChildItem -LiteralPath $PackageRoot -Recurse -File|Sort-Object FullName
$Entries=foreach($File in $Payload){[ordered]@{path=$File.FullName.Substring($PackageRoot.Length+1).Replace('\','/');size=$File.Length;sha256=(Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}}
$Manifest=[ordered]@{task_id='CDH-A08-UNAVAILABLE-AND-HISTORY-SEMANTICS-001';authority='AUTHORIZED_SYNTHETIC_OFFLINE_ONLY';generated_at_utc=[DateTime]::UtcNow.ToString('o');payload_count=$Entries.Count;files=$Entries}
$Manifest|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $PackageRoot 'MANIFEST.json') -Encoding utf8NoBOM
Compress-Archive -LiteralPath $PackageRoot -DestinationPath $Release -CompressionLevel Optimal
Copy-Item -LiteralPath $Release -Destination $Queue
Expand-Archive -LiteralPath $Release -DestinationPath $VerifyRoot
$ExtractedRoot=Join-Path $VerifyRoot 'CDH_A08_001_REVIEW';$ReadManifest=Get-Content -Raw -LiteralPath (Join-Path $ExtractedRoot 'MANIFEST.json')|ConvertFrom-Json
$Mismatch=@();foreach($Entry in $ReadManifest.files){$Path=Join-Path $ExtractedRoot ($Entry.path.Replace('/','\'));if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){$Mismatch+="missing:$($Entry.path)";continue};$Hash=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();if($Hash-ne$Entry.sha256){$Mismatch+="hash:$($Entry.path)"}}
$Archive=[IO.Compression.ZipFile]::OpenRead($Release);try{$Unsafe=@($Archive.Entries|Where-Object{$_.FullName-match'(^|/|\\)\.\.(/|\\)'-or[IO.Path]::IsPathRooted($_.FullName)});foreach($Entry in $Archive.Entries|Where-Object{-not[String]::IsNullOrEmpty($_.Name)}){$Stream=$Entry.Open();try{$Buffer=New-Object byte[] 8192;while($Stream.Read($Buffer,0,$Buffer.Length)-gt 0){}}finally{$Stream.Dispose()}};$EntryCount=$Archive.Entries.Count}finally{$Archive.Dispose()}
$ReleaseHash=(Get-FileHash -LiteralPath $Release -Algorithm SHA256).Hash.ToLowerInvariant();$QueueHash=(Get-FileHash -LiteralPath $Queue -Algorithm SHA256).Hash.ToLowerInvariant()
$Result=[ordered]@{release=$Release;queue=$Queue;release_size=(Get-Item -LiteralPath $Release).Length;sha256=$ReleaseHash;queue_sha256=$QueueHash;byte_identical=($ReleaseHash -eq $QueueHash);payload_count=$ReadManifest.payload_count;manifest_mismatch_count=$Mismatch.Count;unsafe_entry_count=$Unsafe.Count;zip_entry_count=$EntryCount;crc_read='PASS';pass=($Mismatch.Count -eq 0 -and $Unsafe.Count -eq 0 -and $ReleaseHash -eq $QueueHash)}
$Result|ConvertTo-Json -Depth 4|Set-Content -LiteralPath (Join-Path $ReviewRoot 'PACKAGE_VERIFICATION.json') -Encoding utf8NoBOM
$Result|ConvertTo-Json -Compress
if(-not $Result.pass){exit 1}
