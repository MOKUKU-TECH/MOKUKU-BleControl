#!/usr/bin/env python3
"""Installs (or removes) the vibe_monitor report_status.py hook in Claude
Code's settings.json.

Merges into whatever's already there - existing settings and unrelated
hooks (including hooks for other projects/devices) are left untouched, and
re-running is a no-op if already installed. Writes a .bak copy of the
settings file before making any change.

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

# event -> matcher (None if the event doesn't take one)
HOOK_EVENTS = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "PreToolUse": ".*",
    "PostToolUse": ".*",
    "Notification": None,
    "Stop": None,
    "SubagentStop": ".*",
    "SessionEnd": None,
    "PreCompact": None,
}


def settings_path(project: bool) -> Path:
    base = Path.cwd() if project else Path.home()
    return base / ".claude" / "settings.json"


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def has_our_hook(entries, command):
    return any(h.get("command") == command for entry in entries for h in entry.get("hooks", []))


def install(settings: dict, command: str) -> int:
    hooks = settings.setdefault("hooks", {})
    added = 0
    for event, matcher in HOOK_EVENTS.items():
        entries = hooks.setdefault(event, [])
        if has_our_hook(entries, command):
            continue
        entry = {}
        if matcher:
            entry["matcher"] = matcher
        entry["hooks"] = [{"type": "command", "command": command}]
        entries.append(entry)
        added += 1
    return added


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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", action="store_true", help="write to ./.claude/settings.json instead of ~/.claude/settings.json")
    parser.add_argument("--dry-run", action="store_true", help="preview the result instead of writing")
    parser.add_argument("--remove", action="store_true", help="remove previously-installed hook entries instead of adding")
    parser.add_argument("--python", default=sys.executable, help="python interpreter to invoke report_status.py with (default: this interpreter, %(default)s)")
    args = parser.parse_args()

    path = settings_path(args.project)
    command = f"{args.python} {REPORT_SCRIPT}"
    settings = load_settings(path)

    if args.remove:
        count = remove(settings, command)
        print(f"removed {count} hook entr{'y' if count == 1 else 'ies'} ({path})")
    else:
        count = install(settings, command)
        if count:
            print(f"added {count} hook entr{'y' if count == 1 else 'ies'} ({path})")
        else:
            print(f"already installed, nothing to do ({path})")

    if args.dry_run:
        print(json.dumps(settings, indent=2))
        return 0

    if count == 0:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_text(path.read_text())
        print(f"backed up existing file to {backup}")

    with open(path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
