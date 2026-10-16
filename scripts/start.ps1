<#
.SYNOPSIS
  Start OpsPilot AI locally (API + dashboard) - robust, one command, no Docker.

.DESCRIPTION
  * Finds a real Python 3.10+ (skips the Microsoft Store "python" stub) and Node.js 20+.
  * Creates backend\.venv and installs dependencies on first run (or when requirements change).
  * Generates a .env with random secrets on first run.
  * Frees ports held by stale OpsPilot servers; if another program owns a port, picks the next free one.
  * Seeds the demo tenant (idempotent), starts the API, waits until it is healthy.
  * Builds the dashboard if needed and starts it (production mode by default; -Dev for hot reload).
  * The dashboard proxies /api/v1 to the API, so CORS / localhost-vs-127.0.0.1 issues cannot occur.
  * Optional -Workers N starts N extra background worker processes (durable job queue) for scale.
  * Logs go to .run\logs; process ids to .run\pids.json; stop everything with scripts\stop.ps1.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Dev -Workers 2
#>
param(
  [int]$ApiPort = 8000,
  [int]$WebPort = 3000,
  [switch]$Dev,
  [int]$Workers = 0,
  [switch]$NoBrowser,
  [switch]$Reinstall
)
# "Continue": Windows PowerShell 5.1 turns any stderr line from a native program into a
# terminating error under "Stop" (even on success). Native steps are checked via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$runDir = Join-Path $root ".run"
$logDir = Join-Path $runDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Say($msg, $color = "Gray") { Write-Host $msg -ForegroundColor $color }
function Ok($msg) { Say "  [ok] $msg" "Green" }
function Warn($msg) { Say "  [!!] $msg" "Yellow" }
function Fail($msg) { Say "  [xx] $msg" "Red"; exit 1 }

Say "`nOpsPilot AI - local launcher" "Cyan"
Say "  project: $root"

# --- Python -------------------------------------------------------------------
function Test-Python($exe) {
  if (-not $exe -or -not (Test-Path $exe)) { return $false }
  if ($exe -like "*\WindowsApps\*") { return $false }   # Microsoft Store stub, not a real interpreter
  try { $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null } catch { return $false }
  if (-not $v) { return $false }
  $parts = $v.Trim().Split("."); return ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)
}
$venvPy = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Python $venvPy) -or $Reinstall) {
  $candidates = @()
  $candidates += (Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
  $candidates += @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe", "C:\Program Files\Python312\python.exe")
  $py = $null
  try { $pyLauncher = (& py -3 -c "import sys; print(sys.executable)" 2>$null); if ($pyLauncher) { $candidates = @($pyLauncher.Trim()) + $candidates } } catch {}
  foreach ($c in $candidates) { if (Test-Python $c) { $py = $c; break } }
  if (-not $py) { Fail "Python 3.10+ not found. Install it with:  winget install Python.Python.3.12   (then open a NEW terminal)" }
  Ok "Python: $py"
  if (Test-Path (Join-Path $backend ".venv")) { if ($Reinstall) { Remove-Item -Recurse -Force (Join-Path $backend ".venv") } }
  if (-not (Test-Path $venvPy)) { Say "  creating virtualenv..."; & $py -m venv (Join-Path $backend ".venv") }
}
Ok "venv: $venvPy"

$reqFile = Join-Path $backend "requirements-dev.txt"
$stamp = Join-Path $runDir "requirements.sha256"
$reqHash = (Get-FileHash $reqFile).Hash + (Get-FileHash (Join-Path $backend "requirements.txt")).Hash
$needInstall = $Reinstall -or -not (Test-Path $stamp) -or ((Get-Content $stamp -ErrorAction SilentlyContinue) -ne $reqHash)
if (-not $needInstall) { & $venvPy -c "import fastapi, sqlalchemy, anthropic" 2>$null; if ($LASTEXITCODE -ne 0) { $needInstall = $true } }
if ($needInstall) {
  Say "  installing backend dependencies (first run takes a few minutes)..."
  & $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
  & $venvPy -m pip install -r $reqFile --quiet --disable-pip-version-check
  if ($LASTEXITCODE -ne 0) { Fail "pip install failed - see the output above" }
  Set-Content -Path $stamp -Value $reqHash -Encoding ascii
}
Ok "backend dependencies installed"

# --- Node ---------------------------------------------------------------------
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node -and (Test-Path "C:\Program Files\nodejs\node.exe")) { $node = "C:\Program Files\nodejs\node.exe" }
if (-not $node) { Fail "Node.js 20+ not found. Install it with:  winget install OpenJS.NodeJS.LTS   (then open a NEW terminal)" }
$npm = Join-Path (Split-Path $node) "npm.cmd"
$nodeMajor = [int]((& $node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 20) { Fail "Node.js $nodeMajor found; version 20 or newer is required" }
Ok "Node: $node (v$nodeMajor)"
if (-not (Test-Path (Join-Path $frontend "node_modules\next")) -or $Reinstall) {
  Say "  installing dashboard dependencies..."
  Push-Location $frontend; & $npm install --no-audit --no-fund; $code = $LASTEXITCODE; Pop-Location
  if ($code -ne 0) { Fail "npm install failed - see the output above" }
}
Ok "dashboard dependencies installed"

# --- .env -----------------------------------------------------------------------
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
  $secret = & $venvPy -c "import secrets; print(secrets.token_urlsafe(48))"
  $fernet = & $venvPy -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  $content = (Get-Content (Join-Path $root ".env.example") -Raw) -replace "(?m)^SECRET_KEY=.*$", "SECRET_KEY=$secret" -replace "(?m)^ENCRYPTION_KEY=.*$", "ENCRYPTION_KEY=$fernet"
  [IO.File]::WriteAllText($envFile, $content, (New-Object System.Text.UTF8Encoding $false))
  Ok "created .env with fresh random secrets"
}

