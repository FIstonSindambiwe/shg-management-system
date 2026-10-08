# Start the leader screen (React). Run run.bat first - this needs the server.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$front = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $front "node_modules"))) {
    Write-Host "Packages missing. Run setup.bat first (Node.js must be installed)." -ForegroundColor Red
    exit 1
}
Set-Location $front
Write-Host "Leader screen: http://localhost:5173/" -ForegroundColor Green
Write-Host "On a phone on the same wifi, use the Network address printed below." -ForegroundColor Green
Write-Host "For a phone, add your computer's IP to DJANGO_ALLOWED_HOSTS in backend\.env first." -ForegroundColor DarkGray
npm run dev -- --host
