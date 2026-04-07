# run_ex05.ps1 — EX-05: Multi-field extraction with output format requirement (Layer B)
#
# Source case: G-03 (complete, 3 output fields required in JSON)
# Mesh: mixing_elbow.msh.h5
# BCs: cold-inlet 0.4 m/s / 20°C, hot-inlet 1.2 m/s / 40°C (same as EX-01)
# Physics: water-liquid, realizable k-epsilon, energy equation
# Init: hybrid, 150 iterations
# Acceptance: last.result contains outlet_temp_celsius + cold_inlet_mfr + hot_inlet_mfr
#             (final_residuals best-effort, not hard requirement in v0)
#
# Layer: B (acceptance-grounded completion — multi-field extraction)
# Path:  runtime v1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\run_helpers.ps1"
Set-Location $SIM_MAIN

$CASE_ID = "EX-05"
$LOG_DIR  = New-LogDir -CaseId $CASE_ID
$LOG_FILE = "$LOG_DIR\run.log"

Write-Log $LOG_FILE "=========================================="
Write-Log $LOG_FILE "  $CASE_ID — Multi-Field Extraction"
Write-Log $LOG_FILE "  Log dir: $LOG_DIR"
Write-Log $LOG_FILE "=========================================="

# ── Connect ──────────────────────────────────────────────────────────────────
Invoke-IonConnect -Mode "solver" -UiMode "gui" -Processors 2 -LogFile $LOG_FILE
Invoke-IonQuery -Name "session.summary" -LogDir $LOG_DIR -Label "after-connect" -LogFile $LOG_FILE

# ── Steps ─────────────────────────────────────────────────────────────────────
Invoke-IonStep -CaseId $CASE_ID -Label "read-case"      -SnippetFile "$SNIPPETS\01_read_case.py"            -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "mesh-check"     -SnippetFile "$SNIPPETS\02_mesh_check.py"           -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "diagnose-zones" -SnippetFile "$SNIPPETS\00_diagnose_zones.py"       -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "setup-physics"  -SnippetFile "$SNIPPETS\03_setup_physics.py"        -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "setup-material" -SnippetFile "$SNIPPETS\04_setup_material.py"       -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "setup-bcs"      -SnippetFile "$SNIPPETS\05a_setup_bcs_ex01_ex05.py" -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "hybrid-init"    -SnippetFile "$SNIPPETS\06_hybrid_init.py"          -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "run-iterations" -SnippetFile "$SNIPPETS\07_run_150_iter.py"         -LogDir $LOG_DIR -LogFile $LOG_FILE
$extractResult = Invoke-IonStep -CaseId $CASE_ID -Label "extract-all-fields" -SnippetFile "$SNIPPETS\08c_extract_all_fields.py" -LogDir $LOG_DIR -LogFile $LOG_FILE

# ── Final session state ───────────────────────────────────────────────────────
$finalSummary = Invoke-IonQuery -Name "session.summary" -LogDir $LOG_DIR -Label "final" -LogFile $LOG_FILE

# ── Acceptance evaluation (Layer B) ──────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== ACCEPTANCE EVALUATION (Layer B) ==="
Write-Log $LOG_FILE "  run_count (final): $($finalSummary.run_count)"

$r = $extractResult.result
Write-Log $LOG_FILE "  outlet_temp_celsius:  $($r.outlet_temp_celsius)"
Write-Log $LOG_FILE "  cold_inlet_mfr (kg/s): $($r.cold_inlet_mfr)"
Write-Log $LOG_FILE "  hot_inlet_mfr  (kg/s): $($r.hot_inlet_mfr)"
Write-Log $LOG_FILE "  final_residuals:       $($r.final_residuals)"

$required_fields_ok = (
    ($null -ne $r.outlet_temp_celsius) -and
    ($null -ne $r.cold_inlet_mfr) -and
    ($null -ne $r.hot_inlet_mfr)
)

if ($required_fields_ok) {
    Write-Log $LOG_FILE "  All 3 required numeric fields present: PASS"
    Write-Log $LOG_FILE "  EX-05 RESULT: PASS"
    if ($null -eq $r.final_residuals) {
        Write-Log $LOG_FILE "  NOTE: final_residuals=null (residual extraction is best-effort in v0)"
    }
} else {
    Write-Log $LOG_FILE "  ERROR: one or more required fields are null"
    Write-Log $LOG_FILE "  EX-05 RESULT: FAIL (extraction_failure)"
}

# ── Disconnect ────────────────────────────────────────────────────────────────
Invoke-IonDisconnect -LogFile $LOG_FILE
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "Full logs: $LOG_DIR"
