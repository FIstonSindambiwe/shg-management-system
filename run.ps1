# Start the SHG Management System on this computer.
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
Set-Location $backend
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = Join-Path $backend ".venv/bin/python" }
if (-not (Test-Path $py)) {
    Write-Host "Not set up yet. Run setup.bat first." -ForegroundColor Red
    exit 1
}
Write-Host "Opening http://127.0.0.1:8000/admin/  (press Ctrl+C here to stop)" -ForegroundColor Green
Start-Process "http://127.0.0.1:8000/admin/" -ErrorAction SilentlyContinue
& $py manage.py runserver
