#!/usr/bin/env python3
"""Installs a .desktop launcher for vibe_monitor_app.py, so it's a normal
clickable app instead of something you have to open a terminal for.

Installs to ~/.local/share/applications/ (shows up in your app menu/search -
e.g. GNOME Activities "Vibe Monitor") and, if ~/Desktop exists, also drops a
copy there for a literal desktop icon.

Usage:
    python3 install_desktop_launcher.py                # install
    python3 install_desktop_launcher.py --python PATH  # use a specific interpreter
    python3 install_desktop_launcher.py --remove        # uninstall

Uses the interpreter running this installer (sys.executable) by default -
run it from whichever environment actually has PyQt5 and bleak installed
(the same one you'd use to run `python vibe_monitor_app.py` yourself).

Note: some file managers (e.g. GNOME Files/Nautilus) show an "Untrusted
Application Launcher" prompt the first time you double-click a new .desktop
file on the Desktop - click "Trust and Launch" (or right-click -> "Allow
Launching") once and it won't ask again.
"""
import argparse
import subprocess
import sys
from pathlib import Path

APP_NAME = "MOKUKU Vibe Monitor"
DESKTOP_FILENAME = "mokuku-vibe-monitor.desktop"
SCRIPT_PATH = (Path(__file__).resolve().parent / "vibe_monitor_app.py")

APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"
DESKTOP_DIR = Path.home() / "Desktop"


def render_desktop_entry(python_path: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={APP_NAME}\n"
        "Comment=Connect to MOKUKU over BLE and forward Claude Code status to it\n"
        f"Exec={python_path} {SCRIPT_PATH}\n"
        f"Path={SCRIPT_PATH.parent}\n"
        "Icon=bluetooth\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "StartupNotify=true\n"
    )


def install(python_path: str, dry_run: bool) -> None:
    content = render_desktop_entry(python_path)
    if dry_run:
        print(content)
        return

    SCRIPT_PATH.chmod(SCRIPT_PATH.stat().st_mode | 0o111)  # ensure it's executable too

    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    app_menu_path = APPLICATIONS_DIR / DESKTOP_FILENAME
    app_menu_path.write_text(content)
    app_menu_path.chmod(0o755)
    print(f"wrote {app_menu_path}")

    if DESKTOP_DIR.is_dir():
        desktop_icon_path = DESKTOP_DIR / DESKTOP_FILENAME
        desktop_icon_path.write_text(content)
        desktop_icon_path.chmod(0o755)
        print(f"wrote {desktop_icon_path}")
        try:
            subprocess.run(["gio", "set", str(desktop_icon_path), "metadata::trusted", "true"],
                            check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            print("(couldn't pre-mark it as trusted - your file manager may prompt "
                  "once on first double-click, that's expected)")

    try:
        subprocess.run(["update-desktop-database", str(APPLICATIONS_DIR)], check=False, capture_output=True)
    except OSError:
        pass

    print(f"Done - look for \"{APP_NAME}\" in your application launcher/search.")


def remove() -> None:
    removed = False
    for directory in (APPLICATIONS_DIR, DESKTOP_DIR):
        path = directory / DESKTOP_FILENAME
        if path.exists():
            path.unlink()
            print(f"removed {path}")
            removed = True
    if not removed:
        print("nothing installed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", default=sys.executable,
                        help="python interpreter to launch vibe_monitor_app.py with (default: this interpreter, %(default)s)")
    parser.add_argument("--dry-run", action="store_true", help="print the .desktop file instead of installing it")
    parser.add_argument("--remove", action="store_true", help="uninstall the launcher instead of installing it")
    args = parser.parse_args()

    if args.remove:
        remove()
        return 0

    install(args.python, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
