"""Persistent daemon that reflects Claude Code's status onto a MOKUKU device.

Tracks every active Claude Code session (reported over a Unix socket by
report_status.py) and maintains a BLE connection to the single CLOSEST
discoverable MOKUKU device (name prefix "mokuku", picked by RSSI - multiple
units may be around, e.g. someone else's), pushing the most-recently-active
session's status as a short text string via BLE message id 52, which sets the
text on the dedicated VibeCoding panel (see
IDF_SHARED/panel/panel_vibecoding.c:SetVibeCodingStatusText and
doc/BLE_CONTROL.md). Unlike a paired/bonded peripheral, MOKUKU is a plain
unauthenticated BLE server, so devices are found via an active scan
rather than the OS's paired-devices list - no pairing step is needed.

Lazily started by the first hook event (see ensure_running()) and exits on
its own after a long idle stretch.
"""
import asyncio
import fcntl
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

CHARACTERISTIC_UUID_MAIN = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
CHARACTERISTIC_UUID_ACK = "d222e154-1a80-4e71-9a63-2aa2c0ce0a8c"
DEVICE_NAME_PREFIX = "mokuku"
STATUS_TEXT_MAX_BYTES = 31  # firmware STATUS_TEXT_BUFFER_SIZE (32) minus the null terminator

SOCK_PATH = Path(tempfile.gettempdir()) / f"mokuku-vibe-monitor-{os.getuid()}.sock"
PID_PATH = Path.home() / ".cache" / "mokuku-vibe-monitor-daemon.pid"

SESSION_STALE_SECONDS = 30 * 60        # sessions with no liveness pid only
SESSION_ABS_STALE_SECONDS = 24 * 3600  # backstop even with a live pid (pid-reuse paranoia)
TOTAL_IDLE_EXIT_SECONDS = 60 * 60
REFRESH_INTERVAL_SECONDS = 2
RECONNECT_INTERVAL_SECONDS = 8
SCAN_TIMEOUT_SECONDS = 4.0


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def encode_time_sync_message():
    """The 11-byte Transfer Data packet (id=1) that MyHostCallbacks::onMessageData
    (ble_messager.cc) reads as VEL/RPM/GAS/timestamp/backlight/command - sent
    here purely to carry a real Unix timestamp into SystemStateSetRealTime()
    on every daemon refresh tick, independent of whether the status text
    changed. VEL=255 and GAS=0 are this firmware's existing "no data"
    sentinels (data_valid_ = current_vel_ < 255; gas_valid() = gas_ > 0), so
    this doesn't make the speed/fuel panels believe they have real vehicle
    data; backlight=0 and command=0 are no-ops on the firmware side.
    """
    vel, rpm_a, rpm_b, gas = 255, 0, 0, 0
    timestamp = int(time.time())
    backlight, command = 0, 0
    return bytes([1, vel, rpm_a, rpm_b, gas]) + struct.pack("<I", timestamp) + bytes([backlight, command])


def _truncate_with_ellipsis(text, max_bytes):
    """Truncates `text` to fit max_bytes once UTF-8 encoded, appending "..."
    so a cut-off file path/command doesn't look like the whole message (a
    firmware log of a truncated message with no marker looked exactly like
    a shorter, complete one). If `text` is "main\ndetail" shaped (see
    format_status), only the detail half is cut - the short main status
    word always survives intact."""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return raw

    ellipsis = b"..."
    if "\n" in text:
        main, _, detail = text.partition("\n")
        main_bytes = main.encode("utf-8") + b"\n"
        budget = max_bytes - len(main_bytes)
        if budget > len(ellipsis):
            return main_bytes + detail.encode("utf-8")[:budget - len(ellipsis)] + ellipsis
        # no room left for main + ellipsis - fall through to flat truncation

    return raw[:max_bytes - len(ellipsis)] + ellipsis


# Matches VIBECODING_STATE in IDF_SHARED/panel/panel_vibecoding.c - drives the
# panel's background color/blink on the device.
STATE_IDLE, STATE_WORKING, STATE_WAITING = 0, 1, 2


def encode_status_message(state, text):
    payload = _truncate_with_ellipsis(text, STATUS_TEXT_MAX_BYTES)
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


class Daemon:
    def __init__(self):
        self.sessions = {}   # session_id -> {project, status, tool, detail, last_seen, pid}
        self.devices = {}    # address -> {"client": BleakClient}
        self.last_activity = time.time()

    def touch(self):
        self.last_activity = time.time()

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
        self.touch()

    def end_session(self, session_id):
        self.sessions.pop(session_id, None)
        self.touch()

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

    def is_idle(self):
        return not self.sessions and not self.devices


async def handle_client(daemon, reader, writer):
    try:
        line = await reader.readline()
        if not line:
            return
        msg = json.loads(line.decode().strip())
        cmd = msg.get("cmd")

        if cmd == "status":
            current_state, current_text = daemon.current_status()
            summary = {
                "sessions": [
                    {"id": sid, "project": s["project"], "status": s["status"]}
                    for sid, s in daemon.sessions.items()
                ],
                "devices": [
                    {"address": addr, "connected": entry.get("client") is not None and entry["client"].is_connected}
                    for addr, entry in daemon.devices.items()
                ],
                "current_state": current_state,
                "current_text": current_text,
            }
            writer.write((json.dumps(summary) + "\n").encode())
            await writer.drain()
            return

        session_id = msg.get("session_id")
        if not session_id:
            return
        if msg.get("ended"):
            daemon.end_session(session_id)
        else:
            daemon.update_session(session_id, msg.get("project"), msg.get("status"), msg.get("tool"),
                                  msg.get("detail"), pid=msg.get("pid"))
    except (json.JSONDecodeError, OSError):
        pass
    finally:
        writer.close()


