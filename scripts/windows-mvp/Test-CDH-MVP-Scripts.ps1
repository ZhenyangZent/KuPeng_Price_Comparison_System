$ErrorActionPreference = 'Stop'
$errorsFound = @()
Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' | ForEach-Object {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    foreach ($item in $errors) { $errorsFound += "$($_.Name): $($item.Message)" }
}
if ($errorsFound.Count -ne 0) {
    $errorsFound | ForEach-Object { Write-Error $_ }
    exit 1
}
Write-Output 'POWERSHELL_PARSE_PASS'
exit 0
