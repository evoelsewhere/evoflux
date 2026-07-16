# Runs a migration unit's legacy VB6 implementation against a golden case's
# input and captures output for aim_compare. Customize per project — VB6
# legacy apps typically only run on Windows, so this is PowerShell, likely
# executed on a Windows VM/remote host reachable from the runner.
param(
    [Parameter(Mandatory = $true)][string]$Unit,
    [Parameter(Mandatory = $true)][string]$CaseDir   # golden/units/<unit>/cases/<case-id>
)

Write-Warning "TODO: launch the legacy VB6 app/exe for unit '$Unit'"
Write-Warning "TODO: feed $CaseDir/input/ to it and capture output next to the $CaseDir/expected/ layout"
exit 1
