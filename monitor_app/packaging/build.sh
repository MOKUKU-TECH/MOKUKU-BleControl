#!/usr/bin/env bash
# Build the MOKUKU Vibe Monitor onedir bundle on Linux and zip it.
# Optional arg: the zip basename (default MOKUKU-Vibe-Monitor-linux).
set -euo pipefail

name="${1:-MOKUKU-Vibe-Monitor-linux}"

cd "$(dirname "$0")/.."  # BleControl/monitor_app

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --clean --noconfirm packaging/vibe_monitor.spec

cd dist
zip -r "$name.zip" "MOKUKU Vibe Monitor" >/dev/null
echo "built: dist/$name.zip"
