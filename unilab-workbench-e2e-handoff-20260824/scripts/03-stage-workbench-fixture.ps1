[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkbenchPublicDir,
    [string]$RunId = 'asset-pipeline-e2e-20260824',
    [string]$PythonPath,
    [switch]$UseBaseline
)

$ErrorActionPreference = 'Stop'
$handoffRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$publicDir = (Resolve-Path -LiteralPath $WorkbenchPublicDir).Path
$namespaceDir = Join-Path $publicDir '__asset_pipeline_e2e__'
$destination = Join-Path $namespaceDir $RunId
if (Test-Path -LiteralPath $destination) {
    throw "Refusing to overwrite an existing fixture: $destination. Choose a new -RunId."
}
[System.IO.Directory]::CreateDirectory($namespaceDir) | Out-Null

$generatedOutput = Join-Path $handoffRoot 'workspace\work\asset-pipeline-trial'
$prebuiltFixture = Join-Path $handoffRoot 'workbench-fixture-baseline'
if ($UseBaseline -or -not (Test-Path -LiteralPath (Join-Path $generatedOutput 'gate-report.json'))) {
    if (-not (Test-Path -LiteralPath (Join-Path $prebuiltFixture 'scene-catalog.json'))) {
        throw 'The prebuilt Workbench fixture is missing.'
    }
    Copy-Item -LiteralPath $prebuiltFixture -Destination $destination -Recurse
    $sourceLabel = 'prebuilt baseline'
} else {
    if (-not $PythonPath) {
        $PythonPath = @(
            'C:\ProgramData\miniforge3\python.exe',
            'C:\ProgramData\anaconda3\python.exe',
            (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
    }
    if (-not $PythonPath) { throw 'Python was not found. Pass -PythonPath or use -UseBaseline.' }
    & $PythonPath (Join-Path $handoffRoot 'pipeline\build_workbench_fixture.py') --trial-output $generatedOutput --output $destination --fixture-id $RunId
    if ($LASTEXITCODE -ne 0) { throw 'Workbench fixture build failed.' }
    $sourceLabel = 'newly generated trial output'
}

$catalogUrl = "/__asset_pipeline_e2e__/$RunId/scene-catalog.json"
Write-Host "Staged $sourceLabel at: $destination"
Write-Host "Workbench test catalog URL: $catalogUrl"
Write-Host 'This fixture is display/picking-only; it is not a WorkCellActivation and must not enable motion, interlock, or execution.'
