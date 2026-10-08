# Make a verified backup of the database now.
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
Set-Location $backend
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = Join-Path $backend ".venv/bin/python" }
& $py manage.py backup_db
