# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Bleak client for MOKUKU II: one connection, one request in flight at a time."""
import asyncio
import threading
from concurrent.futures import Future
from typing import Callable, List, NamedTuple, Optional

from bleak import BleakClient, BleakScanner

import protocol
from protocol import MessageType, Property, Reply

REPLY_TIMEOUT_SECONDS = 3.0


class Device(NamedTuple):
    name: str
    address: str
    rssi: int


class MokukuIIClient:
    """Runs Bleak on a background event loop; submit() returns a concurrent Future."""

    def __init__(self, on_disconnect: Optional[Callable[[], None]] = None):
        self.on_disconnect = on_disconnect
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client: Optional[BleakClient] = None
        self.request_lock: Optional[asyncio.Lock] = None
        self.pending_reply: Optional[asyncio.Future] = None
        self.pending_key = None

    def submit(self, coroutine) -> Future:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    async def scan(self, timeout: float = 4.0) -> List[Device]:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        devices = []
        for device, advertisement in found.values():
            name = advertisement.local_name or device.name or ""
            if name.startswith(protocol.DEVICE_NAME_PREFIX):
                devices.append(Device(name, device.address, advertisement.rssi))
        return sorted(devices, key=lambda device: -device.rssi)

    async def connect(self, address: str) -> None:
        await self.disconnect()
        self.request_lock = asyncio.Lock()
        self.client = BleakClient(address, disconnected_callback=self.handle_disconnect)
        await self.client.connect()
        # Catches a MOKUKU (S3) eye's address: its Transfer Message has no notify.
        characteristic = self.client.services.get_characteristic(protocol.MESSAGE_UUID)
        if characteristic is None or "notify" not in characteristic.properties:
            await self.disconnect()
            raise ConnectionError("not a MOKUKU II: Transfer Message has no notify")
        await self.client.start_notify(protocol.MESSAGE_UUID, self.handle_notification)

    async def disconnect(self) -> None:
        if self.client is not None:
            client, self.client = self.client, None
            await client.disconnect()

    def handle_disconnect(self, client: BleakClient) -> None:
        if self.client is client:
            self.client = None
            if self.on_disconnect:
                self.on_disconnect()

    def handle_notification(self, sender, data: bytearray) -> None:
        reply = protocol.decode_reply(bytes(data))
        if (reply and self.pending_reply and not self.pending_reply.done()
                and (reply.message_type, reply.property) == self.pending_key):
            self.pending_reply.set_result(reply)

    async def request(self, message: bytes) -> Reply:
        if not self.connected:
            raise ConnectionError("not connected")
        async with self.request_lock:
            self.pending_key = (message[0], message[1])
            self.pending_reply = self.loop.create_future()
            await self.client.write_gatt_char(protocol.MESSAGE_UUID, message, response=True)
            try:
                return await asyncio.wait_for(self.pending_reply, REPLY_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                # Replies longer than one notification are only readable.
                reply = protocol.decode_reply(
                    bytes(await self.client.read_gatt_char(protocol.MESSAGE_UUID)))
                if reply and (reply.message_type, reply.property) == self.pending_key:
                    return reply
                raise TimeoutError(f"no reply to {message[:2].hex(' ')}")
            finally:
                self.pending_reply = None

    async def get(self, property: Property) -> Reply:
        return await self.request(protocol.encode_get(property))

    async def set(self, property: Property, value) -> Reply:
        return await self.request(protocol.encode_set(property, value))

    async def send_data(self, speed_kmh: int, rpm: int, fuel_percent: int,
                        command: protocol.Command = protocol.Command.NONE) -> None:
        if not self.connected:
            raise ConnectionError("not connected")
        await self.client.write_gatt_char(
            protocol.MESSAGE_UUID, protocol.encode_data(speed_kmh, rpm, fuel_percent, command),
            response=False)
