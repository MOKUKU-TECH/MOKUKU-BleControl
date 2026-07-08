#!/usr/bin/env python3
# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Standalone app: scan for MOKUKU, let the user connect, and forward Claude
Code's status (received from report_status.py over a local Unix socket) to
the connected device over BLE.

Replaces the old headless vibe_monitor/daemon.py - that daemon scanned and
connected to MOKUKU automatically in the background with no visible state,
which made it genuinely confusing when the connection wasn't working (silent
retries, no way to tell "is it connected right now?" short of a CLI query
that could itself hang). This app makes the BLE connection something the
user can see and directly control, and shows both the device connection
state and the Claude Code status side by side in one window.

Run it manually (it is not lazily auto-started by the hooks - see
doc/VIBE_CODING_MONITOR.md):
    python vibe_monitor_app.py
"""
import asyncio
import json
import socket
import sys
import threading
from datetime import datetime

from bleak import BleakClient, BleakScanner
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import install_codex_hooks
import install_hooks
from common.log import logging
from vibe_monitor.protocol import (
    CHARACTERISTIC_UUID_ACK,
    CHARACTERISTIC_UUID_MAIN,
    DEVICE_NAME_PREFIX,
    SOCK_PATH,
    STATE_NAMES,
    SessionTracker,
    encode_status_message,
    encode_time_sync_message,
)

REFRESH_INTERVAL_SECONDS = 2
SCAN_TIMEOUT_SECONDS = 4.0


async def _bluetoothctl_connect(address, timeout=15.0):
    """bleak's own BlueZ D-Bus connect() has a known-flaky interaction on
    Linux (github.com/hbldh/bleak#1364 and others: connects then silently
    drops, times out client-side while the connection actually succeeds
    moments later at the BlueZ level, or the whole D-Bus call just hangs
    without honoring asyncio's timeout/cancellation) - `bluetoothctl
    connect` against the same bluetoothd doesn't have this problem, so it
    does the actual radio connection; bleak is only used afterwards for
    GATT reads/writes on the now-established link."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "connect", address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode == 0 and b"Connection successful" in stdout
    except (asyncio.TimeoutError, OSError):
        return False


async def _bluetoothctl_disconnect(address, timeout=10.0):
    """Symmetric with _bluetoothctl_connect: bleak's own disconnect() can be
    just as flaky on Linux/BlueZ as its connect() - if it silently fails or
    times out, our client-side "disconnected" state doesn't match reality,
    the radio link stays up, and MOKUKU (still thinking something's
    connected) never resumes BLE advertising - making it invisible to any
    later scan even though the app itself looks disconnected. Running
    `bluetoothctl disconnect` afterwards forces the actual radio-level
    teardown regardless of whether bleak's own call succeeded."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "disconnect", address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, OSError):
        pass


async def discover_mokuku_devices(timeout=SCAN_TIMEOUT_SECONDS):
    """Returns [(address, name, rssi), ...] for every discovered mokuku* device."""
    # async with (rather than manual start()/stop()) guarantees stop() runs
    # even if something above raises or the sleep is cancelled - otherwise an
    # unstopped discovery session can leave the adapter stuck "discovering"
    # and silently break every scan after it, with nothing visibly wrong.
    async with BleakScanner() as scanner:
        await asyncio.sleep(timeout)
        devices = list(scanner.discovered_devices)
    return [(d.address, d.name, d.rssi) for d in devices
            if d.name and d.name.startswith(DEVICE_NAME_PREFIX)]


class Backend(QObject):
    """Runs BLE and the Unix socket server on one dedicated background
    thread with its own persistent asyncio event loop, and only ever talks
    to the Qt UI thread through signals (thread-safe by Qt's own queued
    connection mechanism) - never touches a Qt widget directly."""

    devices_found = pyqtSignal(list)             # [(address, name, rssi), ...]
    connection_changed = pyqtSignal(str, str)     # (state, address); state: disconnected/scanning/connecting/connected
    log_message = pyqtSignal(str)
    claude_status_changed = pyqtSignal(str, str)  # (state_name, text)
    sessions_changed = pyqtSignal(list)           # [(session_id_or_None, label, is_effective), ...]; None = "Auto" entry

    def __init__(self):
        super().__init__()
        self.tracker = SessionTracker()
        self.loop = None
        self.client = None
        self.connected_address = None
        self._last_sent = None
        self._last_claude_status = None

    def start(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._run_server())
        self.loop.create_task(self._refresh_loop())
        self.loop.run_forever()

    def _log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        logging.info(f"[vibe_monitor] {message}")
        self.log_message.emit(f"{timestamp}  {message}")

    # --- user-triggered actions (called from the Qt thread) ---

    def scan(self):
        asyncio.run_coroutine_threadsafe(self._scan(), self.loop)

    def connect_to(self, address):
        asyncio.run_coroutine_threadsafe(self._connect(address), self.loop)

    def disconnect(self):
        asyncio.run_coroutine_threadsafe(self._disconnect(), self.loop)

    def select_session(self, session_id):
        """session_id=None reverts to automatic (most recently active)."""
        asyncio.run_coroutine_threadsafe(self._select_session(session_id), self.loop)

    # --- async implementation (runs on the background loop) ---

    async def _scan(self):
        self.connection_changed.emit("scanning", "")
        self._log("Scanning for MOKUKU devices...")
        try:
            devices = await asyncio.wait_for(discover_mokuku_devices(), timeout=SCAN_TIMEOUT_SECONDS + 10.0)
        except Exception as exc:
            # Without this, a scan that raises (or hangs past its own
            # internal timeout) left the button stuck on "Scanning..."
            # forever with zero feedback - indistinguishable from "can't
            # find the device" even though nothing was actually wrong with
            # the device.
            self._log(f"Scan failed: {exc}")
            devices = []
        self._log(f"Found {len(devices)} device(s)" if devices else "No MOKUKU devices found")
        self.devices_found.emit(devices)
        if not self.client or not self.client.is_connected:
            self.connection_changed.emit("disconnected", "")

    async def _connect(self, address):
        self.connection_changed.emit("connecting", address)
        self._log(f"Connecting to {address}...")
        if not await _bluetoothctl_connect(address):
            self._log(f"Failed to connect to {address}")
            self.connection_changed.emit("disconnected", "")
            return

        def on_disconnect(_client):
            self.client = None
            self._log(f"Disconnected from {address}")
            self.connection_changed.emit("disconnected", "")

        client = BleakClient(address, disconnected_callback=on_disconnect)
        try:
            await asyncio.wait_for(client.connect(timeout=20), timeout=25.0)
        except Exception:
            # bleak's client-side connect() can time out while BlueZ's
            # underlying connection actually completed moments later -
            # don't discard it just because our wait gave up first.
            if not client.is_connected:
                self._log(f"Failed to connect to {address}")
                self.connection_changed.emit("disconnected", "")
                return

        self.client = client
        self.connected_address = address
        self._last_sent = None
        self._log(f"Connected to {address}")
        self.connection_changed.emit("connected", address)

    async def _disconnect(self):
        address = self.connected_address
        if self.client:
            try:
                await asyncio.wait_for(self.client.disconnect(), timeout=5.0)
            except Exception:
                pass
        self.client = None
        if address:
            # Belt and suspenders: force the radio-level disconnect via
            # bluetoothctl too, regardless of whether bleak's own
            # disconnect() above actually succeeded - see
            # _bluetoothctl_disconnect's docstring for why this matters
            # (otherwise the device can stay connected at the BlueZ level
            # and simply stop being scannable, with the app none the wiser).
            await _bluetoothctl_disconnect(address)
        self._log("Disconnected")
        self.connection_changed.emit("disconnected", "")

    async def _select_session(self, session_id):
        self.tracker.select_session(session_id)
        if session_id is None:
            self._log("Session selection: back to auto (most recently active)")
        else:
            info = self.tracker.sessions.get(session_id)
            self._log(f"Session selection: pinned to {info['project'] if info else session_id[:8]}")
        self._emit_sessions_changed()
        # a manual selection should always refresh the display/device even if
        # the newly-effective session happens to have the same (state, text)
        # as whatever was showing before - the user just acted, so give
        # immediate feedback rather than silently no-op'ing on a coincidence.
        self._last_claude_status = None
        self._emit_current_status()

    # --- Unix socket server (receives status updates from report_status.py) ---

    async def _run_server(self):
        SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SOCK_PATH.exists():
            SOCK_PATH.unlink()
        server = await asyncio.start_unix_server(self._handle_client, path=str(SOCK_PATH))
        self._log(f"Listening for Claude Code status on {SOCK_PATH}")
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            msg = json.loads(line.decode().strip())

            if msg.get("cmd") == "status":
                state, text = self.tracker.current_status()
                summary = {
                    "sessions": [
                        {"id": sid, "agent": s.get("agent", "claude"), "project": s["project"], "status": s["status"]}
                        for sid, s in self.tracker.sessions.items()
                    ],
                    "devices": (
                        [{"address": self.connected_address, "connected": True}]
                        if self.client and self.client.is_connected else []
                    ),
                    "current_state": state,
                    "current_text": text,
                    "effective_session_id": self.tracker.effective_session_id(),
                    "auto_selected": self.tracker.is_auto_selected(),
                }
                writer.write((json.dumps(summary) + "\n").encode())
                await writer.drain()
                return

            session_id = msg.get("session_id")
            if not session_id:
                return
            if msg.get("ended"):
                self.tracker.end_session(session_id)
            else:
                self.tracker.update_session(session_id, msg.get("project"), msg.get("status"), msg.get("tool"),
                                            msg.get("detail"), pid=msg.get("pid"),
                                            agent=msg.get("agent") or "claude")
            self._emit_sessions_changed()
            self._emit_current_status(source=msg.get("project") or session_id[:8])
        except (json.JSONDecodeError, OSError):
            pass
        finally:
            writer.close()

    def _emit_sessions_changed(self):
        auto_effective = self.tracker.is_auto_selected()
        effective_id = self.tracker.effective_session_id()
        items = [(None, "Auto (most recently active)", auto_effective)]
        for sid, s in sorted(self.tracker.sessions.items(), key=lambda kv: -kv[1]["last_seen"]):
            items.append((sid, f"[{s.get('agent', 'claude')}] {s['project']} — {s['status']}", sid == effective_id))
        self.sessions_changed.emit(items)

    def _emit_current_status(self, source=None):
        # Only the effective session's status is ever sent to MOKUKU or shown
        # as "current" - see SessionTracker.effective_session_id(). With
        # multiple sessions active, updates from a non-effective one still
        # move it up the (most-recently-active-first) session list, but don't
        # otherwise change what's currently displayed/sent.
        state, text = self.tracker.current_status()
        if (state, text) == self._last_claude_status:
            return
        self._last_claude_status = (state, text)
        self.claude_status_changed.emit(STATE_NAMES[state], text)
        prefix = f"[{source}] " if source else ""
        self._log(f"{prefix}status -> {STATE_NAMES[state]}: {text.replace(chr(10), ' - ')}")

    # --- periodic push to the connected device ---

    async def _refresh_loop(self):
        while True:
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
            session_count_before = len(self.tracker.sessions)
            self.tracker.prune_stale_sessions()
            if len(self.tracker.sessions) != session_count_before:
                self._emit_sessions_changed()
                self._emit_current_status()  # a pruned session may have been the effective one

            if not self.client or not self.client.is_connected:
                continue

            try:
                await asyncio.wait_for(
                    self.client.write_gatt_char(CHARACTERISTIC_UUID_MAIN, encode_time_sync_message()), timeout=10.0)
            except Exception:
                continue  # disconnected_callback (if it fires) handles the UI update

            state, text = self.tracker.current_status()
            if self._last_sent == (state, text):
                continue
            try:
                await asyncio.wait_for(
                    self.client.write_gatt_char(CHARACTERISTIC_UUID_ACK, encode_status_message(state, text)),
                    timeout=10.0)
                self._last_sent = (state, text)
            except Exception:
                pass


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.devices = []
        self.last_connected_address = None
        self.backend = Backend()
        self._init_ui()
        self.backend.devices_found.connect(self._on_devices_found)
        self.backend.connection_changed.connect(self._on_connection_changed)
        self.backend.log_message.connect(self._on_log_message)
        self.backend.claude_status_changed.connect(self._on_claude_status_changed)
        self.backend.sessions_changed.connect(self._on_sessions_changed)
        self.backend.start()

    def _init_ui(self):
        self.setWindowTitle("MOKUKU Vibe Coding Monitor")
        self.setGeometry(300, 300, 480, 640)
        layout = QVBoxLayout()

        device_label = QLabel("MOKUKU Device")
        device_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(device_label)

        self.connection_status_label = QLabel("Disconnected")
        layout.addWidget(self.connection_status_label)

        self.scan_button = QPushButton("Scan", self)
        self.scan_button.clicked.connect(self.backend.scan)
        layout.addWidget(self.scan_button)

        self.device_list = QListWidget(self)
        self.device_list.setFixedHeight(120)
        layout.addWidget(self.device_list)

        button_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect", self)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.connect_button.setEnabled(False)
        button_row.addWidget(self.connect_button)

        self.disconnect_button = QPushButton("Disconnect", self)
        self.disconnect_button.clicked.connect(self.backend.disconnect)
        self.disconnect_button.setEnabled(False)
        button_row.addWidget(self.disconnect_button)

        self.reconnect_button = QPushButton("Reconnect", self)
        self.reconnect_button.clicked.connect(self._on_reconnect_clicked)
        self.reconnect_button.setEnabled(False)
        button_row.addWidget(self.reconnect_button)
        layout.addLayout(button_row)

        layout.addWidget(self._hline())

        claude_label = QLabel("Claude Code Status")
        claude_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(claude_label)

        self.claude_status_label = QLabel("Idle")
        self.claude_status_label.setStyleSheet("font-size: 20px;")
        layout.addWidget(self.claude_status_label)

        sessions_label = QLabel("Claude Code Sessions (click to choose which one to send)")
        layout.addWidget(sessions_label)

        self.session_list = QListWidget(self)
        self.session_list.setFixedHeight(100)
        self.session_list.itemClicked.connect(self._on_session_clicked)
        layout.addWidget(self.session_list)

        layout.addWidget(self._hline())

        setup_label = QLabel("Setup")
        setup_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(setup_label)

        self.install_hooks_button = QPushButton("Install Claude Code Hooks", self)
        self.install_hooks_button.clicked.connect(self._on_install_hooks_clicked)
        layout.addWidget(self.install_hooks_button)

        self.install_codex_hooks_button = QPushButton("Install Codex Hooks", self)
        self.install_codex_hooks_button.clicked.connect(self._on_install_codex_hooks_clicked)
        layout.addWidget(self.install_codex_hooks_button)

        layout.addWidget(self._hline())

        log_label = QLabel("Activity Log")
        log_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(log_label)

        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        socket_label = QLabel(f"Socket: {SOCK_PATH}")
        socket_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(socket_label)

        self.setLayout(layout)

    @staticmethod
    def _hline():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _on_devices_found(self, devices):
        self.devices = devices
        self.device_list.clear()
        for address, name, rssi in devices:
            item = QListWidgetItem(f"{name}   {address}   RSSI {rssi}")
            item.setData(Qt.UserRole, address)
            self.device_list.addItem(item)
        self.connect_button.setEnabled(bool(devices))

    def _on_connect_clicked(self):
        item = self.device_list.currentItem()
        if not item:
            QMessageBox.warning(self, "WARNING", "Select a device from the list first.")
            return
        self.backend.connect_to(item.data(Qt.UserRole))

    def _on_reconnect_clicked(self):
        if self.last_connected_address:
            self.backend.connect_to(self.last_connected_address)

    def _on_connection_changed(self, state, address):
        labels = {
            "disconnected": "Disconnected",
            "scanning": "Scanning...",
            "connecting": f"Connecting to {address}...",
            "connected": f"Connected to {address}",
        }
        self.connection_status_label.setText(labels.get(state, state))
        if state == "connected":
            self.last_connected_address = address

        is_connected = state == "connected"
        is_busy = state in ("scanning", "connecting")
        self.scan_button.setEnabled(not is_busy)
        self.connect_button.setEnabled(not is_connected and not is_busy and bool(self.devices))
        self.disconnect_button.setEnabled(is_connected)
        self.reconnect_button.setEnabled(not is_connected and not is_busy and self.last_connected_address is not None)

    def _on_log_message(self, message):
        self.log_view.append(message)

    def _on_claude_status_changed(self, state_name, text):
        self.claude_status_label.setText(f"{state_name}: {text.replace(chr(10), ' - ')}")

    def _on_sessions_changed(self, items):
        self.session_list.clear()
        for session_id, label, is_effective in items:
            marker = "● " if is_effective else "○ "  # ● currently sent to MOKUKU / ○ not
            item = QListWidgetItem(marker + label)
            item.setData(Qt.UserRole, session_id)
            if is_effective:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.session_list.addItem(item)

    def _on_session_clicked(self, item):
        self.backend.select_session(item.data(Qt.UserRole))

    def _on_install_hooks_clicked(self):
        # Global (~/.claude/settings.json), not --project: this button has
        # no notion of "current project" (it's a standalone app, often
        # launched from a desktop icon with its own cwd), so it wires up
        # every Claude Code session on this machine, matching plain
        # `python3 install_hooks.py` from the CLI.
        path = install_hooks.settings_path(project=False)
        command = f"{sys.executable} {install_hooks.REPORT_SCRIPT}"
        try:
            settings = install_hooks.load_settings(path)
            count = install_hooks.install(settings, command)
            if count:
                install_hooks.write_settings(path, settings)
                message = f"Installed {count} hook entr{'y' if count == 1 else 'ies'} into {path}"
            else:
                message = f"Claude Code hooks already installed ({path})"
        except OSError as exc:
            message = f"Failed to install Claude Code hooks: {exc}"
        self._on_log_message(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
        QMessageBox.information(self, "Claude Code Hooks", message)

    def _on_install_codex_hooks_clicked(self):
        # Global (~/.codex/hooks.json), matching the Claude button's choice
        # and plain `python3 install_codex_hooks.py` from the CLI.
        path = install_codex_hooks.hooks_path(project=False)
        try:
            config = install_codex_hooks.load_hooks(path)
            count = install_codex_hooks.install(config, sys.executable)
            if count:
                install_hooks.write_settings(path, config)
                message = (f"Installed {count} hook entr{'y' if count == 1 else 'ies'} into {path}.\n\n"
                           "Codex requires you to manually trust new hooks before they run - "
                           "open the Codex CLI and run /hooks to review and approve them.")
            else:
                message = f"Codex hooks already installed ({path})"
        except OSError as exc:
            message = f"Failed to install Codex hooks: {exc}"
        self._on_log_message(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
        QMessageBox.information(self, "Codex Hooks", message)

    def closeEvent(self, event):
        self.backend.disconnect()
        event.accept()


def _another_instance_running():
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(str(SOCK_PATH))
        return True
    except OSError:
        return False


if __name__ == "__main__":
    if _another_instance_running():
        print(f"Another vibe_monitor_app.py already seems to be running (socket {SOCK_PATH} is live).\n"
              "Quit that one first - two instances would fight over the same MOKUKU connection.", file=sys.stderr)
        sys.exit(1)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
