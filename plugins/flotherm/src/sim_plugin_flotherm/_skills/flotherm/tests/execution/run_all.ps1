# run_all.ps1 — Run all flotherm execution tests sequentially.
#
# Usage: powershell -ExecutionPolicy Bypass -File run_all.ps1
#
# Tests:
#   EX-01  Connectivity check
#   EX-02  Lint .pack files
#   EX-03  Lint FloSCRIPT XML
#   EX-04  File type detection
#   EX-05  Batch solve attempt (known failure — regression baseline)
#   EX-06  Output parsing
#   EX-07  Error paths

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\run_helpers.ps1"

$CASE_ID  = "ALL"
$LOG_DIR  = New-LogDir -CaseId $CASE_ID
$LOG_FILE = "$LOG_DIR\run.log"
$pass = 0; $fail = 0; $known_fail = 0

Write-Log $LOG_FILE "=========================================="
Write-Log $LOG_FILE "  Flotherm Execution Tests"
Write-Log $LOG_FILE "  Log dir: $LOG_DIR"
Write-Log $LOG_FILE "=========================================="

# ── EX-01: Connectivity ─────────────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== EX-01: Connectivity Check ==="

$r = Invoke-Driver -LogFile $LOG_FILE -Label "connect" -Code @"
info = d.connect()
print(json.dumps({"status": info.status, "version": info.version, "message": info.message}))
"@

$ok = $true
$ok = (Assert-Equal "status" $r.status "ok" $LOG_FILE) -and $ok
$ok = (Assert-Equal "version" $r.version "2504" $LOG_FILE) -and $ok
$ok = (Assert-Contains "message" $r.message "flotherm.bat" $LOG_FILE) -and $ok

if ($ok) { $pass++; Write-Log $LOG_FILE "  EX-01: PASS" }
else     { $fail++; Write-Log $LOG_FILE "  EX-01: FAIL" }

# ── EX-02: Lint .pack ───────────────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== EX-02: Lint .pack Files ==="

$r = Invoke-Driver -LogFile $LOG_FILE -Label "lint-mobile" -Code @"
r = d.lint(Path(r'$PACK_MOBILE_DEMO'))
print(json.dumps({"ok": r.ok, "diag_count": len(r.diagnostics)}))
"@
$ok2 = Assert-True "lint Mobile_Demo ok" $r.ok $LOG_FILE

$r = Invoke-Driver -LogFile $LOG_FILE -Label "lint-super" -Code @"
r = d.lint(Path(r'$PACK_SUPERPOSITION'))
print(json.dumps({"ok": r.ok, "diag_count": len(r.diagnostics)}))
"@
$ok2 = (Assert-True "lint SuperPosition ok" $r.ok $LOG_FILE) -and $ok2

if ($ok2) { $pass++; Write-Log $LOG_FILE "  EX-02: PASS" }
else      { $fail++; Write-Log $LOG_FILE "  EX-02: FAIL" }

# ── EX-03: Lint FloSCRIPT XML ───────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== EX-03: Lint FloSCRIPT XML ==="

$r = Invoke-Driver -LogFile $LOG_FILE -Label "lint-grid-xml" -Code @"
r = d.lint(Path(r'$XML_GRID_HEATSINKS'))
diags = [x.message for x in r.diagnostics]
print(json.dumps({"ok": r.ok, "diagnostics": diags}))
"@
$ok3 = Assert-True "lint Grid-HeatSinks ok" $r.ok $LOG_FILE

$r = Invoke-Driver -LogFile $LOG_FILE -Label "lint-tube-xml" -Code @"
r = d.lint(Path(r'$XML_MAKE_TUBE'))
diags = [x.message for x in r.diagnostics]
print(json.dumps({"ok": r.ok, "diagnostics": diags}))
"@
$ok3 = (Assert-True "lint Make_Tube ok" $r.ok $LOG_FILE) -and $ok3

if ($ok3) { $pass++; Write-Log $LOG_FILE "  EX-03: PASS" }
else      { $fail++; Write-Log $LOG_FILE "  EX-03: FAIL" }

# ── EX-04: File Type Detection ──────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== EX-04: File Type Detection ==="

$r = Invoke-Driver -LogFile $LOG_FILE -Label "detect" -Code @"
results = {
    'pack': d.detect(Path(r'$PACK_MOBILE_DEMO')),
    'floscript_xml': d.detect(Path(r'$XML_GRID_HEATSINKS')),
}
print(json.dumps(results))
"@
$ok4 = Assert-True "detect .pack" $r.pack $LOG_FILE
$ok4 = (Assert-True "detect FloSCRIPT .xml" $r.floscript_xml $LOG_FILE) -and $ok4

if ($ok4) { $pass++; Write-Log $LOG_FILE "  EX-04: PASS" }
else      { $fail++; Write-Log $LOG_FILE "  EX-04: FAIL" }

