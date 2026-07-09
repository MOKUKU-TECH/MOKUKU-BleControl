"""Pure protocol logic shared between the hook script and vibe_monitor_app.py:
BLE message encoding, detail truncation, and Claude Code session tracking.
No I/O of its own (no sockets, no BLE) - see vibe_monitor_app.py for that.
"""
import os
import struct
import time

CHARACTERISTIC_UUID_MAIN = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
CHARACTERISTIC_UUID_ACK = "d222e154-1a80-4e71-9a63-2aa2c0ce0a8c"
DEVICE_NAME_PREFIX = "mokuku"
STATUS_TEXT_MAX_BYTES = 63  # firmware's two 32-byte main/detail buffers (31 usable bytes each) + 1 newline separator
PROJECT_NAME_MAX_BYTES = 31  # firmware VIBECODING_PROJECT_BUFFER_SIZE (32) minus the null terminator

# vibe_monitor_app.py listens here; report_status.py connects here. A TCP
# loopback socket (not a Unix domain socket) so the exact same code runs on
# Windows, where AF_UNIX and os.getuid() don't exist. Bound to 127.0.0.1
# only, never a routable interface - this is strictly local IPC between the
# hook script and the app on the same machine. The app is started and
# stopped manually by the user, so there's no lock file / "ensure a daemon
# is running" dance needed around it.
IPC_HOST = "127.0.0.1"
IPC_PORT = 47615

# Panel arrays and commands for the one-time "Enable Vibe Coding Monitor
# Mode" setup, sent on the ACK characteristic (see encode_command_message).
VIBE_MODE_LEFT_PANELS = "11-5"     # PANEL_TYPE_VIBECODING + PANEL_TYPE_FUEL
VIBE_MODE_RIGHT_PANELS = "9-7-10"  # Time + Duration + Music
MSG_ID_LEFT_PANEL_ARRAY = 50
MSG_ID_RIGHT_PANEL_ARRAY = 51
COMMAND_DISABLE_BLE_SCAN = 35      # DisableBleScan(): stop OBD/canbus scanning, fall back to GPS mode

# WiFi credentials + firmware URL for HTTP OTA, sent as string messages on the
# ACK characteristic (the device downloads the firmware over this network).
MSG_ID_WIFI_NAME = 7
MSG_ID_WIFI_PASSWORD = 8
MSG_ID_OTA_HTTP_URL = 9

# OTA triggers, sent as command bytes (encode_command_message). The right eye
# must update before the left: the left/INS eye owns the BLE link, so updating
# it first can interrupt the right eye's still-running update - hence the delay
# between the two.
COMMAND_OTA_RIGHT_EYE = 67  # forwarded over inter-eye UART to the right eye
COMMAND_OTA_LEFT_EYE = 66   # runs on the local left/INS/BLE eye
OTA_EYE_ORDER_DELAY_SECONDS = 0.5

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
    purely to carry the current time into SystemStateSetRealTime() on every
    refresh tick, independent of whether the status text changed.
    VEL=255 and GAS=0 are this firmware's existing "no data" sentinels
    (data_valid_ = current_vel_ < 255; gas_valid() = gas_ > 0), so this
    doesn't make the speed/fuel panels believe they have real vehicle data;
    backlight=0 and command=0 are no-ops on the firmware side.

    The timestamp field is local seconds-since-midnight, not a raw Unix
    epoch: SystemStateGetTime() (state_manager.c) derives the displayed
    clock as (this value) % 86400, with no timezone conversion of its own -
    a raw UTC epoch's mod-86400 is UTC time-of-day, which is wrong by a
    fixed offset for anyone not in UTC+0. messager.py's get_current_time_ms()
    (the reference app's own equivalent of this function) already sends
    local seconds-since-midnight for the same reason - mirrored here.
    """
    vel, rpm_a, rpm_b, gas = 255, 0, 0, 0
    now = time.localtime()
    timestamp = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
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


def encode_status_message(state, project, text):
    project_bytes = (project or "").encode("utf-8")[:PROJECT_NAME_MAX_BYTES]
    text_bytes = _truncate_detail(text, STATUS_TEXT_MAX_BYTES)
    return bytes([52, state, len(project_bytes)]) + project_bytes + bytes([len(text_bytes)]) + text_bytes


def encode_string_message(msg_id, text):
    """A length-prefixed ASCII message on the ACK characteristic - the wire
    format the reference app's messager.push_string_message() uses for the
    panel-array commands (50/51)."""
    payload = text.encode("utf-8")
    return bytes([msg_id, len(payload)]) + payload


def encode_command_message(command):
    """ACK message id 1 carrying a single command byte - matches
    messager.push_command() (e.g. command 35 = DisableBleScan)."""
    return bytes([1, command])


def encode_reboot_message():
    """ACK message id 6 triggers esp_restart() on the device - matches
    messager.push_reboot()."""
    return bytes([6])


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
    elif status == "thinking":
        return STATE_WORKING, "Thinking"
    return STATE_IDLE, "Idle"


class SessionTracker:
    """Tracks every active coding-assistant session reported over the socket
    by report_status.py (Claude Code and/or Codex CLI - see its --agent
    flag), and picks which one's status to show/send. Multiple sessions can
    be active at once (e.g. several Claude Code/Codex windows) - by default
    the most-recently-active one is shown/sent, but select_session() lets
    the user pin a specific one instead."""

    def __init__(self):
        self.sessions = {}   # session_id -> {agent, project, status, tool, detail, last_seen, pid}
        self.selected_session_id = None  # None = automatic (most recently active)

    def update_session(self, session_id, project, status, tool, detail, pid=None, agent="claude"):
        existing = self.sessions.get(session_id)
        if existing and existing.get("project"):
            project = existing["project"]
        self.sessions[session_id] = {
            "agent": agent,
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

    def select_session(self, session_id):
        """session_id=None reverts to automatic (most recently active)."""
        self.selected_session_id = session_id

    def is_auto_selected(self):
        """True if there's no valid pinned session, i.e. current_status()
        is falling back to "most recently active" rather than a user pick."""
        return not (self.selected_session_id and self.selected_session_id in self.sessions)

    def effective_session_id(self):
        """The session_id current_status() is actually using, or None if
        there are no sessions at all."""
        if self.selected_session_id and self.selected_session_id in self.sessions:
            return self.selected_session_id
        if not self.sessions:
            return None
        return max(self.sessions.items(), key=lambda kv: kv[1]["last_seen"])[0]

    def current_status(self):
        """Returns (state, project, text)."""
        session_id = self.effective_session_id()
        if session_id is None:
            return STATE_IDLE, "", "Idle"
        session = self.sessions[session_id]
        state, text = format_status(session)
        return state, session["project"], text
