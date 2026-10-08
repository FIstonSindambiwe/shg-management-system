# SHG Management System - one-time setup (safe to run again after updates)
# Double-click setup.bat, or run:  powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Continue"
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nSETUP STOPPED: $text" -ForegroundColor Red; exit 1 }

Set-Location $backend

# 1. Python ------------------------------------------------------------------
Step "Checking Python"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "Python is not installed. Run:  winget install Python.Python.3.12   then close and reopen this window."
}
$ver = (python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')").Trim()
Write-Host "Python $ver"
if ([version]$ver -lt [version]"3.10") { Fail "Python $ver is too old. Install Python 3.12." }

# 2. Virtual environment --------------------------------------------------------
Step "Preparing the virtual environment (.venv)"
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = Join-Path $backend ".venv/bin/python" }   # non-Windows fallback
if (-not (Test-Path $py)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }
    $py = Join-Path $backend ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = Join-Path $backend ".venv/bin/python" }
}

# 3. Packages ----------------------------------------------------------------------
Step "Installing packages (first time takes a few minutes)"
& $py -m pip install --upgrade pip --quiet --disable-pip-version-check
& $py -m pip install -r requirements.txt --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "Package install failed. Check your internet connection, then run setup again." }

# 4. Settings file ------------------------------------------------------------------
Step "Settings (.env)"
if (Test-Path ".env") {
    Write-Host ".env already exists - kept as it is."
} else {
    $key = (& $py -c "import secrets; print(secrets.token_urlsafe(50))").Trim()
    (Get-Content ".env.example") -replace '^DJANGO_SECRET_KEY=.*', "DJANGO_SECRET_KEY=$key" | Set-Content ".env"
    Write-Host "Created .env with a new secret key."
}

# 5. Backup before changing the database ------------------------------------------
$dbFile = Join-Path $root "data\shg_system.sqlite3"
if (-not (Test-Path $dbFile)) { $dbFile = Join-Path $root "data/shg_system.sqlite3" }
if (Test-Path $dbFile) {
    Step "Backing up the existing database"
    & $py manage.py backup_db
    if ($LASTEXITCODE -ne 0) { Fail "Backup failed, so the database was not changed." }
}

# 6. Database ------------------------------------------------------------------------
Step "Updating the database"
& $py manage.py migrate
if ($LASTEXITCODE -ne 0) { Fail "Database update (migrate) failed." }

# 7. First accounts ------------------------------------------------------------------
& $py manage.py seed_demo --check
if ($LASTEXITCODE -ne 0) {
    Step "Creating the first accounts"
    if ($env:SHG_ADMIN_PASSWORD -and $env:SHG_LEADER_PASSWORD) {
        $a = $env:SHG_ADMIN_PASSWORD; $l = $env:SHG_LEADER_PASSWORD; $okA = $true; $okL = $true
    } else {
    Write-Host "Choose passwords now (at least 8 characters). Nothing shows while you type."
    do {
        $a  = [System.Net.NetworkCredential]::new("", (Read-Host "Password for 'admin'" -AsSecureString)).Password
        $a2 = [System.Net.NetworkCredential]::new("", (Read-Host "Type it again" -AsSecureString)).Password
        $okA = ($a -eq $a2) -and ($a.Length -ge 8)
        if (-not $okA) { Write-Host "Passwords did not match or were shorter than 8. Try again." -ForegroundColor Yellow }
    } until ($okA)
    do {
        $l  = [System.Net.NetworkCredential]::new("", (Read-Host "Password for 'leader_amahoro'" -AsSecureString)).Password
        $l2 = [System.Net.NetworkCredential]::new("", (Read-Host "Type it again" -AsSecureString)).Password
        $okL = ($l -eq $l2) -and ($l.Length -ge 8)
        if (-not $okL) { Write-Host "Passwords did not match or were shorter than 8. Try again." -ForegroundColor Yellow }
    } until ($okL)
    }
    & $py manage.py seed_demo --admin-password $a --leader-password $l
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the first accounts." }
} else {
    Write-Host "`nAccounts already exist - kept as they are."
}

# 8. Frontend (React) ------------------------------------------------------------------
Step "Frontend (React)"
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location (Join-Path $root "frontend")
    npm install --no-fund --no-audit --loglevel=error
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm install failed." }
    Pop-Location
    Write-Host "Frontend ready. Start it with frontend.bat (after run.bat)."
} else {
    Write-Host "Node.js not found - the leader screen will not start." -ForegroundColor Yellow
    Write-Host "Install it with:  winget install OpenJS.NodeJS.LTS   then run setup again." -ForegroundColor Yellow
}

# 9. Tests -----------------------------------------------------------------------------
Step "Running the tests"
& $py manage.py test --noinput
if ($LASTEXITCODE -ne 0) { Fail "Some tests failed. Send the red text above to the developer." }

Write-Host "`nSETUP COMPLETE." -ForegroundColor Green
Write-Host "1. Double-click run.bat       - the server (keep it open)"
Write-Host "2. Double-click frontend.bat  - the leader screen at http://localhost:5173/"
Write-Host "   The admin pages stay at http://127.0.0.1:8000/admin/"
