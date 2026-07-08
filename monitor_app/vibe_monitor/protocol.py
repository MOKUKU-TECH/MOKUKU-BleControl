"""Pure protocol logic shared between the hook script and vibe_monitor_app.py:
BLE message encoding, detail truncation, and Claude Code session tracking.
No I/O of its own (no sockets, no BLE) - see vibe_monitor_app.py for that.
"""
import os
import struct
import tempfile
import time
from pathlib import Path

CHARACTERISTIC_UUID_MAIN = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
CHARACTERISTIC_UUID_ACK = "d222e154-1a80-4e71-9a63-2aa2c0ce0a8c"
DEVICE_NAME_PREFIX = "mokuku"
STATUS_TEXT_MAX_BYTES = 31  # firmware STATUS_TEXT_BUFFER_SIZE (32) minus the null terminator

# vibe_monitor_app.py listens here; report_status.py connects here. A plain
# well-known path (no lock file/pidfile) - the app is started and stopped
# manually by the user, not lazily spawned, so there's no "ensure a daemon is
# running" dance needed here anymore.
SOCK_PATH = Path(tempfile.gettempdir()) / f"mokuku-vibe-monitor-{os.getuid()}.sock"

SESSION_STALE_SECONDS = 30 * 60        # sessions with no liveness pid only
SESSION_ABS_STALE_SECONDS = 24 * 3600  # backstop even with a live pid (pid-reuse paranoia)

# Matches VIBECODING_STATE in IDF_SHARED/panel/panel_vibecoding.c - drives the
# panel's background color/blink on the device.
STATE_IDLE, STATE_WORKING, STATE_WAITING = 0, 1, 2
STATE_NAMES = {STATE_IDLE: "idle", STATE_WORKING: "working", STATE_WAITING: "waiting"}

# Tools whose detail is a file path, where the filename (the tail) is the
# identifying part and the shared leading directories aren't. Everything
# else (e.g. Bash, where detail is a shell command) keeps the front instead
# - the command name at the start is usually more informative than trailing
# arguments.
TAIL_TRUNCATE_TOOLS = {"Read", "Edit"}


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def encode_time_sync_message():
    """The 11-byte Transfer Data packet (id=1) that MyHostCallbacks::onMessageData
    (ble_messager.cc) reads as VEL/RPM/GAS/timestamp/backlight/command - sent
    purely to carry a real Unix timestamp into SystemStateSetRealTime() on
    every refresh tick, independent of whether the status text changed.
    VEL=255 and GAS=0 are this firmware's existing "no data" sentinels
    (data_valid_ = current_vel_ < 255; gas_valid() = gas_ > 0), so this
    doesn't make the speed/fuel panels believe they have real vehicle data;
    backlight=0 and command=0 are no-ops on the firmware side.
    """
    vel, rpm_a, rpm_b, gas = 255, 0, 0, 0
    timestamp = int(time.time())
    backlight, command = 0, 0
    return bytes([1, vel, rpm_a, rpm_b, gas]) + struct.pack("<I", timestamp) + bytes([backlight, command])


def _keep_tail(raw_bytes, budget):
    """Keeps the last `budget` bytes of `raw_bytes`, trimmed to start right
    after a '/' when the kept portion contains one - a clean path-segment
    boundary instead of a mid-word fragment. E.g.
    ".../IDF_SHARED/panel/panel_vibecoding.c" keeps
    "/panel/panel_vibecoding.c"."""
    if budget <= 0:
        return b""
    tail = raw_bytes[-budget:]
    slash_idx = tail.find(b"/")
    if 0 < slash_idx < len(tail) - 1:
        tail = tail[slash_idx:]
    return tail


def _keep_front_with_ellipsis(raw_bytes, budget):
    """Keeps the first `budget` bytes of `raw_bytes`, appending "..." so a
    cut-off command doesn't look like the whole message."""
    ellipsis = b"..."
    if budget <= len(ellipsis):
        return raw_bytes[:budget]
    return raw_bytes[:budget - len(ellipsis)] + ellipsis


def _truncate_detail(text, max_bytes):
    """Truncates `text` to fit max_bytes once UTF-8 encoded. If `text` is
    "main\ndetail" shaped (see format_status), only the detail half is cut -
    the short main status word always survives intact - keeping the tail for
    TAIL_TRUNCATE_TOOLS (file paths) and the front+"..." for everything else
    (e.g. shell commands)."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return raw

    if "\n" in text:
        main, _, detail = text.partition("\n")
        main_bytes = main.encode("utf-8") + b"\n"
        budget = max_bytes - len(main_bytes)
        if budget > 0:
            detail_bytes = detail.encode("utf-8")
            if main in TAIL_TRUNCATE_TOOLS:
                return main_bytes + _keep_tail(detail_bytes, budget)
            return main_bytes + _keep_front_with_ellipsis(detail_bytes, budget)
        # no room left even for main + newline - fall through to flat truncation

    return _keep_front_with_ellipsis(raw, max_bytes)


def encode_status_message(state, text):
    payload = _truncate_detail(text, STATUS_TEXT_MAX_BYTES)
    return bytes([52, state, len(payload)]) + payload


def format_status(info):
    """Returns (state, text)."""
    status = info.get("status")
    if status == "working":
        tool = (info.get("tool") or "").strip()
        detail = (info.get("detail") or "").strip()
        if tool and detail:
            text = f"{tool}\n{detail}"
        elif tool:
            text = tool
        else:
            text = "Working"
        return STATE_WORKING, text
    elif status == "waiting":
        return STATE_WAITING, "Waiting"
    return STATE_IDLE, "Idle"


class SessionTracker:
    """Tracks every active Claude Code session reported over the socket by
    report_status.py, and picks which one's status to show/send."""

    def __init__(self):
        self.sessions = {}   # session_id -> {project, status, tool, detail, last_seen, pid}

    def update_session(self, session_id, project, status, tool, detail, pid=None):
        existing = self.sessions.get(session_id)
        if existing and existing.get("project"):
            project = existing["project"]
        self.sessions[session_id] = {
            "project": project or session_id[:8],
            "status": status,
            "tool": tool or "",
            "detail": detail or "",
            "last_seen": time.time(),
            "pid": pid or (existing or {}).get("pid"),
        }

    def end_session(self, session_id):
        self.sessions.pop(session_id, None)

    def prune_stale_sessions(self):
        # Heartbeat: hooks only fire on discrete events, so a single long
        # tool call or background wait can be silent well past any
        # reasonable message-staleness window. When we know the session's
        # Claude process pid, liveness of that process - not message
        # recency - decides whether the session is still real.
        now = time.time()
        dead = []
        for sid, s in self.sessions.items():
            age = now - s["last_seen"]
            pid = s.get("pid")
            if pid:
                if not _pid_alive(pid) or age > SESSION_ABS_STALE_SECONDS:
                    dead.append(sid)
            elif age > SESSION_STALE_SECONDS:
                dead.append(sid)
        for sid in dead:
            del self.sessions[sid]

    def current_status(self):
        """Returns (state, text)."""
        if not self.sessions:
            return STATE_IDLE, "Idle"
        most_recent = max(self.sessions.values(), key=lambda s: s["last_seen"])
        return format_status(most_recent)
