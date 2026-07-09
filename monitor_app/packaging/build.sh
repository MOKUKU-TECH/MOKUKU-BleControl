#!/usr/bin/env bash
# Build the MOKUKU Vibe Monitor onedir bundle on Linux and zip it.
set -euo pipefail

cd "$(dirname "$0")/.."  # BleControl/monitor_app

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --clean --noconfirm packaging/vibe_monitor.spec

cd dist
zip -r "MOKUKU-Vibe-Monitor-linux.zip" "MOKUKU Vibe Monitor" >/dev/null
echo "built: dist/MOKUKU-Vibe-Monitor-linux.zip"
