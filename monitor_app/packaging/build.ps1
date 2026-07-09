# Build the MOKUKU Vibe Monitor onedir bundle on Windows and zip it.
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")  # BleControl\monitor_app

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --clean --noconfirm packaging/vibe_monitor.spec

$src = "dist/MOKUKU Vibe Monitor"
$zip = "dist/MOKUKU-Vibe-Monitor-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $src -DestinationPath $zip
Write-Host "built: $zip"
