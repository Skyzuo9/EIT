[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$BlenderPath,
    [string]$AsciiTemp = 'C:\unilab_asset_trial_tmp',
    [switch]$SkipUnitTests
)

$ErrorActionPreference = 'Stop'
$handoffRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Resolve-PythonExecutable([string]$Requested) {
    $candidates = @(
        $Requested,
        'C:\ProgramData\miniforge3\python.exe',
        'C:\ProgramData\anaconda3\python.exe',
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
    ) | Where-Object { $_ }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw 'Python was not found. Pass -PythonPath explicitly.'
}

function Resolve-BlenderExecutable([string]$Requested) {
    $commandPath = Get-Command blender -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
    $installed = Get-ChildItem 'C:\Program Files\Blender Foundation' -Filter blender.exe -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -ExpandProperty FullName
    $candidates = @($Requested, $commandPath) + @($installed)
    foreach ($candidate in ($candidates | Where-Object { $_ })) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    throw 'Blender was not found. Pass -BlenderPath explicitly.'
}

function YamlPath([string]$PathValue) {
    return $PathValue.Replace('\', '/')
}

$pythonExe = Resolve-PythonExecutable $PythonPath
$blenderExe = Resolve-BlenderExecutable $BlenderPath
if (@(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue).Count -gt 0) {
    throw 'SOLIDWORKS is already running. Close it first; the adapter only controls a process it starts itself.'
}

& $pythonExe -c "import yaml, cascadio; print('Python dependencies OK')"
if ($LASTEXITCODE -ne 0) {
    throw ('Python dependencies are missing. Run: "{0}" -m pip install -r "{1}\requirements.txt"' -f $pythonExe, $handoffRoot)
}

$workspace = Join-Path $handoffRoot 'workspace'
$output = Join-Path $workspace 'work\asset-pipeline-trial'
$inputRoot = Join-Path $workspace 'inputs'
$replacements = [ordered]@{
    '__WORKSPACE__' = YamlPath $workspace
    '__OUTPUT__' = YamlPath $output
    '__ASCII_TEMP__' = YamlPath $AsciiTemp
    '__PYTHON__' = YamlPath $pythonExe
    '__BLENDER__' = YamlPath $blenderExe
    '__SW_ASSEMBLY__' = YamlPath (Join-Path $inputRoot 'solidworks\方形视触觉\方形视触觉2.sldasm')
    '__SW_SOURCE_ROOT__' = YamlPath (Join-Path $inputRoot 'solidworks\方形视触觉')
    '__STEP_SOURCE__' = YamlPath (Join-Path $inputRoot 'step\BIgClaw.stp')
    '__STATIC_TRAY_URDF__' = YamlPath (Join-Path $inputRoot 'legacy-urdf\250ml试剂瓶托盘.urdf\urdf\250ml试剂瓶托盘.urdf.urdf')
    '__LINEAR_GUIDE_URDF__' = YamlPath (Join-Path $inputRoot 'legacy-urdf\导轨PTB22-L40-1000-R-M75-C3-0.urdf\urdf\PTB22-L40-1000-R-M75-C3-0.SLDASM.urdf')
    '__CAPPING_GRIPPER_URDF__' = YamlPath (Join-Path $inputRoot 'legacy-urdf\拧盖夹爪组件.urdf\urdf\拧盖夹爪组件.urdf.urdf')
    '__INPUT_ROOT__' = YamlPath $inputRoot
}
$templatePath = Join-Path $handoffRoot 'config\pipeline.template.yaml'
$localConfig = Join-Path $workspace 'work\pipeline.local.yaml'
$configText = [System.IO.File]::ReadAllText($templatePath, [System.Text.Encoding]::UTF8)
foreach ($entry in $replacements.GetEnumerator()) {
    $configText = $configText.Replace($entry.Key, $entry.Value)
}
[System.IO.Directory]::CreateDirectory((Split-Path $localConfig -Parent)) | Out-Null
[System.IO.File]::WriteAllText($localConfig, $configText, [System.Text.UTF8Encoding]::new($false))

Push-Location $handoffRoot
try {
    if (-not $SkipUnitTests) {
        & $pythonExe -m unittest discover -s pipeline -p 'test_*.py' -v
        if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }
    }
    & $pythonExe (Join-Path $handoffRoot 'pipeline\trial_asset_pipeline.py') --config $localConfig
    if ($LASTEXITCODE -ne 0) { throw "Asset pipeline failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

Write-Host "`nGenerated output: $output"
Write-Host ('Next: .\scripts\02-verify-output.ps1 -PythonPath "{0}"' -f $pythonExe)