async def run_server(daemon):
    async def handler(reader, writer):
        await handle_client(daemon, reader, writer)

    SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()
    server = await asyncio.start_unix_server(handler, path=str(SOCK_PATH))
    async with server:
        await server.serve_forever()


async def discover_mokuku_devices(timeout=SCAN_TIMEOUT_SECONDS):
    """Returns [(address, rssi), ...] for every discovered mokuku* device."""
    scanner = BleakScanner()
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return [(d.address, d.rssi) for d in scanner.discovered_devices
            if d.name and d.name.startswith(DEVICE_NAME_PREFIX)]


async def _bluetoothctl_connect(address, timeout=15.0):
    """bleak's own BlueZ D-Bus connect() has a known-flaky interaction on
    Linux (github.com/hbldh/bleak#1364 and others: connects then silently
    drops, times out client-side while the connection actually succeeds
    moments later at the BlueZ level, or the whole D-Bus call just hangs
    without honoring asyncio's timeout/cancellation) - `bluetoothctl
    connect` against the same bluetoothd doesn't have this problem, so it
    does the actual radio connection; bleak is only used afterwards for
    GATT reads/writes on the now-established link. A hung `client.connect()`
    previously wedged this daemon's whole event loop (including the Unix
    socket server), making it unresponsive."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "connect", address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0 and b"Connection successful" in stdout
    except (asyncio.TimeoutError, OSError):
        return False


async def manage_device(daemon, address):
    if address in daemon.devices:
        return
    entry = {"client": None}
    daemon.devices[address] = entry
    success = False
    try:
        if not await _bluetoothctl_connect(address):
            return

        client = BleakClient(address, disconnected_callback=lambda _c: daemon.devices.pop(address, None))
        try:
            await asyncio.wait_for(client.connect(timeout=20), timeout=25.0)
        except Exception:
            # As above: bleak's client-side connect() can time out while
            # BlueZ's underlying connection actually completed moments
            # later - don't discard it just because our wait gave up first.
            if not client.is_connected:
                return

        entry["client"] = client
        daemon.touch()
        success = True
    finally:
        if not success:
            daemon.devices.pop(address, None)


async def _drop_device(daemon, address):
    entry = daemon.devices.pop(address, None)
    client = entry.get("client") if entry else None
    if client:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=5.0)
        except Exception:
            pass


async def reconnect_loop(daemon):
    while True:
        # Only scan while not already connected to something - an active BLE
        # scan and a live GATT connection compete for the same radio, and
        # scanning on every cycle (previously: unconditionally, every 8s,
        # forever) was adding real latency/jitter to refresh_loop's status
        # writes on the already-open connection. This means we no longer
        # auto-switch to a closer unit that appears mid-connection (rare;
        # multiple-MOKUKU-nearby is an edge case), only reconnect once
        # disconnected.
        if not daemon.devices:
            discovered = await discover_mokuku_devices()
            if discovered:
                closest_address, _ = max(discovered, key=lambda item: item[1])
                asyncio.create_task(manage_device(daemon, closest_address))
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)


async def refresh_loop(daemon):
    last_sent = {}
    while True:
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        daemon.prune_stale_sessions()
        state, text = daemon.current_status()
        status_message = encode_status_message(state, text)

        for address, entry in list(daemon.devices.items()):
            client = entry.get("client")
            if not client or not client.is_connected:
                continue

            # Time sync every tick, independent of whether the status text
            # changed, so the clock stays fresh even during long idle
            # stretches - not just at the moment something changes.
            try:
                await asyncio.wait_for(
                    client.write_gatt_char(CHARACTERISTIC_UUID_MAIN, encode_time_sync_message()), timeout=10.0)
                daemon.touch()
            except Exception:
                last_sent.pop(address, None)
                await _drop_device(daemon, address)
                continue

            if last_sent.get(address) == (state, text):
                continue
            try:
                await asyncio.wait_for(client.write_gatt_char(CHARACTERISTIC_UUID_ACK, status_message), timeout=10.0)
                last_sent[address] = (state, text)
                daemon.touch()
            except Exception:
                last_sent.pop(address, None)
                await _drop_device(daemon, address)

        if daemon.is_idle() and time.time() - daemon.last_activity > TOTAL_IDLE_EXIT_SECONDS:
            os._exit(0)


async def main_async():
    daemon = Daemon()
    await asyncio.gather(run_server(daemon), reconnect_loop(daemon), refresh_loop(daemon))


# Kept open (and thus locked) for the daemon process's whole lifetime.
# Module-level so it isn't garbage-collected (which would close the fd and
# silently drop the lock).
_lock_handle = None


def _try_lock_pid_file():
    """Returns an open file handle holding an exclusive flock, or None if
    another process already holds it. flock is process-death-safe - the OS
    releases it automatically if the holder crashes, so there's no stale-
    lock case to clean up, unlike a plain PID file."""
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(PID_PATH, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def run():
    global _lock_handle
    f = _try_lock_pid_file()
    if f is None:
        return  # another instance won the race to become the daemon
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    _lock_handle = f
    try:
        asyncio.run(main_async())
    finally:
        _lock_handle = None
        f.close()  # releases the flock
        PID_PATH.unlink(missing_ok=True)
        SOCK_PATH.unlink(missing_ok=True)


def _read_pid():
    try:
        return int(PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return None


def is_running():
    """Whether a daemon currently holds the singleton lock - this is the
    source of truth (not PID liveness, which is racy if a PID gets reused)."""
    f = _try_lock_pid_file()
    if f is None:
        return True
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()
    return False


def ensure_running():
    if is_running():
        return
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "run"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(50):
        if is_running() and SOCK_PATH.exists():
            return
        time.sleep(0.1)


def stop():
    pid = _read_pid()
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run()
