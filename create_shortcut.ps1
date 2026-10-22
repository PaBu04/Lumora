# Creates a desktop shortcut "Light Show Generator" that opens the app in its own window.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root "backend\.venv\Scripts"
$launcher = Join-Path $venv "lsg-desktop.exe"
if (-not (Test-Path $launcher)) {
    Write-Host "Installing the app first..."
    if (-not (Test-Path (Join-Path $venv "python.exe"))) { python -m venv (Join-Path $root "backend\.venv") }
    & (Join-Path $venv "python.exe") -m pip install -e (Join-Path $root "backend")
}
if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
    Push-Location (Join-Path $root "frontend"); npm install; npm run build; Pop-Location
}
$icon = Join-Path $root "backend\lsg\static\app.ico"
& (Join-Path $venv "python.exe") -m lsg.tools.make_icon $icon
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Light Show Generator.lnk"))
$link.TargetPath = $launcher
$link.WorkingDirectory = Join-Path $root "backend"
$link.IconLocation = $icon
$link.Description = "Musiksynchrone LED-Lichtshows"
$link.Save()
Write-Host "Shortcut created on the desktop."
