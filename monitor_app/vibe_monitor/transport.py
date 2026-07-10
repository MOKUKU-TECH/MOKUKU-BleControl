"""Transport abstraction for the Vibe Coding Monitor: the app writes the same
BLE message protocol either over Bluetooth (BleTransport) or over the right
eye's USB serial port (SerialTransport, which frames each message - see
protocol.encode_serial_frame - and the firmware relays it to the left eye).

Both transports expose the same async surface used by Backend:
  list_targets() -> [(id, label, extra)]      # for the device/port picker
  connect(target_id) -> bool
  disconnect()
  write_main(bytes) / write_ack(bytes)         # Transfer Data / Transfer Message
  is_connected (property)
  on_disconnect                                # callback set by Backend
"""
import asyncio
import sys

from common.log import logging
from vibe_monitor.protocol import (
    CHARACTERISTIC_UUID_ACK,
    CHARACTERISTIC_UUID_MAIN,
    DEVICE_NAME_PREFIX,
    ESP32S3_USB_VID,
    SERIAL_BAUD,
    SERIAL_CHAN_ACK,
    SERIAL_CHAN_DATA,
    encode_serial_frame,
)

IS_LINUX = sys.platform.startswith("linux")
SCAN_TIMEOUT_SECONDS = 4.0
WRITE_TIMEOUT_SECONDS = 10.0


async def _bluetoothctl_connect(address, timeout=15.0):
    """bleak's own BlueZ D-Bus connect() has a known-flaky interaction on
    Linux (github.com/hbldh/bleak#1364 and others: connects then silently
    drops, times out client-side while the connection actually succeeds
    moments later at the BlueZ level, or the whole D-Bus call just hangs
    without honoring asyncio's timeout/cancellation) - `bluetoothctl
    connect` against the same bluetoothd doesn't have this problem, so it
    does the actual radio connection; bleak is only used afterwards for
    GATT reads/writes on the now-established link. Linux-only; returns True
    (nothing to pre-connect) elsewhere so the caller proceeds to bleak."""
    if not IS_LINUX:
        return True
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
    just as flaky on Linux/BlueZ. Running `bluetoothctl disconnect` afterwards
    forces the actual radio-level teardown regardless of whether bleak's call
    succeeded - otherwise MOKUKU can stay connected at the BlueZ level and just
    stop advertising, invisible to later scans. No-op on non-Linux."""
    if not IS_LINUX:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl", "disconnect", address,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, OSError):
        pass


class BleTransport:
    name = "ble"
    scan_label = "Scanning for MOKUKU devices..."

    def __init__(self):
        self.client = None
        self.connected_address = None
        self.on_disconnect = None

    @property
    def is_connected(self):
        return bool(self.client and self.client.is_connected)

    async def list_targets(self):
        """[(address, "name  address  RSSI n", rssi), ...] for mokuku* devices."""
        from bleak import BleakScanner
        # async with (rather than manual start()/stop()) guarantees stop() runs
        # even if the sleep is cancelled - an unstopped discovery session can
        # leave the adapter stuck "discovering" and silently break later scans.
        async with BleakScanner() as scanner:
            await asyncio.sleep(SCAN_TIMEOUT_SECONDS)
            devices = list(scanner.discovered_devices)
        return [(d.address, f"{d.name}   {d.address}   RSSI {d.rssi}", d.rssi)
                for d in devices if d.name and d.name.startswith(DEVICE_NAME_PREFIX)]

    async def connect(self, address):
        from bleak import BleakClient
        if not await _bluetoothctl_connect(address):
            return False

        def _on_disconnect(_client):
            self.client = None
            if self.on_disconnect:
                self.on_disconnect()

        client = BleakClient(address, disconnected_callback=_on_disconnect)
        try:
            await asyncio.wait_for(client.connect(timeout=20), timeout=25.0)
        except Exception:
            # bleak's client-side connect() can time out while BlueZ's underlying
            # connection actually completed moments later - don't discard it.
            if not client.is_connected:
                return False
        self.client = client
        self.connected_address = address
        return True

    async def disconnect(self):
        address = self.connected_address
        if self.client:
            try:
                await asyncio.wait_for(self.client.disconnect(), timeout=5.0)
            except Exception:
                pass
        self.client = None
        if address:
            await _bluetoothctl_disconnect(address)

    async def write_main(self, data):
        await asyncio.wait_for(
            self.client.write_gatt_char(CHARACTERISTIC_UUID_MAIN, data), timeout=WRITE_TIMEOUT_SECONDS)

    async def write_ack(self, data):
        await asyncio.wait_for(
            self.client.write_gatt_char(CHARACTERISTIC_UUID_ACK, data), timeout=WRITE_TIMEOUT_SECONDS)


class SerialTransport:
    name = "serial"
    scan_label = "Listing serial ports..."

    def __init__(self):
        self._serial = None
        self.on_disconnect = None

    @property
    def is_connected(self):
        return bool(self._serial and self._serial.is_open)

    async def list_targets(self):
        """[(device, "device  description", is_likely_esp32), ...]. ESP32-S3
        USB-Serial-JTAG ports (VID 0x303A) are flagged so the UI can prefer them."""
        from serial.tools import list_ports
        targets = []
        for port in list_ports.comports():
            likely = port.vid == ESP32S3_USB_VID
            label = f"{port.device}   {port.description}"
            targets.append((port.device, label, likely))
        # Show the likely-MOKUKU ports first.
        targets.sort(key=lambda t: not t[2])
        return targets

    async def connect(self, port):
        import serial
        loop = asyncio.get_running_loop()
        try:
            self._serial = await loop.run_in_executor(
                None, lambda: serial.Serial(port, SERIAL_BAUD, timeout=0, write_timeout=WRITE_TIMEOUT_SECONDS))
        except serial.SerialException as exc:
            logging.error(f"[serial] open {port} failed: {exc}")
            self._serial = None
            return False
        return True

    async def disconnect(self):
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    async def write_main(self, data):
        await self._write(encode_serial_frame(SERIAL_CHAN_DATA, bytes(data)))

    async def write_ack(self, data):
        await self._write(encode_serial_frame(SERIAL_CHAN_ACK, bytes(data)))

    async def _write(self, frame):
        import serial
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._serial.write, frame)
        except (serial.SerialException, OSError, AttributeError) as exc:
            # The port vanished (device unplugged/reset). Mark disconnected and
            # notify, mirroring bleak's disconnected_callback.
            logging.error(f"[serial] write failed, dropping port: {exc}")
            await self.disconnect()
            if self.on_disconnect:
                self.on_disconnect()
            raise
