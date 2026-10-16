<#
.SYNOPSIS
  Kept for backwards compatibility: starts OpsPilot in hot-reload mode via scripts\start.ps1.
#>
& (Join-Path $PSScriptRoot "start.ps1") -Dev @args
