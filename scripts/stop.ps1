<#
.SYNOPSIS
  Stop every OpsPilot process started by scripts\start.ps1 (and any stray OpsPilot servers).
#>
param([switch]$Quiet)
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".run\pids.json"
$stopped = 0
if (Test-Path $pidFile) {
  $pids = Get-Content $pidFile -Raw | ConvertFrom-Json
  foreach ($p in $pids.PSObject.Properties) {
    $proc = Get-Process -Id $p.Value -ErrorAction SilentlyContinue
    if ($proc) { Stop-Process -Id $p.Value -Force -ErrorAction SilentlyContinue; $stopped++ }
  }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
# Stray processes from earlier runs (matched strictly on this project's paths/entry points).
$escaped = [regex]::Escape($root)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  $c = "$($_.CommandLine)"
  ($c -match $escaped -and ($c -match "uvicorn|app\.cli|app\.workers|next[\\/]dist[\\/]bin[\\/]next|next start|next dev"))
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped++ }
if (-not $Quiet) { Write-Host "Stopped $stopped OpsPilot process(es)." }
