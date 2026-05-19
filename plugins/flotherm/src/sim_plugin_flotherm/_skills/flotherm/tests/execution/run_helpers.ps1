# run_helpers.ps1 — shared functions for flotherm execution test scripts.
# Dot-source this file: . "$PSScriptRoot\run_helpers.ps1"

$env:PYTHONPATH = "E:\sim\sim\src"
$PYTHON = "python"
$FLOTHERM_ROOT = "E:\Program Files (x86)\Siemens\SimcenterFlotherm\2504"
$EXAMPLES = "$FLOTHERM_ROOT\examples"
$PACK_MOBILE_DEMO = "$EXAMPLES\FloSCRIPT\Demonstration Examples\Transient Power Update\Mobile_Demo-Steady_State.pack"
$PACK_SUPERPOSITION = "$EXAMPLES\Demonstration Models\Superposition\SuperPosition.pack"
$XML_GRID_HEATSINKS = "$EXAMPLES\FloSCRIPT\Utilities\Grid-HeatSinks-and-Fans.xml"
$XML_MAKE_TUBE = "$EXAMPLES\FloSCRIPT\Demonstration Examples\Voxelization\Make_Tube.xml"
$AGENT_ROOT = "E:\sim\sim-agent-flotherm"

function New-LogDir {
    param([string]$CaseId)
    $ts     = Get-Date -Format "yyyyMMdd_HHmmss"
    $logDir = "$AGENT_ROOT\tests\execution\logs\${CaseId}_${ts}"
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

function Invoke-Driver {
    <#
    .SYNOPSIS
    Execute a Python snippet against the FlothermDriver and return parsed JSON.
    Writes code to a temp .py file to avoid PowerShell/cmd quoting issues.
    #>
    param(
        [string]$Code,
        [string]$LogFile,
        [string]$Label = ""
    )
    $header = @"
import sys, json
sys.path.insert(0, r'E:\sim\sim\src')
from pathlib import Path
from sim.drivers.flotherm.driver import FlothermDriver
d = FlothermDriver()
try:
"@
    $footer = @"

except Exception as e:
    print(json.dumps({"error": str(e), "error_type": type(e).__name__}))
"@
    # Indent user code by 4 spaces for the try block
    $indented = ($Code -split "`n" | ForEach-Object { "    $_" }) -join "`n"
    $fullCode = "$header`n$indented`n$footer"

    $tmpFile = [System.IO.Path]::GetTempFileName() -replace '\.tmp$', '.py'
    Set-Content -Path $tmpFile -Value $fullCode -Encoding UTF8
    $result = & $PYTHON $tmpFile 2>&1
    Remove-Item -Path $tmpFile -Force -ErrorAction SilentlyContinue
    if ($Label) { Write-Log $LogFile "  [$Label] $result" }
    try {
        return $result | ConvertFrom-Json -ErrorAction Stop
    } catch {
        if ($Label) { Write-Log $LogFile "  [$Label] RAW: $result" }
        return $null
    }
}

function Assert-Equal {
    param([string]$Field, $Actual, $Expected, [string]$LogFile)
    if ($Actual -eq $Expected) {
        Write-Log $LogFile "    PASS: $Field = $Actual"
        return $true
    } else {
        Write-Log $LogFile "    FAIL: $Field = $Actual (expected: $Expected)"
        return $false
    }
}

function Assert-True {
    param([string]$Field, $Value, [string]$LogFile)
    if ($Value) {
        Write-Log $LogFile "    PASS: $Field = True"
        return $true
    } else {
        Write-Log $LogFile "    FAIL: $Field = False (expected: True)"
        return $false
    }
}

function Assert-Contains {
    param([string]$Field, [string]$Haystack, [string]$Needle, [string]$LogFile)
    if ($Haystack -match [regex]::Escape($Needle)) {
        Write-Log $LogFile "    PASS: $Field contains '$Needle'"
        return $true
    } else {
        Write-Log $LogFile "    FAIL: $Field does not contain '$Needle'"
        return $false
    }
}
