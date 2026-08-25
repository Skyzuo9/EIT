[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$handoffRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$manifestPath = Join-Path $handoffRoot 'HANDOFF-MANIFEST.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Manifest not found: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$errors = [System.Collections.Generic.List[string]]::new()
foreach ($entry in $manifest.files) {
    $path = Join-Path $handoffRoot ($entry.path.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $errors.Add("missing: $($entry.path)")
        continue
    }
    $item = Get-Item -LiteralPath $path
    if ($item.Length -ne [int64]$entry.bytes) {
        $errors.Add("size mismatch: $($entry.path)")
        continue
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) {
        $errors.Add("hash mismatch: $($entry.path)")
    }
}
$result = [ordered]@{
    handoffId = $manifest.handoffId
    passed = $errors.Count -eq 0
    checkedFiles = $manifest.files.Count
    errors = $errors
}
$result | ConvertTo-Json -Depth 5
if ($errors.Count -gt 0) { exit 1 }
