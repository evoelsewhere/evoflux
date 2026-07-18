# Runs a migration unit's legacy VB6 implementation and writes its
# canonical-ready output for aim_compare. Customize per project — VB6 legacy
# apps typically only run on Windows, so this is PowerShell, likely executed
# on a Windows VM/remote host reachable from the runner.
#
# Arg contract (identical for run_legacy and run_target):
#   $1 UNIT      module / unit name                        -> -Unit
#   $2 CASE_SET  which cases to run, e.g. smoke | full      -> -CaseSet
#   $3 OUT_DIR   absolute directory to write output into    -> -OutDir
param(
    [Parameter(Mandatory = $true)][string]$Unit,
    [string]$CaseSet = 'smoke',                             # smoke | full
    [Parameter(Mandatory = $true)][string]$OutDir          # absolute output dir
)

Write-Warning "run_legacy stub — received: UNIT='$Unit' CASE_SET='$CaseSet' OUT_DIR='$OutDir'"
Write-Warning "Contract: `$1=UNIT  `$2=CASE_SET (smoke|full)  `$3=OUT_DIR (absolute output dir)"
Write-Warning "TODO: launch the legacy VB6 app/exe for unit '$Unit', case set '$CaseSet'"
Write-Warning "TODO: write its output into '$OutDir' for aim_compare to read"
exit 1
