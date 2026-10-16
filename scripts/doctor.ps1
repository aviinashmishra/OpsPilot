<#
.SYNOPSIS
  Diagnose why OpsPilot is not working on localhost and print the exact fix.
#>
param([int]$ApiPort = 8000, [int]$WebPort = 3000)
$root = Split-Path -Parent $PSScriptRoot
$problems = 0
function Check($ok, $label, $fix) {
  if ($ok) { Write-Host "  [ok] $label" -ForegroundColor Green }
  else { Write-Host "  [xx] $label" -ForegroundColor Red; Write-Host "       fix: $fix" -ForegroundColor Yellow; $script:problems++ }
}
Write-Host "`nOpsPilot doctor - $root`n" -ForegroundColor Cyan
Check ((Get-Location).Path -notlike "*\Desktop\Agent\Agent*") "running from the project folder" "the project lives in $root - open that folder (cd $root)"
$venvPy = Join-Path $root "backend\.venv\Scripts\python.exe"
Check (Test-Path $venvPy) "backend virtualenv exists" "run start.cmd (it creates it)"
if (Test-Path $venvPy) {
  & $venvPy -c "import fastapi, sqlalchemy, anthropic" 2>$null
  Check ($LASTEXITCODE -eq 0) "backend dependencies importable" "powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Reinstall"
}
$node = (Get-Command node -ErrorAction SilentlyContinue).Source; if (-not $node -and (Test-Path "C:\Program Files\nodejs\node.exe")) { $node = "C:\Program Files\nodejs\node.exe" }
Check ([bool]$node) "Node.js installed" "winget install OpenJS.NodeJS.LTS"
Check (Test-Path (Join-Path $root "frontend\node_modules\next")) "dashboard dependencies installed" "cd frontend; npm install"
foreach ($pair in @(@($ApiPort, "API"), @($WebPort, "dashboard"))) {
  $conn = Get-NetTCPConnection -State Listen -LocalPort $pair[0] -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)"
    $ours = "$($proc.CommandLine)" -match "OpsPilot|app\.main|next"
    Check $ours "port $($pair[0]) ($($pair[1])) is served by OpsPilot" "port $($pair[0]) is taken by '$($proc.Name)' (pid $($proc.ProcessId)); stop it or run start.ps1 -ApiPort/-WebPort with another port"
  } else {
    Check $false "port $($pair[0]) ($($pair[1])) is listening" "start everything with start.cmd"
  }
}
try { $h = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 5; Check ($h.status -eq "ok") "API health: $($h.status) (db=$($h.database), llm=$($h.llm_provider))" "see .run\logs\api.log.err" } catch { Check $false "API answers on http://127.0.0.1:$ApiPort" "see .run\logs\api.log.err, then start.cmd" }
try { $w = Invoke-WebRequest "http://localhost:$WebPort/api/v1/health" -UseBasicParsing -TimeoutSec 10; Check ($w.StatusCode -eq 200) "dashboard proxy reaches the API" "check OPSPILOT_API_ORIGIN in frontend\.env.local" } catch { Check $false "dashboard reachable on http://localhost:$WebPort" "see .run\logs\web.log, then start.cmd" }
try { $l = Invoke-RestMethod -Method Post "http://127.0.0.1:$ApiPort/api/v1/auth/login" -ContentType "application/json" -Body '{"tenant":"acme-demo","email":"admin@acme-demo.test","password":"OpsPilot-Demo-2026!"}' -TimeoutSec 10; Check ([bool]$l.access_token) "demo login works" "re-seed: cd backend; .venv\Scripts\python -m app.cli seed" } catch { Check $false "demo login works" "re-seed: cd backend; .venv\Scripts\python -m app.cli seed" }
foreach ($log in @("api.log.err", "web.log.err")) {
  $f = Join-Path $root ".run\logs\$log"
  if (Test-Path $f) { $errs = Select-String -Path $f -Pattern "Traceback|Error:|EADDRINUSE" -SimpleMatch:$false | Select-Object -Last 3; if ($errs) { Write-Host "  recent errors in ${log}:" -ForegroundColor Yellow; $errs | ForEach-Object { Write-Host "    $($_.Line)" } } }
}
if ($problems -eq 0) { Write-Host "`nEverything looks healthy. Open http://localhost:$WebPort`n" -ForegroundColor Green } else { Write-Host "`n$problems problem(s) found - apply the fixes above, then run start.cmd`n" -ForegroundColor Yellow }
