# run_helpers.ps1 — shared functions for all execution test scripts.
# Dot-source this file: . "$PSScriptRoot\run_helpers.ps1"
#
# Resolves paths from $PSScriptRoot. The .ps1 files live at
# <repo>/tests/execution/, so SIM_MAIN = $PSScriptRoot/../.. (the sim-cli repo root).
#
# `sim` must be on PATH (activate your venv first), or set $env:SIM_BIN.

if ($env:SIM_BIN) {
    $SIM = $env:SIM_BIN
} else {
    $simCmd = Get-Command sim -ErrorAction SilentlyContinue
    if ($null -eq $simCmd) {
        throw "sim CLI not found. Activate your venv (uv venv && uv pip install -e .) or set `$env:SIM_BIN."
    }
    $SIM = $simCmd.Source
}

$SCRIPT_DIR = $PSScriptRoot
$SNIPPETS   = Join-Path $PSScriptRoot "snippets"
$SIM_MAIN   = (Get-Item $PSScriptRoot).Parent.Parent.FullName

function New-LogDir {
    param([string]$CaseId)
    $ts      = Get-Date -Format "yyyyMMdd_HHmmss"
    $logDir  = "$SIM_MAIN\tests\execution\logs\${CaseId}_${ts}"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    return $logDir
}

function Write-Log {
    param([string]$LogFile, [string]$Message)
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "$ts  $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Invoke-IonStep {
    param(
        [string]$CaseId,
        [string]$Label,
        [string]$SnippetFile,
        [string]$LogDir,
        [string]$LogFile
    )

    Write-Log $LogFile ""
    Write-Log $LogFile "=== STEP: $Label ==="
    Write-Log $LogFile "    snippet: $SnippetFile"

    # Run the snippet
    $runOut = & $SIM run --code-file $SnippetFile --label $Label 2>&1
    $runOut | Out-File -FilePath "$LogDir\${Label}_run.txt" -Encoding utf8
    foreach ($line in $runOut) { Write-Log $LogFile "  run> $line" }

    $runExit = $LASTEXITCODE
    Write-Log $LogFile "    sim run exit code: $runExit"

    # Query last.result
    $queryOut = & $SIM query last.result 2>&1
    $queryOut | Out-File -FilePath "$LogDir\${Label}_result.json" -Encoding utf8
    Write-Log $LogFile "    last.result saved to ${Label}_result.json"

    # Parse ok field
    try {
        $parsed = $queryOut | ConvertFrom-Json -ErrorAction Stop
        $ok = $parsed.ok
    } catch {
        $ok = $false
        Write-Log $LogFile "    WARNING: could not parse last.result as JSON"
    }

    # Exit 1 = server-level error (protocol/serialization), Exit 2 = snippet exception
    if ($runExit -eq 1) {
        Write-Log $LogFile "WARNING: sim run exit 1 (server error, e.g. serialization). Checking last.result..."
        if ($ok -eq $false) {
            Write-Log $LogFile "ERROR: step '$Label' — server error AND ok=false. Stopping."
            & $SIM disconnect 2>&1 | Out-Null
            exit 1
        } else {
            Write-Log $LogFile "  Step '$Label' appears OK despite server warning (ok=true). Continuing."
        }
    } elseif ($runExit -eq 2 -or $ok -eq $false) {
        Write-Log $LogFile "ERROR: step '$Label' failed (ok=false or exit 2). Stopping test."
        Write-Log $LogFile "       See $LogDir\${Label}_result.json for details."
        # Disconnect cleanly before exit
        Write-Log $LogFile "  Disconnecting..."
        & $SIM disconnect 2>&1 | Out-Null
        exit 1
    }

    Write-Log $LogFile "    Step '$Label' OK"
    return $parsed
}

function Invoke-IonConnect {
    param(
        [string]$Mode,
        [string]$UiMode = "gui",
        [int]$Processors = 2,
        [string]$LogFile
    )
    Write-Log $LogFile "=== CONNECT: mode=$Mode ui_mode=$UiMode processors=$Processors ==="
    $connectOut = & $SIM connect --mode $Mode --ui-mode $UiMode --processors $Processors 2>&1
    $connectOut | ForEach-Object { Write-Log $LogFile "  connect> $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Log $LogFile "ERROR: sim connect failed (exit $LASTEXITCODE). Aborting."
        exit 1
    }
    Write-Log $LogFile "  Connect OK"
}

function Invoke-IonQuery {
    param([string]$Name, [string]$LogDir, [string]$Label, [string]$LogFile)
    $out = & $SIM query $Name 2>&1
    $out | Out-File -FilePath "$LogDir\query_${Label}.json" -Encoding utf8
    Write-Log $LogFile "  query $Name -> saved to query_${Label}.json"
    try { return $out | ConvertFrom-Json -ErrorAction Stop } catch { return $null }
}

function Invoke-IonDisconnect {
    param([string]$LogFile)
    Write-Log $LogFile ""
    Write-Log $LogFile "=== DISCONNECT ==="
    $out = & $SIM disconnect 2>&1
    $out | ForEach-Object { Write-Log $LogFile "  disconnect> $_" }
    Write-Log $LogFile "  Disconnect exit code: $LASTEXITCODE"
}
