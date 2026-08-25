[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkbenchRepo,
    [string[]]$ScreenshotPath = @()
)

$ErrorActionPreference = 'Stop'
$handoffRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repo = (Resolve-Path -LiteralPath $WorkbenchRepo).Path
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$resultRoot = Join-Path $handoffRoot "workspace\work\return-package-$timestamp"
[System.IO.Directory]::CreateDirectory($resultRoot) | Out-Null

$trial = Join-Path $handoffRoot 'workspace\work\asset-pipeline-trial'
foreach ($name in @('REPORT.md', 'run-summary.json', 'gate-report.json', 'environment.json')) {
    $source = Join-Path $trial $name
    if (Test-Path -LiteralPath $source -PathType Leaf) { Copy-Item -LiteralPath $source -Destination $resultRoot }
}
if (Test-Path -LiteralPath (Join-Path $trial 'previews')) {
    Copy-Item -LiteralPath (Join-Path $trial 'previews') -Destination $resultRoot -Recurse
}
foreach ($screenshot in $ScreenshotPath) {
    if (Test-Path -LiteralPath $screenshot -PathType Leaf) {
        Copy-Item -LiteralPath $screenshot -Destination $resultRoot
    }
}

$gitEvidence = [ordered]@{
    repo = $repo
    commit = (& git -C $repo rev-parse HEAD 2>&1) -join "`n"
    branch = (& git -C $repo branch --show-current 2>&1) -join "`n"
    status = (& git -C $repo status --short 2>&1) -join "`n"
}
[System.IO.File]::WriteAllText(
    (Join-Path $resultRoot 'workbench-git-evidence.json'),
    (($gitEvidence | ConvertTo-Json -Depth 5) + "`n"),
    [System.Text.UTF8Encoding]::new($false)
)
Copy-Item -LiteralPath (Join-Path $handoffRoot 'templates\TEST-RESULTS.md') -Destination $resultRoot
$zipPath = "$resultRoot.zip"
Compress-Archive -LiteralPath $resultRoot -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Return package: $resultRoot"
Write-Host "ZIP: $zipPath"
