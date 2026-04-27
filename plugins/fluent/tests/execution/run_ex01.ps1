# run_ex01.ps1 — EX-01: Solver feasibility baseline (Layer A)
#
# Source case: A-02 (complete English prompt, all BCs provided)
# Mesh: mixing_elbow.msh.h5
# BCs: cold-inlet 0.4 m/s / 20°C, hot-inlet 1.2 m/s / 40°C
# Physics: water-liquid, realizable k-epsilon, energy equation
# Init: hybrid, 150 iterations
# Acceptance: iterations_run=150, outlet avg temperature extractable as numeric
#
# Layer: A (execution feasibility)
# Path:  runtime v1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Source helpers (defines $SIM_MAIN from $PSScriptRoot) then change to repo root
# so .sim/ IPC directory is created there.
. "$PSScriptRoot\run_helpers.ps1"
Set-Location $SIM_MAIN

$CASE_ID = "EX-01"
$LOG_DIR  = New-LogDir -CaseId $CASE_ID
$LOG_FILE = "$LOG_DIR\run.log"

Write-Log $LOG_FILE "=========================================="
Write-Log $LOG_FILE "  $CASE_ID — Solver Feasibility Baseline"
Write-Log $LOG_FILE "  Log dir: $LOG_DIR"
Write-Log $LOG_FILE "=========================================="

# ── Connect ──────────────────────────────────────────────────────────────────
Invoke-IonConnect -Mode "solver" -UiMode "gui" -Processors 2 -LogFile $LOG_FILE
$summary = Invoke-IonQuery -Name "session.summary" -LogDir $LOG_DIR -Label "after-connect" -LogFile $LOG_FILE

# ── Steps ─────────────────────────────────────────────────────────────────────
Invoke-IonStep -CaseId $CASE_ID -Label "read-case"   -SnippetFile "$SNIPPETS\01_read_case.py"         -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "mesh-check"  -SnippetFile "$SNIPPETS\02_mesh_check.py"        -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "diagnose-zones" -SnippetFile "$SNIPPETS\00_diagnose_zones.py" -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "setup-physics"  -SnippetFile "$SNIPPETS\03_setup_physics.py"  -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "setup-material" -SnippetFile "$SNIPPETS\04_setup_material.py" -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "setup-bcs"      -SnippetFile "$SNIPPETS\05a_setup_bcs_ex01_ex05.py" -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "hybrid-init"    -SnippetFile "$SNIPPETS\06_hybrid_init.py"    -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "run-iterations" -SnippetFile "$SNIPPETS\07_run_150_iter.py"   -LogDir $LOG_DIR -LogFile $LOG_FILE
$extractResult = Invoke-IonStep -CaseId $CASE_ID -Label "extract-outlet-temp" -SnippetFile "$SNIPPETS\08a_extract_outlet_temp.py" -LogDir $LOG_DIR -LogFile $LOG_FILE

# ── Final session state ───────────────────────────────────────────────────────
$finalSummary = Invoke-IonQuery -Name "session.summary" -LogDir $LOG_DIR -Label "final" -LogFile $LOG_FILE

# ── Acceptance evaluation ─────────────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== ACCEPTANCE EVALUATION ==="
Write-Log $LOG_FILE "  run_count (final): $($finalSummary.run_count)"

$tempC = $extractResult.result.outlet_avg_temp_C
if ($null -ne $tempC) {
    Write-Log $LOG_FILE "  outlet_avg_temp_C: $tempC"
    Write-Log $LOG_FILE "  Layer A: PASS (execution completed, temperature extracted)"
    Write-Log $LOG_FILE "  EX-01 RESULT: PASS"
} else {
    Write-Log $LOG_FILE "  ERROR: outlet_avg_temp_C is null — extraction failed"
    Write-Log $LOG_FILE "  EX-01 RESULT: FAIL (extraction_failure)"
}

# ── Disconnect ────────────────────────────────────────────────────────────────
Invoke-IonDisconnect -LogFile $LOG_FILE
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "Full logs: $LOG_DIR"