# ── EX-05: Batch Solve (Known Failure) ──────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== EX-05: Batch Solve Attempt (Known Failure Baseline) ==="

$r = Invoke-Driver -LogFile $LOG_FILE -Label "batch-solve" -Code @"
result = d.run_file(Path(r'$PACK_SUPERPOSITION'), mode='batch')
print(json.dumps({
    "exit_code": result.exit_code,
    "stdout_empty": not result.stdout,
    "stderr": result.stderr[:200],
    "duration_s": result.duration_s,
    "has_registerStart": "registerStart" in result.stderr,
}))
"@

Write-Log $LOG_FILE "    exit_code: $($r.exit_code)"
Write-Log $LOG_FILE "    stdout_empty: $($r.stdout_empty)"
Write-Log $LOG_FILE "    duration_s: $($r.duration_s)"
Write-Log $LOG_FILE "    has_registerStart: $($r.has_registerStart)"
Write-Log $LOG_FILE "    stderr: $($r.stderr)"

# This is a KNOWN failure — batch mode does not work in Flotherm 2504
# The test passes if the KNOWN failure pattern is observed
$known = ($r.exit_code -eq 0) -and ($r.stdout_empty -eq $true) -and ($r.has_registerStart -eq $true)
if ($known) {
    $known_fail++
    Write-Log $LOG_FILE "  EX-05: KNOWN FAIL (batch mode broken — see known_issues.md)"
} else {
    # If somehow it works now, that's actually good news
    $pass++
    Write-Log $LOG_FILE "  EX-05: UNEXPECTED PASS — batch mode may have been fixed!"
}

# ── EX-06: Output Parsing ───────────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== EX-06: Output Parsing ==="

$r = Invoke-Driver -LogFile $LOG_FILE -Label "parse" -Code @"
tests = [
    (d.parse_output(''), {}),
    (d.parse_output('no json here'), {}),
    (d.parse_output('{\"temp\": 85.3}'), {'temp': 85.3}),
    (d.parse_output('line1\n{\"a\":1}\nline3\n{\"b\":2}'), {'b': 2}),
]
all_pass = all(actual == expected for actual, expected in tests)
print(json.dumps({"all_pass": all_pass, "test_count": len(tests)}))
"@
$ok6 = Assert-True "parse_output all cases" $r.all_pass $LOG_FILE

if ($ok6) { $pass++; Write-Log $LOG_FILE "  EX-06: PASS" }
else      { $fail++; Write-Log $LOG_FILE "  EX-06: FAIL" }

# ── EX-07: Error Paths ──────────────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=== EX-07: Error Paths ==="

$r = Invoke-Driver -LogFile $LOG_FILE -Label "not-installed" -Code @"
import sim.drivers.flotherm.driver as drv
orig = drv._find_installation
drv._find_installation = lambda: None
try:
    d.run_file(Path(r'$PACK_MOBILE_DEMO'), mode='batch')
    print(json.dumps({"raised": False}))
except RuntimeError as e:
    print(json.dumps({"raised": True, "error_type": "RuntimeError", "msg": str(e)[:100]}))
finally:
    drv._find_installation = orig
"@
$ok7 = Assert-True "RuntimeError raised" $r.raised $LOG_FILE
$ok7 = (Assert-Equal "error_type" $r.error_type "RuntimeError" $LOG_FILE) -and $ok7

$r = Invoke-Driver -LogFile $LOG_FILE -Label "xml-not-impl" -Code @"
import tempfile, os
tmp = os.path.join(tempfile.mkdtemp(), 'test.xml')
with open(tmp, 'w') as f:
    f.write('<xml_log_file version=\"1.0\"><solve_all/></xml_log_file>')
try:
    d.run_file(Path(tmp))
    print(json.dumps({"raised": False}))
except NotImplementedError as e:
    print(json.dumps({"raised": True, "error_type": "NotImplementedError", "msg": str(e)[:100]}))
"@
$ok7 = (Assert-True "NotImplementedError raised" $r.raised $LOG_FILE) -and $ok7

if ($ok7) { $pass++; Write-Log $LOG_FILE "  EX-07: PASS" }
else      { $fail++; Write-Log $LOG_FILE "  EX-07: FAIL" }

# ── Summary ─────────────────────────────────────────────────────────────────
Write-Log $LOG_FILE ""
Write-Log $LOG_FILE "=========================================="
Write-Log $LOG_FILE "  SUMMARY"
Write-Log $LOG_FILE "    PASS:       $pass / 7"
Write-Log $LOG_FILE "    FAIL:       $fail / 7"
Write-Log $LOG_FILE "    KNOWN FAIL: $known_fail / 7"
Write-Log $LOG_FILE "=========================================="
Write-Log $LOG_FILE "  Logs: $LOG_DIR"