# --- Ports ----------------------------------------------------------------------
function Get-PortOwner($port) {
  $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $conn) { return $null }
  return Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)"
}
function Resolve-Port($port, $label) {
  for ($p = $port; $p -lt $port + 20; $p++) {
    $owner = Get-PortOwner $p
    if (-not $owner) { return $p }
    $cmd = "$($owner.CommandLine)"
    if ($cmd -match "OpsPilot" -or $cmd -match "app\.main:app" -or $cmd -match "app\.cli" -or $cmd -match "next[\\/]dist[\\/]bin[\\/]next") {
      Warn "port $p held by a stale OpsPilot $label (pid $($owner.ProcessId)) - stopping it"
      Stop-Process -Id $owner.ProcessId -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 800
      if (-not (Get-PortOwner $p)) { return $p }
    } else {
      Warn "port $p is used by another program ($($owner.Name)); trying $($p + 1)"
    }
  }
  Fail "no free port found near $port for the $label"
}
& (Join-Path $PSScriptRoot "stop.ps1") -Quiet
$ApiPort = Resolve-Port $ApiPort "API"
$WebPort = Resolve-Port $WebPort "dashboard"
Ok "ports: API $ApiPort, dashboard $WebPort"

# --- Seed + API -----------------------------------------------------------------------
Push-Location $backend
$env:PYTHONUTF8 = "1"
# SQLite gets its schema from create_all during seed; PostgreSQL (e.g. Neon) is migrated with Alembic first.
$isSqlite = (& $venvPy -c "from app.core.config import get_settings; print(get_settings().is_sqlite)" 2>$null)
if ("$isSqlite".Trim() -eq "False") {
  & $venvPy -m alembic upgrade head *> (Join-Path $logDir "migrate.log")
  if ($LASTEXITCODE -ne 0) { Pop-Location; Get-Content (Join-Path $logDir "migrate.log") -Tail 30; Fail "database migration failed (log above) - check DATABASE_URL in .env" }
  Ok "PostgreSQL schema migrated (alembic upgrade head)"
}
& $venvPy -m app.cli seed *> (Join-Path $logDir "seed.log")
if ($LASTEXITCODE -ne 0) { Pop-Location; Get-Content (Join-Path $logDir "seed.log") -Tail 30; Fail "database seed failed (log above)" }
Pop-Location
Ok "database ready (demo tenant seeded)"

