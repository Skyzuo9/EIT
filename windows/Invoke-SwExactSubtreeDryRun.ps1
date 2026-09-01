[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$Request,
    [Parameter(Mandatory = $true)][string]$StationHandoff,
    [Parameter(Mandatory = $true)][string]$Decomposition,
    [Parameter(Mandatory = $true)][string]$StationLayout,
    [Parameter(Mandatory = $true)][string]$CoverageReport,
    [Parameter(Mandatory = $true)][string]$Review,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = "Stop"

# This wrapper intentionally never creates or attaches to a SolidWorks COM object.
# The Python dry-run validates approval bindings and parses the captured occurrence
# snapshot only.  A future W2 executor must use a different, explicitly authorized entrypoint.
& $Python (Join-Path $RepoRoot "scripts\sw_exact_subtree_exporter.py") `
    --request $Request `
    --station-handoff $StationHandoff `
    --decomposition $Decomposition `
    --station-layout $StationLayout `
    --coverage-report $CoverageReport `
    --review $Review `
    --output $Output

if ($LASTEXITCODE -ne 0) {
    throw "SwExactSubtreeExporter dry-run failed closed with exit code $LASTEXITCODE"
}
