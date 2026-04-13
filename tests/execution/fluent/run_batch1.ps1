# run_batch1.ps1 — Run EX-01 → EX-02 → EX-05 sequentially.
#
# Each case runs in its own Fluent session (connect → steps → disconnect).
# If any case fails mid-execution, it disconnects and records the failure
# in its own log directory. The batch continues with the next case.
#
# Usage:
#   cd <sim-cli-repo>
#   powershell -ExecutionPolicy Bypass -File tests\execution\run_batch1.ps1
#
# Logs are written to:
#   tests\execution\logs\EX-01_<timestamp>\
#   tests\execution\logs\EX-02_<timestamp>\
#   tests\execution\logs\EX-05_<timestamp>\
#   tests\execution\logs\batch1_<timestamp>_summary.log

# Resolve sim-cli repo root from this script's location, then cd there
# so .sim/ IPC dir is created at the repo root.
$SIM_MAIN = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location $SIM_MAIN

$BATCH_TS      = Get-Date -Format "yyyyMMdd_HHmmss"
$BATCH_LOG     = "$SIM_MAIN\tests\execution\logs\batch1_${BATCH_TS}_summary.log"
$SCRIPT_DIR    = $PSScriptRoot

function Write-BatchLog {
    param([string]$Message)
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "$ts  $Message"
    Write-Host $line
    Add-Content -Path $BATCH_LOG -Value $line
}

Write-BatchLog "======================================================"
Write-BatchLog "  Batch 1 Execution Test Run"
Write-BatchLog "  Cases: EX-01, EX-02, EX-05"
Write-BatchLog "  GUI: enabled (--ui-mode gui)"
Write-BatchLog "======================================================"
Write-BatchLog ""

$results = @{}

foreach ($case_script in @("run_ex01.ps1", "run_ex02.ps1", "run_ex05.ps1")) {
    $case_id = $case_script -replace "run_", "" -replace "\.ps1", "" -replace "ex", "EX-"
    Write-BatchLog "------------------------------------------------------"
    Write-BatchLog "  Starting $case_id ..."
    Write-BatchLog "------------------------------------------------------"

    $start = Get-Date
    try {
        & powershell -ExecutionPolicy Bypass -File "$SCRIPT_DIR\$case_script"
        $exit_code = $LASTEXITCODE
    } catch {
        $exit_code = 1
        Write-BatchLog "  EXCEPTION running ${case_id}: $_"
    }
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)

    if ($exit_code -eq 0) {
        $results[$case_id] = "PASS"
        Write-BatchLog "  $case_id completed in ${elapsed}s — see logs for detailed result"
    } else {
        $results[$case_id] = "FAIL (exit $exit_code)"
        Write-BatchLog "  $case_id FAILED (exit $exit_code) after ${elapsed}s"
        Write-BatchLog "  Check tests\execution\logs\${case_id}_* for details"
    }
    Write-BatchLog ""
}

Write-BatchLog "======================================================"
Write-BatchLog "  BATCH SUMMARY"
Write-BatchLog "======================================================"
foreach ($k in $results.Keys) {
    Write-BatchLog "  $k : $($results[$k])"
}
Write-BatchLog ""
Write-BatchLog "All log directories: tests\execution\logs\"
Write-BatchLog "Batch summary log:   $BATCH_LOG"
