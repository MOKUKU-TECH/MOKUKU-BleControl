#!/usr/bin/env python3
"""Claude Code hook entry point.

Reads a hook event's JSON payload from stdin and forwards a mapped status,
tagged with this session's id and project, to the persistent daemon (see
daemon.py) over its Unix socket. Installed into settings.json by
../install_hooks.py (see doc/VIBE_CODING_MONITOR.md) - not imported as part
of the package, so it bootstraps its own sys.path to find ipc_client.py
whether it's run as a bare script or via `python -m`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ipc_client  # noqa: E402

STATUS_BY_EVENT = {
    "SessionStart": "idle",
    "Stop": "idle",
    "SessionEnd": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "SubagentStop": "working",
    "PreCompact": "working",
    "Notification": "waiting",
}

DETAIL_KEYS = ("file_path", "command", "pattern", "description", "url")


def extract_detail(tool_input):
    if not isinstance(tool_input, dict):
        return ""
    for key in DETAIL_KEYS:
        value = tool_input.get(key)
        if value:
            return str(value)[:80]
    return ""


def project_name(event):
    # cwd tracks the session's persistent shell (a `cd` into a subdirectory
    # changes it mid-session); CLAUDE_PROJECT_DIR is the stable project root
    # Claude Code sets in every hook's environment.
    root = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ""
    return os.path.basename(root.rstrip("/")) if root else ""


def claude_pid():
    """The long-lived Claude Code process this hook belongs to. Hooks are
    spawned via a short-lived `sh -c` wrapper, so it's our grandparent -
    resolvable only right now, while the wrapper is still alive. The daemon
    heartbeat-checks this pid so a session survives arbitrarily long silent
    stretches (one huge tool call, a long background wait) instead of being
    pruned as stale."""
    try:
        with open(f"/proc/{os.getppid()}/stat") as f:
            gppid = int(f.read().split(")")[-1].split()[1])
        return gppid if gppid > 1 else None
    except (OSError, ValueError, IndexError):
        return None


def map_event(event):
    """Returns (status, tool, detail) or None if this event has no mapping."""
    status = STATUS_BY_EVENT.get(event.get("hook_event_name"))
    if status is None:
        return None
    tool = event.get("tool_name") or ""
    detail = extract_detail(event.get("tool_input"))
    return status, tool, detail


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0  # never fail the hook over a malformed/empty payload

    session_id = event.get("session_id")
    if not session_id:
        return 0

    if event.get("hook_event_name") == "SessionEnd":
        ipc_client.send(session_id, ended=True)
        return 0

    mapped = map_event(event)
    if mapped is None:
        return 0

    status, tool, detail = mapped
    ipc_client.send(session_id, project=project_name(event), status=status, tool=tool, detail=detail,
                    pid=claude_pid())
    return 0


if __name__ == "__main__":
    sys.exit(main())
