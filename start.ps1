# Starts the Light Show Generator (builds the web UI on first run).
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Setting up Python environment..."
    python -m venv (Join-Path $root "backend\.venv")
    & $python -m pip install -e (Join-Path $root "backend")
}
if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
    Write-Host "Building web UI..."
    Push-Location (Join-Path $root "frontend")
    npm install
    npm run build
    Pop-Location
}
Start-Process "http://127.0.0.1:$(if ($env:LSG_PORT) { $env:LSG_PORT } else { 8000 })"
& $python -m lsg.app
