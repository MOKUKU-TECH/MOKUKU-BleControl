#!/usr/bin/env python3
"""Claude Code / Codex CLI hook entry point.

Reads a hook event's JSON payload from stdin and forwards a mapped status,
tagged with this session's id and project, to vibe_monitor_app.py (see
../vibe_monitor_app.py) over its Unix socket. The app is started and
connected to MOKUKU manually by the user - if it isn't running, sending is a
silent no-op (see ipc_client.py). Installed into Claude Code's settings.json
by ../install_hooks.py, or Codex's hooks.json by ../install_codex_hooks.py
(see doc/VIBE_CODING_MONITOR.md) - not imported as part of the package, so
it bootstraps its own sys.path to find ipc_client.py whether it's run as a
bare script or via `python -m`.

Both agents deliver hook JSON via stdin with near-identical common fields
(session_id, cwd, tool_name, tool_input) - Codex's own hook set is a close
port of Claude Code's. The one meaningful gap: Codex's `PermissionRequest`
payload isn't confirmed to self-report which event it is the way Claude's
`hook_event_name` field does, so rather than trust the payload for that,
Codex invocations are installed with an explicit `--agent codex --event
<Name>` on the command line (install_codex_hooks.py) - the event name comes
from argv, not the JSON body, for that agent.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

try:
    from . import ipc_client
except ImportError:  # run as a bare script (source hook install), not as a package
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

# Codex CLI's own hook event set (codex-rs/hooks) - no SessionEnd (session
# cleanup instead relies on prune_stale_sessions()'s pid-liveness check) and
# no MessageDisplay-equivalent, but PermissionRequest fills the same
# "blocking wait on you" role Claude's Notification(permission_prompt) does.
CODEX_STATUS_BY_EVENT = {
    "SessionStart": "idle",
    "Stop": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "SubagentStart": "working",
    "SubagentStop": "working",
    "PreCompact": "working",
    "PostCompact": "working",
    "PermissionRequest": "waiting",
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
    # Claude Code sets in every hook's environment (Codex has no equivalent
    # env var, so its sessions always fall back to cwd - which its own hook
    # payloads do include).
    root = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ""
    return os.path.basename(root.rstrip("/")) if root else ""


def agent_pid():
    """The long-lived Claude Code/Codex process this hook belongs to. Hooks
    are spawned via a short-lived `sh -c` wrapper, so it's our grandparent -
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


def parse_cli_args(argv):
    """Minimal manual parsing (no argparse - keeps this a tiny,
    dependency-free hook script). Claude Code invocations pass no arguments
    at all and behave exactly as before. Codex invocations are installed
    (see install_codex_hooks.py) with an explicit `--agent codex --event
    <HookEventName>` so the event name comes from argv rather than being
    trusted out of Codex's own JSON payload - see the module docstring."""
    agent = "claude"
    event_override = None
    it = iter(argv)
    for arg in it:
        if arg == "--agent":
            agent = next(it, "claude")
        elif arg == "--event":
            event_override = next(it, None)
    return agent, event_override


def map_event(event, agent, event_name):
    """Returns (status, tool, detail) or None if this event has no mapping."""
    table = CODEX_STATUS_BY_EVENT if agent == "codex" else STATUS_BY_EVENT
    status = table.get(event_name)
    if status is None:
        return None
    tool = event.get("tool_name") or ""
    detail = extract_detail(event.get("tool_input"))
    return status, tool, detail


def main(argv=None):
    agent, event_override = parse_cli_args(sys.argv[1:] if argv is None else argv)

    raw = sys.stdin.read() if sys.stdin else ""  # windowed exe may have no stdin attached
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0  # never fail the hook over a malformed/empty payload

    session_id = event.get("session_id")
    if not session_id:
        return 0

    event_name = event_override or event.get("hook_event_name")

    if agent == "claude" and event_name == "SessionEnd":
        ipc_client.send(session_id, ended=True)
        return 0

    if agent == "claude" and event_name == "MessageDisplay" and _message_display_throttled(session_id):
        return 0

    mapped = map_event(event, agent, event_name)
    if mapped is None:
        return 0

    status, tool, detail = mapped
    ipc_client.send(session_id, project=project_name(event), status=status, tool=tool, detail=detail,
                    pid=agent_pid(), agent=agent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