$pids = @{}
$env:CORS_ORIGINS = "http://localhost:$WebPort,http://127.0.0.1:$WebPort"
$apiLog = Join-Path $logDir "api.log"
$workerMode = if ($Workers -gt 0) { "db" } else { "thread" }
$env:WORKER_MODE = $workerMode
$api = Start-Process -FilePath $venvPy -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort" -WorkingDirectory $backend -RedirectStandardOutput $apiLog -RedirectStandardError "$apiLog.err" -PassThru -WindowStyle Hidden
$pids.api = $api.Id
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Milliseconds 700
  if ($api.HasExited) { break }
  try { $r = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 3; if ($r.status) { $healthy = $true; break } } catch {}
}
if (-not $healthy) { Say "`n--- api.log (stderr) ---"; Get-Content "$apiLog.err" -Tail 40 -ErrorAction SilentlyContinue; Fail "API did not become healthy on port $ApiPort" }
Ok "API healthy  http://127.0.0.1:$ApiPort/docs"

for ($w = 1; $w -le $Workers; $w++) {
  $wl = Join-Path $logDir "worker$w.log"
  $wp = Start-Process -FilePath $venvPy -ArgumentList "-m", "app.workers.runner", "--concurrency", "4", "--name", "worker-$w" -WorkingDirectory $backend -RedirectStandardOutput $wl -RedirectStandardError "$wl.err" -PassThru -WindowStyle Hidden
  $pids["worker$w"] = $wp.Id
}
if ($Workers -gt 0) { Ok "$Workers background worker process(es) started (durable DB job queue)" }

# --- Dashboard ----------------------------------------------------------------------
$env:OPSPILOT_API_ORIGIN = "http://127.0.0.1:$ApiPort"
$env:NEXT_TELEMETRY_DISABLED = "1"
$nextBin = Join-Path $frontend "node_modules\next\dist\bin\next"
$webLog = Join-Path $logDir "web.log"
if (-not $Dev) {
  $buildId = Join-Path $frontend ".next\BUILD_ID"
  $srcNewest = (Get-ChildItem -Recurse -File -Path (Join-Path $frontend "app"), (Join-Path $frontend "components"), (Join-Path $frontend "lib") | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
  if (-not (Test-Path $buildId) -or (Get-Item $buildId).LastWriteTime -lt $srcNewest) {
    Say "  building the dashboard (about a minute)..."
    Push-Location $frontend; & $node $nextBin build *> (Join-Path $logDir "build.log"); $code = $LASTEXITCODE; Pop-Location
    if ($code -ne 0) { Get-Content (Join-Path $logDir "build.log") -Tail 40; Fail "dashboard build failed (log above)" }
  }
  $web = Start-Process -FilePath $node -ArgumentList $nextBin, "start", "-p", "$WebPort", "-H", "0.0.0.0" -WorkingDirectory $frontend -RedirectStandardOutput $webLog -RedirectStandardError "$webLog.err" -PassThru -WindowStyle Hidden
} else {
  $web = Start-Process -FilePath $node -ArgumentList $nextBin, "dev", "-p", "$WebPort" -WorkingDirectory $frontend -RedirectStandardOutput $webLog -RedirectStandardError "$webLog.err" -PassThru -WindowStyle Hidden
}
$pids.web = $web.Id
$webOk = $false
for ($i = 0; $i -lt 120; $i++) {
  Start-Sleep -Milliseconds 700
  if ($web.HasExited) { break }
  try { $r = Invoke-WebRequest "http://localhost:$WebPort/api/v1/health" -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { $webOk = $true; break } } catch {}
}
($pids | ConvertTo-Json) | Set-Content (Join-Path $runDir "pids.json") -Encoding ascii
if (-not $webOk) { Say "`n--- web.log ---"; Get-Content $webLog -Tail 30 -ErrorAction SilentlyContinue; Get-Content "$webLog.err" -Tail 30 -ErrorAction SilentlyContinue; Fail "dashboard did not start on port $WebPort" }
Ok "dashboard ready and connected to the API through its proxy"

$url = "http://localhost:$WebPort"
Say "`n  OpsPilot is running:" "Cyan"
Say "    Dashboard  $url"
Say "    API docs   http://127.0.0.1:$ApiPort/docs"
Say "    Sign in    tenant acme-demo / any demo account / password OpsPilot-Demo-2026!"
Say "    Logs       $logDir"
Say "    Stop       powershell -ExecutionPolicy Bypass -File scripts\stop.ps1`n"
if (-not $NoBrowser) { Start-Process $url }
