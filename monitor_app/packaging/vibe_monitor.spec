# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the MOKUKU Vibe Monitor.

Onedir (not onefile): a onefile bundle re-extracts the whole ~50 MB PyQt/bleak
payload to a temp dir on every launch, which the hook path (`<exe>
--hook-report`, run on every Claude Code event) would pay each time. Onedir
leaves the files on disk and imports lazily, so main.py's early argv dispatch
keeps the hook path off the PyQt/bleak imports entirely.

Build:  pyinstaller --clean --noconfirm packaging/vibe_monitor.spec
Output: dist/MOKUKU Vibe Monitor/  (zip this folder for distribution)
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

HERE = Path(SPECPATH).parent  # BleControl/monitor_app

datas, binaries, hiddenimports = [], [], []


def _collect(pkg):
    try:
        d, b, h = collect_all(pkg)
        datas.extend(d)
        binaries.extend(b)
        hiddenimports.extend(h)
    except Exception:
        pass  # optional/platform-specific package not installed here


for pkg in ("bleak", "coloredlogs", "humanfriendly"):
    _collect(pkg)

if sys.platform.startswith("win"):
    hiddenimports += ["bleak.backends.winrt", "bleak.backends.winrt.client",
                      "bleak.backends.winrt.scanner"]
    _collect("winrt")
else:
    hiddenimports += ["bleak.backends.bluezdbus"]
    _collect("dbus_fast")

a = Analysis(
    [str(HERE / "main.py")],
    pathex=[str(HERE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MOKUKU Vibe Monitor",
    console=False,  # no console window when double-clicked; hook stdin still pipes in
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="MOKUKU Vibe Monitor",
)
