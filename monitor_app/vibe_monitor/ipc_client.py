"""Sends one hook-derived event (or a control command) to vibe_monitor_app.py
over its Unix socket. The app is started and stopped manually by the user
(see doc/VIBE_CODING_MONITOR.md) - if it isn't running, sending is a silent
no-op, same as if the message vanished into a closed window. There's no
lazy auto-launch: the whole point of moving to a visible app is that the
user can always see whether the BLE connection is up, rather than a hook
silently spawning a background process with no feedback.
"""
import json
import os
import socket
import sys

try:
    from .protocol import IPC_HOST, IPC_PORT
except ImportError:  # run as a bare script (source hook install), not as a package
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from protocol import IPC_HOST, IPC_PORT  # noqa: E402

_CONNECT_TIMEOUT = 1.0


def _send_message(message, timeout=_CONNECT_TIMEOUT, expect_reply=False):
    line = json.dumps(message) + "\n"
    try:
        with socket.create_connection((IPC_HOST, IPC_PORT), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(line.encode())
            if expect_reply:
                data = sock.makefile().readline()
                return json.loads(data) if data else None
        return True
    except (OSError, json.JSONDecodeError):
        return None if expect_reply else False


def send(session_id, project=None, status=None, tool=None, detail=None, ended=False, pid=None, agent="claude"):
    """Returns True if the message was delivered to the app. `agent`
    identifies which coding assistant this session belongs to (e.g. "claude",
    "codex") - report_status.py is shared by both, tagged via its --agent flag."""
    if os.environ.get("MOKUKU_VIBE_MONITOR_DRY_RUN"):
        print(f"[dry-run] would send: session={session_id} agent={agent} project={project} status={status} "
              f"tool={tool} detail={detail} ended={ended} pid={pid}")
        return True

    message = {"session_id": session_id, "ended": ended}
    if not ended:
        message.update({"project": project, "status": status, "tool": tool, "detail": detail, "pid": pid,
                        "agent": agent})
    return bool(_send_message(message))


def query_status(timeout=2.0):
    """Returns the app's {sessions, devices, current_state, current_project, current_text} summary dict, or None."""
    return _send_message({"cmd": "status"}, timeout=timeout, expect_reply=True)
