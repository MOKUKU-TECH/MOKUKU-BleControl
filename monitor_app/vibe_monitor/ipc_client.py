"""Sends one hook-derived event (or a control command) to the persistent
daemon (daemon.py) over its Unix socket, lazily starting the daemon first
if it isn't already running.
"""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import daemon as daemon_mod  # noqa: E402

# The socket file can exist (created by bind()) a moment before the daemon
# actually reaches listen()/accept() - ensure_running() only waits for the
# file to appear, so a freshly-spawned daemon can still refuse the very
# first connection. A few quick retries absorb that race without needing a
# real client-side connection pool.
_CONNECT_RETRIES = 5
_CONNECT_RETRY_DELAY = 0.2


def _send_message(message, timeout=2.0, expect_reply=False):
    daemon_mod.ensure_running()
    line = json.dumps(message) + "\n"
    for attempt in range(_CONNECT_RETRIES):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(daemon_mod.SOCK_PATH))
                sock.sendall(line.encode())
                if expect_reply:
                    data = sock.makefile().readline()
                    return json.loads(data) if data else None
            return True
        except (OSError, json.JSONDecodeError):
            if attempt < _CONNECT_RETRIES - 1:
                time.sleep(_CONNECT_RETRY_DELAY)
    return None if expect_reply else False


def send(session_id, project=None, status=None, tool=None, detail=None, ended=False, pid=None):
    """Returns True if the message was delivered to the daemon."""
    if os.environ.get("MOKUKU_VIBE_MONITOR_DRY_RUN"):
        print(f"[dry-run] would send: session={session_id} project={project} status={status} "
              f"tool={tool} detail={detail} ended={ended} pid={pid}")
        return True

    message = {"session_id": session_id, "ended": ended}
    if not ended:
        message.update({"project": project, "status": status, "tool": tool, "detail": detail, "pid": pid})
    return bool(_send_message(message))


def query_status(timeout=2.0):
    """Returns the daemon's {sessions, devices, current_text} summary dict, or None."""
    return _send_message({"cmd": "status"}, timeout=timeout, expect_reply=True)
