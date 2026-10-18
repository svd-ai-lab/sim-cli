param(
  [string[]]$Roots = @(),
  [string[]]$CommandNames = @("VolumeExtract", "Enclosure", "Export", "Import", "NamedSelection", "ShareTopology"),
  [switch]$AllDocs
)

$ErrorActionPreference = "SilentlyContinue"

function Add-Unique {
  param(
    [System.Collections.Generic.List[string]]$List,
    [string]$Value
  )
  if ($Value -and -not $List.Contains($Value)) {
    $List.Add($Value) | Out-Null
  }
}

function Get-AnsysRootFromExe {
  param([string]$Exe)
  $dir = Split-Path -Parent $Exe
  if ((Split-Path -Leaf $dir) -in @("scdm", "Discovery")) {
    return Split-Path -Parent $dir
  }
  return $dir
}

$candidateExes = [System.Collections.Generic.List[string]]::new()

foreach ($root in $Roots) {
  Add-Unique $candidateExes (Join-Path $root "SpaceClaim.exe")
  Add-Unique $candidateExes (Join-Path $root "scdm\SpaceClaim.exe")
  Add-Unique $candidateExes (Join-Path $root "Discovery\SpaceClaim.exe")
}

foreach ($envName in @("SIM_SPACECLAIM_ROOT", "SPACECLAIM_ROOT", "AWP_ROOT261", "AWP_ROOT252", "AWP_ROOT251", "AWP_ROOT242", "AWP_ROOT241")) {
  $value = [Environment]::GetEnvironmentVariable($envName)
  if ($value) {
    Add-Unique $candidateExes (Join-Path $value "SpaceClaim.exe")
    Add-Unique $candidateExes (Join-Path $value "scdm\SpaceClaim.exe")
    Add-Unique $candidateExes (Join-Path $value "Discovery\SpaceClaim.exe")
  }
}

$cmd = Get-Command SpaceClaim.exe
if ($cmd) {
  Add-Unique $candidateExes $cmd.Source
}

foreach ($pattern in @(
  "C:\Program Files\ANSYS Inc\*\scdm\SpaceClaim.exe",
  "C:\Program Files\ANSYS Inc\ANSYS Student\*\scdm\SpaceClaim.exe",
  "C:\Program Files\ANSYS Inc\*\Discovery\SpaceClaim.exe",
  "C:\Program Files\ANSYS Inc\ANSYS Student\*\Discovery\SpaceClaim.exe"
)) {
  Get-ChildItem -Path $pattern | ForEach-Object { Add-Unique $candidateExes $_.FullName }
}

$foundExes = @($candidateExes | Where-Object { Test-Path -LiteralPath $_ })
$rootsFound = [System.Collections.Generic.List[string]]::new()
foreach ($exe in $foundExes) {
  Add-Unique $rootsFound (Get-AnsysRootFromExe $exe)
}

$preferredApiVersions = [System.Collections.Generic.List[int]]::new()
foreach ($root in $rootsFound) {
  $leaf = Split-Path -Leaf $root
  if ($leaf -match "^v(\d+)$") {
    $version = [int]$Matches[1]
    if (-not $preferredApiVersions.Contains($version)) {
      $preferredApiVersions.Add($version) | Out-Null
    }
  }
}

function Get-ApiVersion {
  param([string]$Path)
  if ($Path -match "SpaceClaim\.Api\.V(\d+)") {
    return [int]$Matches[1]
  }
  return 0
}

$docFiles = [System.Collections.Generic.List[string]]::new()
foreach ($root in $rootsFound) {
  foreach ($docPattern in @(
    "scdm\SpaceClaim.Api*.xml",
    "scdm\SpaceClaim.Api*\*.xml",
    "scdm\SpaceClaim.Api*.chm",
    "scdm\SpaceClaim.Api*\*.chm",
    "Discovery\SpaceClaim.Api*.xml",
    "Discovery\SpaceClaim.Api*\*.xml",
    "Discovery\SpaceClaim.Api*.chm",
    "Discovery\SpaceClaim.Api*\*.chm"
  )) {
    Get-ChildItem -Path (Join-Path $root $docPattern) | ForEach-Object { Add-Unique $docFiles $_.FullName }
  }
}

$xmlDocs = @($docFiles | Where-Object { $_ -like "*.xml" })
if (-not $AllDocs) {
  $preferredDocs = @()
  foreach ($doc in $xmlDocs) {
    if ($preferredApiVersions.Contains((Get-ApiVersion $doc))) {
      $preferredDocs += $doc
    }
  }
  if ($preferredDocs) {
    $xmlDocs = @($preferredDocs | Sort-Object { if ($_ -like "*.Scripting.xml") { 0 } else { 1 } }, { $_ } | Select-Object -First 4)
  } else {
    $latestApiVersion = @($xmlDocs | ForEach-Object { Get-ApiVersion $_ } | Sort-Object -Descending | Select-Object -First 1)[0]
    $xmlDocs = @($xmlDocs | Where-Object { (Get-ApiVersion $_) -eq $latestApiVersion } | Sort-Object | Select-Object -First 4)
  }
}

$commandHits = @()
foreach ($doc in $xmlDocs) {
  foreach ($name in $CommandNames) {
    $hit = Select-String -LiteralPath $doc -Pattern $name -SimpleMatch | Select-Object -First 3
    if ($hit) {
      $commandHits += [pscustomobject]@{
        command = $name
        file = $doc
        matches = @($hit | ForEach-Object { "line $($_.LineNumber): $($_.Line.Trim())" })
      }
    }
  }
}

[pscustomobject]@{
  found = [bool]$foundExes
  executables = @($foundExes)
  ansys_roots = @($rootsFound)
  latest_api_docs = @($xmlDocs)
  api_doc_count = @($docFiles).Count
  command_hits = @($commandHits)
} | ConvertTo-Json -Depth 6
