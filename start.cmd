@echo off
rem Double-click to start OpsPilot AI (API + dashboard). Pass -Dev for hot reload, -Workers 2 for extra workers.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 (
  echo.
  echo Startup failed. Diagnose with:  powershell -ExecutionPolicy Bypass -File "%~dp0scripts\doctor.ps1"
  pause
)
