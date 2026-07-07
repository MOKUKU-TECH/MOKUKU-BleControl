"""Persistent daemon that reflects Claude Code's status onto a MOKUKU device.

Tracks every active Claude Code session (reported over a Unix socket by
report_status.py) and maintains a BLE connection to every discoverable
MOKUKU device (name prefix "mokuku"), pushing the most-recently-active
session's status as a short text string via BLE message id 52, which
overrides the velocity panel's number with that text (see
IDF_SHARED/panel/panel_car.c:SetSpeedPanelStatusText and
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
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

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


def encode_status_message(text):
    payload = text.encode("utf-8")[:STATUS_TEXT_MAX_BYTES]
    return bytes([52, len(payload)]) + payload


def format_status(info):
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
    elif status == "waiting":
        text = "Waiting"
    else:
        text = "Idle"
    return text[:STATUS_TEXT_MAX_BYTES]


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

    def current_status_text(self):
        if not self.sessions:
            return "Idle"
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
            summary = {
                "sessions": [
                    {"id": sid, "project": s["project"], "status": s["status"]}
                    for sid, s in daemon.sessions.items()
                ],
                "devices": [
                    {"address": addr, "connected": entry.get("client") is not None and entry["client"].is_connected}
                    for addr, entry in daemon.devices.items()
                ],
                "current_text": daemon.current_status_text(),
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


async def discover_mokuku_addresses(timeout=SCAN_TIMEOUT_SECONDS):
    scanner = BleakScanner()
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return [d.address for d in scanner.discovered_devices if d.name and d.name.startswith(DEVICE_NAME_PREFIX)]


async def manage_device(daemon, address):
    if address in daemon.devices:
        return
    entry = {"client": None}
    daemon.devices[address] = entry
    success = False
    try:
        client = BleakClient(address, disconnected_callback=lambda _c: daemon.devices.pop(address, None))
        await asyncio.wait_for(client.connect(), timeout=15.0)
        if not client.is_connected:
            return
        entry["client"] = client
        daemon.touch()
        success = True
    except Exception:
        return
    finally:
        if not success:
            daemon.devices.pop(address, None)


async def reconnect_loop(daemon):
    while True:
        for address in await discover_mokuku_addresses():
            if address not in daemon.devices:
                asyncio.create_task(manage_device(daemon, address))
        await asyncio.sleep(RECONNECT_INTERVAL_SECONDS)


async def refresh_loop(daemon):
    last_sent = {}
    while True:
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        daemon.prune_stale_sessions()
        text = daemon.current_status_text()
        message = encode_status_message(text)

        for address, entry in list(daemon.devices.items()):
            client = entry.get("client")
            if not client or not client.is_connected:
                continue
            if last_sent.get(address) == text:
                continue
            try:
                await asyncio.wait_for(client.write_gatt_char(CHARACTERISTIC_UUID_ACK, message), timeout=10.0)
                last_sent[address] = text
                daemon.touch()
            except Exception:
                daemon.devices.pop(address, None)
                last_sent.pop(address, None)
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=5.0)
                except Exception:
                    pass

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
