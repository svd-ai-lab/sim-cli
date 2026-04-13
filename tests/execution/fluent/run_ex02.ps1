# run_ex02.ps1 — EX-02: Numerical acceptance criterion verification (Layer B)
#
# Source case: A-03 (modified BCs, 22–38°C range acceptance)
# Mesh: mixing_elbow.msh.h5
# BCs: cold-inlet 0.6 m/s / 20°C (MODIFIED), hot-inlet 1.2 m/s / 40°C
# Physics: water-liquid, realizable k-epsilon, energy equation
# Init: hybrid, 100 iterations
# Acceptance: outlet mass-weighted avg temp IN 22–38°C (Layer B)
#
# Layer: B (acceptance-grounded completion)
# Path:  runtime v1

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\run_helpers.ps1"
Set-Location $SIM_MAIN

$CASE_ID = "EX-02"
$LOG_DIR  = New-LogDir -CaseId $CASE_ID
$LOG_FILE = "$LOG_DIR\run.log"

Write-Log $LOG_FILE "=========================================="
Write-Log $LOG_FILE "  $CASE_ID — Numerical Acceptance Criterion"
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
Invoke-IonStep -CaseId $CASE_ID -Label "setup-bcs"      -SnippetFile "$SNIPPETS\05b_setup_bcs_ex02.py"      -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "hybrid-init"    -SnippetFile "$SNIPPETS\06_hybrid_init.py"          -LogDir $LOG_DIR -LogFile $LOG_FILE
Invoke-IonStep -CaseId $CASE_ID -Label "run-iterations" -SnippetFile "$SNIPPETS\07_run_150_iter.py"         -LogDir $LOG_DIR -LogFile $LOG_FILE
$extractResult = Invoke-IonStep -CaseId $CASE_ID -Label "extract-mass-weighted-temp" -SnippetFile "$SNIPPETS\08b_extract_mass_weighted_temp.py" -LogDir $LOG_DIR -LogFile $LOG_FILE

# ── Final session state ───────────────────────────────────────────────────────
$finalSummary = Invoke-IonQuery -Name "session.summary" -LogDir $LOG_DIR -Label "final" -LogFile $LOG_FILE

# ── Acceptance evaluation (Layer B) ──────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== ACCEPTANCE EVALUATION (Layer B) ==="
Write-Log $LOG_FILE "  run_count (final): $($finalSummary.run_count)"

$tempC       = $extractResult.result.outlet_mass_weighted_avg_temp_C
$inRange     = $extractResult.result.acceptance_22_38_C

if ($null -ne $tempC) {
    Write-Log $LOG_FILE "  outlet_mass_weighted_avg_temp_C: $tempC"
    if ($inRange -eq $true) {
        Write-Log $LOG_FILE "  Acceptance criterion (22–38°C): PASS"
        Write-Log $LOG_FILE "  EX-02 RESULT: PASS"
    } elseif ($inRange -eq $false) {
        Write-Log $LOG_FILE "  Acceptance criterion (22–38°C): FAIL (value out of range)"
        Write-Log $LOG_FILE "  EX-02 RESULT: FAIL (acceptance_failure — value outside criterion)"
        Write-Log $LOG_FILE "  NOTE: Physics may be correct; criterion range may need review."
    }
} else {
    Write-Log $LOG_FILE "  ERROR: outlet_mass_weighted_avg_temp_C is null — extraction failed"
    Write-Log $LOG_FILE "  EX-02 RESULT: FAIL (extraction_failure)"
}

# ── Disconnect ────────────────────────────────────────────────────────────────
Invoke-IonDisconnect -LogFile $LOG_FILE
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "Full logs: $LOG_DIR"
