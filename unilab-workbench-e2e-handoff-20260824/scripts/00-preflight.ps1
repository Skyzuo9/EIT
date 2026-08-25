[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$BlenderPath
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
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Resolve-BlenderExecutable([string]$Requested) {
    $commandPath = Get-Command blender -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
    $installed = Get-ChildItem 'C:\Program Files\Blender Foundation' -Filter blender.exe -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -ExpandProperty FullName
    $candidates = @($Requested, $commandPath) + @($installed)
    foreach ($candidate in ($candidates | Where-Object { $_ })) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

function Invoke-Version([string]$Executable, [string[]]$Arguments) {
    if (-not $Executable) { return $null }
    try {
        return ((& $Executable @Arguments 2>&1) | Select-Object -First 3) -join "`n"
    } catch {
        return $_.Exception.Message
    }
}

$pythonExe = Resolve-PythonExecutable $PythonPath
$blenderExe = Resolve-BlenderExecutable $BlenderPath
$pythonModules = $false
$pythonModuleMessage = 'Python not found'
if ($pythonExe) {
    $pythonModuleMessage = ((& $pythonExe -c "import yaml, cascadio; print('PyYAML=' + yaml.__version__); print('cascadio=' + getattr(cascadio, '__version__', '0.1.1'))" 2>&1) -join "`n")
    $pythonModules = $LASTEXITCODE -eq 0
}

$sourceChecks = @(
    'workspace\inputs\solidworks\方形视触觉\方形视触觉2.sldasm',
    'workspace\inputs\step\BIgClaw.stp',
    'workspace\inputs\legacy-urdf\250ml试剂瓶托盘.urdf\urdf\250ml试剂瓶托盘.urdf.urdf',
    'workspace\inputs\legacy-urdf\导轨PTB22-L40-1000-R-M75-C3-0.urdf\urdf\PTB22-L40-1000-R-M75-C3-0.SLDASM.urdf',
    'workspace\inputs\legacy-urdf\拧盖夹爪组件.urdf\urdf\拧盖夹爪组件.urdf.urdf'
)
$missingSources = @($sourceChecks | Where-Object { -not (Test-Path -LiteralPath (Join-Path $handoffRoot $_) -PathType Leaf) })
$solidworksRegistered = Test-Path 'Registry::HKEY_CLASSES_ROOT\SldWorks.Application.33'
$solidworksRunning = @(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue).Count -gt 0
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
$gitCommand = Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
$criticalPassed = [bool]($pythonExe -and $pythonModules -and $blenderExe -and $solidworksRegistered -and $missingSources.Count -eq 0 -and -not $solidworksRunning)

$report = [ordered]@{
    schema = 'lab.asset_pipeline_preflight/v0'
    passed = $criticalPassed
    handoffRoot = $handoffRoot
    python = [ordered]@{
        found = [bool]$pythonExe
        executable = $pythonExe
        version = Invoke-Version $pythonExe @('--version')
        requiredModulesPassed = $pythonModules
        moduleProbe = $pythonModuleMessage
    }
    blender = [ordered]@{
        found = [bool]$blenderExe
        executable = $blenderExe
        version = Invoke-Version $blenderExe @('--version')
    }
    solidworks = [ordered]@{
        progid = 'SldWorks.Application.33'
        registered = $solidworksRegistered
        alreadyRunning = $solidworksRunning
        instruction = if ($solidworksRunning) { 'Close SOLIDWORKS before running the isolated read-only capture.' } else { 'Ready for isolated read-only capture.' }
    }
    optional = [ordered]@{
        node = Invoke-Version $nodeCommand @('--version')
        git = Invoke-Version $gitCommand @('--version')
    }
    inputs = [ordered]@{
        expected = $sourceChecks.Count
        missing = $missingSources
    }
}

$reportPath = Join-Path $handoffRoot 'workspace\work\preflight.json'
[System.IO.Directory]::CreateDirectory((Split-Path $reportPath -Parent)) | Out-Null
[System.IO.File]::WriteAllText($reportPath, (($report | ConvertTo-Json -Depth 8) + "`n"), [System.Text.UTF8Encoding]::new($false))
$report | ConvertTo-Json -Depth 8
Write-Host "`nPreflight report: $reportPath"
if (-not $criticalPassed) {
    Write-Host "Install missing requirements with: <python> -m pip install -r `"$handoffRoot\requirements.txt`""
    exit 1
}
