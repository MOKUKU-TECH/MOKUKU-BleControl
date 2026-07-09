#!/usr/bin/env python3
"""Installs (or removes) the vibe_monitor report_status.py hook in Codex
CLI's hooks.json - the Codex-side counterpart of install_hooks.py.

Merges into whatever's already there - existing hooks are left untouched,
and re-running is a no-op if already installed. Writes a .bak copy of the
file before making any change.

IMPORTANT: unlike Claude Code, Codex requires you to manually trust new
hooks before they actually run. After installing, open the Codex CLI and
run `/hooks` to review and approve these entries - they're inert until you
do (see https://developers.openai.com/codex/hooks). Codex may also need
`[features] hooks = true` set in its config.toml if hooks are disabled by
default on your version.

Usage:
    python3 install_codex_hooks.py                # writes to ~/.codex/hooks.json
    python3 install_codex_hooks.py --project      # writes to ./.codex/hooks.json instead
    python3 install_codex_hooks.py --dry-run      # preview the result, don't write anything
    python3 install_codex_hooks.py --remove       # remove previously-installed entries
"""
import argparse
import json
import sys
from pathlib import Path

from install_hooks import find_our_entry, write_settings as write_hooks

REPORT_SCRIPT = str((Path(__file__).resolve().parent / "vibe_monitor" / "report_status.py"))

# Codex CLI's own hook event set (codex-rs/hooks) - see report_status.py's
# CODEX_STATUS_BY_EVENT for what each one maps to. Unlike Claude Code's
# hooks, the event name is baked into each command line (--event <Name>)
# rather than trusted out of Codex's own JSON payload - see
# report_status.py's module docstring for why.
HOOK_EVENTS = (
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PermissionRequest", "SubagentStart", "SubagentStop", "PreCompact",
    "PostCompact", "Stop",
)


def command_for_event(python: str, event: str) -> str:
    return f"{python} {REPORT_SCRIPT} --agent codex --event {event}"


def hooks_path(project: bool) -> Path:
    base = Path.cwd() if project else Path.home()
    return base / ".codex" / "hooks.json"


def load_hooks(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def install(config: dict, python: str) -> int:
    hooks = config.setdefault("hooks", {})
    added = 0
    for event in HOOK_EVENTS:
        command = command_for_event(python, event)
        entries = hooks.setdefault(event, [])
        if find_our_entry(entries, command) is not None:
            continue
        entries.append({"hooks": [{"type": "command", "command": command}]})
        added += 1
    return added


def remove(config: dict, python: str) -> int:
    hooks = config.get("hooks", {})
    removed = 0
    for event in HOOK_EVENTS:
        if event not in hooks:
            continue
        command = command_for_event(python, event)
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
    parser.add_argument("--project", action="store_true", help="write to ./.codex/hooks.json instead of ~/.codex/hooks.json")
    parser.add_argument("--dry-run", action="store_true", help="preview the result instead of writing")
    parser.add_argument("--remove", action="store_true", help="remove previously-installed hook entries instead of adding")
    parser.add_argument("--python", default=sys.executable, help="python interpreter to invoke report_status.py with (default: this interpreter, %(default)s)")
    args = parser.parse_args()

    path = hooks_path(args.project)
    config = load_hooks(path)

    if args.remove:
        count = remove(config, args.python)
        print(f"removed {count} hook entr{'y' if count == 1 else 'ies'} ({path})")
    else:
        count = install(config, args.python)
        if count:
            print(f"added {count} hook entr{'y' if count == 1 else 'ies'} ({path})")
        else:
            print(f"already installed, nothing to do ({path})")

    if args.dry_run:
        print(json.dumps(config, indent=2))
        return 0

    if count == 0:
        return 0

    backup = write_hooks(path, config)
    if backup:
        print(f"backed up existing file to {backup}")
    print(f"wrote {path}")
    if not args.remove:
        print()
        print("IMPORTANT: Codex requires you to manually trust new hooks before")
        print("they run. Open the Codex CLI and run `/hooks` to review and")
        print("approve these entries - they're inert until you do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
