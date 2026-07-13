#!/usr/bin/env python3
"""Installs (or removes) the vibe_monitor report_status.py hook in Claude
Code's settings.json.

Merges into whatever's already there - existing settings and unrelated
hooks (including hooks for other projects/devices) are left untouched.
Re-running is a no-op if already installed and up to date, but also repairs
drift on entries it previously installed (e.g. a stale matcher from before
this script's HOOK_EVENTS changed). Writes a .bak copy of the settings file
before making any change.

Usage:
    python3 install_hooks.py                # writes to ~/.claude/settings.json
    python3 install_hooks.py --project      # writes to ./.claude/settings.json instead
    python3 install_hooks.py --dry-run      # preview the result, don't write anything
    python3 install_hooks.py --remove       # remove previously-installed entries
"""
import argparse
import json
import sys
from pathlib import Path

REPORT_SCRIPT = str((Path(__file__).resolve().parent / "vibe_monitor" / "report_status.py"))


def _join(*parts):
    """Join command parts, quoting any that contain spaces (Windows install
    paths like 'C:\\Program Files\\...' otherwise break the hook command)."""
    return " ".join(f'"{p}"' if " " in p else p for p in parts)


def _frozen_hook_exe() -> str:
    """Sibling console (`mokuku-vibe-hook`) exe next to the GUI executable.
    Both are built from main.py (see packaging/vibe_monitor.spec) and share
    the bundle's _internal; the hook one is a console binary so its stdin -
    the JSON payload Claude Code pipes in - actually works. The GUI exe
    (sys.executable here) is a Windows GUI-subsystem binary, which has no
    stdin, so pointing the hook at it made every hook event a silent no-op."""
    exe = Path(sys.executable)
    name = "mokuku-vibe-hook" + (".exe" if exe.suffix.lower() == ".exe" else "")
    return str(exe.with_name(name))


def hook_command(python: str, *extra) -> str:
    """The command that runs report_status for one hook event. In a
    PyInstaller bundle it's the bundled console hook exe dispatching on
    `--hook-report` (see main.py) - no interpreter or script path, so the end
    user needs no Python. From source it's the given interpreter running
    report_status.py. `extra` carries the Codex installer's `--agent codex
    --event <name>` args (see install_codex_hooks); command parts with spaces
    are quoted."""
    if getattr(sys, "frozen", False):
        return _join(_frozen_hook_exe(), "--hook-report", *extra)
    return _join(python, REPORT_SCRIPT, *extra)


def report_command(python: str) -> str:
    return hook_command(python)

# event -> matcher (None if the event doesn't take one)
HOOK_EVENTS = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreToolUse": ".*",
    "PostToolUse": ".*",
    # Notification fires for several distinct sub-types, most commonly
    # "idle_prompt" - Claude finished responding and is just waiting for the
    # next prompt, which fires on every single turn with no user action
    # involved. Scoping to "permission_prompt" only keeps this to genuine
    # blocking waits (a tool/question needs your approval right now) -
    # without it, the display flips to "Waiting" after every response,
    # which reads as a bug ("I didn't do anything").
    "Notification": "permission_prompt",
    "Stop": None,
    "SubagentStop": ".*",
    "SessionEnd": None,
    "PreCompact": None,
    "MessageDisplay": None,
}


def settings_path(project: bool) -> Path:
    base = Path.cwd() if project else Path.home()
    return base / ".claude" / "settings.json"


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def find_our_entry(entries, command):
    return next((entry for entry in entries for h in entry.get("hooks", []) if h.get("command") == command), None)


def install(settings: dict, command: str) -> int:
    """Adds our hook entries, and re-syncs the matcher on ones already
    installed - e.g. this repo once installed Notification with no matcher,
    which let every idle_prompt notification (fired ~60s into every idle
    stretch, no user action involved) through as a false "Waiting" status;
    re-running install_hooks.py after that fix landed needs to actually
    correct that already-installed entry, not just no-op on it."""
    hooks = settings.setdefault("hooks", {})
    changed = 0
    for event, matcher in HOOK_EVENTS.items():
        entries = hooks.setdefault(event, [])
        entry = find_our_entry(entries, command)
        if entry is not None:
            if entry.get("matcher") != matcher:
                if matcher:
                    entry["matcher"] = matcher
                else:
                    entry.pop("matcher", None)
                changed += 1
            continue
        entry = {}
        if matcher:
            entry["matcher"] = matcher
        entry["hooks"] = [{"type": "command", "command": command}]
        entries.append(entry)
        changed += 1
    return changed


def remove(settings: dict, command: str) -> int:
    hooks = settings.get("hooks", {})
    removed = 0
    for event in list(hooks.keys()):
        kept_entries = []
        for entry in hooks[event]:
            before = entry.get("hooks", [])
            after = [h for h in before if h.get("command") != command]
            removed += len(before) - len(after)
            if after:
                kept_entries.append({**entry, "hooks": after})
        if kept_entries:
            hooks[event] = kept_entries
        else:
            del hooks[event]
    return removed


def write_settings(path: Path, settings: dict):
    """Backs up path (if it exists) then writes settings to it. Shared by
    the CLI below and vibe_monitor_app.py's "Install Claude Code Hooks"
    button so both follow the exact same backup/write behavior. Returns the
    backup Path, or None if there was nothing to back up."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_text(path.read_text())
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", action="store_true", help="write to ./.claude/settings.json instead of ~/.claude/settings.json")
    parser.add_argument("--dry-run", action="store_true", help="preview the result instead of writing")
    parser.add_argument("--remove", action="store_true", help="remove previously-installed hook entries instead of adding")
    parser.add_argument("--python", default=sys.executable, help="python interpreter to invoke report_status.py with (default: this interpreter, %(default)s)")
    args = parser.parse_args()

    path = settings_path(args.project)
    command = report_command(args.python)
    settings = load_settings(path)

    if args.remove:
        count = remove(settings, command)
        print(f"removed {count} hook entr{'y' if count == 1 else 'ies'} ({path})")
    else:
        count = install(settings, command)
        if count:
            print(f"added/updated {count} hook entr{'y' if count == 1 else 'ies'} ({path})")
        else:
            print(f"already installed and up to date, nothing to do ({path})")

    if args.dry_run:
        print(json.dumps(settings, indent=2))
        return 0

    if count == 0:
        return 0

    backup = write_settings(path, settings)
    if backup:
        print(f"backed up existing file to {backup}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
