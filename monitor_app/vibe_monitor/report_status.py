#!/usr/bin/env python3
"""Claude Code hook entry point.

Reads a hook event's JSON payload from stdin and forwards a mapped status,
tagged with this session's id and project, to vibe_monitor_app.py (see
../vibe_monitor_app.py) over its Unix socket. The app is started and
connected to MOKUKU manually by the user - if it isn't running, sending is a
silent no-op (see ipc_client.py). Installed into settings.json by
../install_hooks.py (see doc/VIBE_CODING_MONITOR.md) - not imported as part
of the package, so it bootstraps its own sys.path to find ipc_client.py
whether it's run as a bare script or via `python -m`.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

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
    # There's no hook for "the user answered a question/permission prompt
    # and Claude resumed" - MessageDisplay (fires while assistant text
    # streams) is the only thing that happens during that gap, so it's what
    # clears a stale "Waiting" once Claude starts talking again.
    "MessageDisplay": "thinking",
}

# MessageDisplay fires continuously while text streams, and every firing
# re-spawns this whole script - without throttling that's a socket round
# trip (and whatever overhead that carries) on every chunk. A cheap local
# timestamp file bounds it to about once per _MESSAGE_DISPLAY_THROTTLE_SECONDS
# per session, which still clears "Waiting" within a few seconds of Claude
# resuming.
_MESSAGE_DISPLAY_THROTTLE_SECONDS = 2.5


def _message_display_throttled(session_id):
    path = Path(tempfile.gettempdir()) / f"mokuku-vibe-monitor-msgdisplay-{session_id}"
    now = time.time()
    try:
        if now - path.stat().st_mtime < _MESSAGE_DISPLAY_THROTTLE_SECONDS:
            return True
    except OSError:
        pass
    try:
        path.touch()
    except OSError:
        pass
    return False

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
    resolvable only right now, while the wrapper is still alive. The app
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

    if event.get("hook_event_name") == "MessageDisplay" and _message_display_throttled(session_id):
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
