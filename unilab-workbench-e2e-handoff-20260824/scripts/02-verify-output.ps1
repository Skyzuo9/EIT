[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$AllowPartial,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$handoffRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonPath) {
    $PythonPath = @(
        'C:\ProgramData\miniforge3\python.exe',
        'C:\ProgramData\anaconda3\python.exe',
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $PythonPath) { throw 'Python was not found. Pass -PythonPath explicitly.' }
if (-not $OutputPath) { $OutputPath = Join-Path $handoffRoot 'workspace\work\asset-pipeline-trial' }
$arguments = @((Join-Path $handoffRoot 'pipeline\verify_trial_output.py'), '--output', $OutputPath)
if ($AllowPartial) { $arguments += '--allow-partial' }
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) { throw 'Strict output verification failed.' }
