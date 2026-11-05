# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Bleak client for MOKUKU II: one connection, one request in flight at a time."""
import asyncio
import binascii
import contextlib
import struct
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional

from bleak import BleakClient, BleakScanner

import protocol
from protocol import MessageType, Property, Reply

REPLY_TIMEOUT_SECONDS = 3.0
# Consecutive failed sectors a file transfer survives before it gives up.
TRANSFER_RETRIES = 3
# The device drops a host that writes nothing for 30 s.
KEEPALIVE_SECONDS = 10.0


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
        self.file_commands: asyncio.Queue = asyncio.Queue()
        self.file_data: asyncio.Queue = asyncio.Queue()
        self.pending_key = None
        self.last_write_time = 0.0

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
        # Published as self.client only once set up, so a drop mid-connect cannot clear it.
        client = BleakClient(address, disconnected_callback=self.handle_disconnect)
        await client.connect()
        try:
            # Catches a MOKUKU (S3) eye's address: its Transfer Message has no notify.
            characteristic = client.services.get_characteristic(protocol.MESSAGE_UUID)
            if characteristic is None or "notify" not in characteristic.properties:
                raise ConnectionError("not a MOKUKU II: Transfer Message has no notify")
            await client.start_notify(protocol.MESSAGE_UUID, self.handle_notification)
            await client.start_notify(protocol.FILE_COMMAND_UUID,
                                      lambda _, data: self.file_commands.put_nowait(bytes(data)))
            await client.start_notify(protocol.FILE_DATA_UUID,
                                      lambda _, data: self.file_data.put_nowait(bytes(data)))
            if not client.is_connected:
                raise ConnectionError("disconnected while connecting")
        except BaseException:
            await client.disconnect()
            raise
        self.request_lock = asyncio.Lock()
        self.client = client
        self.last_write_time = time.monotonic()
        self.loop.create_task(self.keep_alive(client))

    async def keep_alive(self, client: BleakClient) -> None:
        """Asks for the version whenever nothing was written for KEEPALIVE_SECONDS."""
        while self.client is client and client.is_connected:
            await asyncio.sleep(1.0)
            if time.monotonic() - self.last_write_time < KEEPALIVE_SECONDS:
                continue
            try:
                await self.get(Property.VERSION)
            except Exception:
                pass  # a lost link ends the loop through handle_disconnect

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

    def connected_client(self) -> BleakClient:
        """The current client; a local reference survives handle_disconnect clearing it."""
        client = self.client
        if client is None or not client.is_connected:
            raise ConnectionError("not connected")
        return client

    @contextlib.asynccontextmanager
    async def locked_client(self):
        """Holds the request lock, so one request or transfer is in flight at a time."""
        self.connected_client()
        async with self.request_lock:
            yield self.connected_client()

    async def write(self, client: BleakClient, uuid: str, value: bytes,
                    response: bool = False) -> None:
        self.last_write_time = time.monotonic()
        await client.write_gatt_char(uuid, value, response=response)

    async def request(self, message: bytes, write_response: bool = True) -> Reply:
        async with self.locked_client() as client:
            self.pending_key = (message[0], message[1])
            self.pending_reply = self.loop.create_future()
            await self.write(client, protocol.MESSAGE_UUID, message, write_response)
            try:
                return await asyncio.wait_for(self.pending_reply, REPLY_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                # Replies longer than one notification are only readable.
                reply = protocol.decode_reply(
                    bytes(await client.read_gatt_char(protocol.MESSAGE_UUID)))
                if reply and (reply.message_type, reply.property) == self.pending_key:
                    return reply
                raise TimeoutError(f"no reply to {message[:2].hex(' ')}")
            finally:
                self.pending_reply = None

    async def get(self, property: Property) -> Reply:
        return await self.request(protocol.encode_get(property))

    async def checked_request(self, message: bytes, write_response: bool = True) -> bytes:
        """The reply value; raises on a result other than OK."""
        reply = await self.request(message, write_response)
        if reply.result != protocol.Result.OK:
            raise IOError(protocol.describe_failure(reply))
        return reply.value

    async def list_directory(self, path: str = protocol.RECORDING_DIRECTORY) -> List[str]:
        """Every entry name, one page per request until an empty page."""
        names = []
        while True:
            page = protocol.decode_directory(
                await self.checked_request(protocol.encode_list_directory(len(names), path)))
            if not page:
                return names
            names += page

    async def delete_recordings(self) -> None:
        """Deletes every file in /sdcard/record; refused while recording."""
        await self.checked_request(protocol.encode_set(Property.DELETE_RECORDINGS, None))

    @contextlib.asynccontextmanager
    async def file_transfer(self):
        """Holds the request lock with the file queues emptied of earlier transfers' leftovers;
        a transfer that fails or is cancelled is stopped on the device."""
        async with self.locked_client() as client:
            for queue in (self.file_commands, self.file_data):
                while not queue.empty():
                    queue.get_nowait()
            try:
                yield client
            except BaseException:
                with contextlib.suppress(Exception):
                    await self.write(client, protocol.FILE_COMMAND_UUID, protocol.encode_stop())
                raise

    async def wait_idle(self) -> None:
        """Returns once no request or transfer, including a cancelled one stopping, holds the lock."""
        if self.request_lock is not None:
            async with self.request_lock:
                pass

    async def start_file_command(self, client: BleakClient, frame: bytes, path: str,
                                 timeout: float = REPLY_TIMEOUT_SECONDS) -> bytes:
        """Sends a start command; returns the values of its accepted reply."""
        await self.write(client, protocol.FILE_COMMAND_UUID, frame, response=True)
        command = struct.unpack_from("<H", frame)[0]
        while True:
            reply = protocol.decode_command_reply(
                await asyncio.wait_for(self.file_commands.get(), timeout))
            if reply and reply.command == command:
                break
        if reply.status != protocol.CommandStatus.ACCEPTED:
            raise IOError(f"{path}: {protocol.CommandStatus(reply.status).name.lower()}")
        return reply.values

    @staticmethod
    def count_failure(failures: int, path: str, sector: int) -> int:
        failures += 1
        if failures > TRANSFER_RETRIES:
            raise IOError(f"{path}: sector {sector} failed {failures} times")
        return failures

    async def receive_sector(self, sector: int, length: int) -> Optional[bytes]:
        """The sector's bytes once its last packet arrives; None when packets are missing, its CRC
        fails, or packets stop."""
        blob, next_sequence, intact = bytearray(), 0, True
        try:
            while True:
                packet = await asyncio.wait_for(self.file_data.get(), REPLY_TIMEOUT_SECONDS)
                index, sequence, payload = protocol.decode_packet(packet)
                if index != sector:
                    continue  # left over from a resent sector
                if sequence == 0:
                    blob, next_sequence, intact = bytearray(), 0, True
                if sequence != protocol.LAST_PACKET:
                    intact = intact and sequence == next_sequence
                    next_sequence = sequence + 1
                blob += payload
                if sequence == protocol.LAST_PACKET:
                    body = protocol.without_crc(bytes(blob))
                    return body if intact and body is not None and len(body) == length else None
        except asyncio.TimeoutError:
            return None

    async def download(self, path: str, output: Path, resume: bool = False,
                       on_progress: Optional[Callable[[int, int], None]] = None) -> int:
        """Saves the device file to output sector by sector, each checked by its CRC and
        acknowledged; returns the bytes transferred. With resume, continues after output's bytes
        once the device confirms they match its file. A failed or cancelled download leaves the
        bytes received in output, ready to resume. on_progress(received, size) after each sector."""
        offset = output.stat().st_size if resume and output.exists() else 0
        prefix_crc = 0
        with open(output, "r+b" if offset else "wb") as file:
            if offset:
                for chunk in iter(lambda: file.read(1 << 20), b""):
                    prefix_crc = binascii.crc_hqx(chunk, prefix_crc)
            async with self.file_transfer() as client:
                # The device reads the saved prefix to check it: allow for that at a slow 1 MB/s.
                size, sector_size, device_crc = struct.unpack("<IIH", await self.start_file_command(
                    client, protocol.encode_start_download(offset, path), path,
                    REPLY_TIMEOUT_SECONDS + offset / 1e6))
                if device_crc != prefix_crc:
                    raise IOError(f"{output} is not the start of {path}; download it without resuming")
                received = offset
                sector = failures = 0
                while received < size:
                    body = await self.receive_sector(sector, min(sector_size, size - received))
                    if body is None:
                        failures = self.count_failure(failures, path, sector)
                        status, next_sector = protocol.SectorStatus.CRC_ERROR, sector
                    else:
                        file.write(body)
                        received += len(body)
                        failures = 0
                        status, next_sector = protocol.SectorStatus.OK, sector + 1
                    await self.write(client, protocol.FILE_DATA_UUID,
                                     protocol.encode_acknowledgement(sector, status, next_sector))
                    sector = next_sector
                    if body is not None and on_progress:
                        on_progress(received, size)
        return size - offset

    async def upload(self, path: str, data: bytes,
                     on_progress: Optional[Callable[[int, int], None]] = None) -> None:
        """Writes data to path sector by sector, each checked by its CRC and acknowledged;
        on_progress(sent, size) after each sector. The device keeps the old file until the last
        sector arrives."""
        async with self.file_transfer() as client:
            sector_size, packet_size = struct.unpack("<IH", await self.start_file_command(
                client, protocol.encode_start_upload(len(data), path), path))
            chunk_size = packet_size - protocol.PACKET_HEADER_SIZE
            sectors = -(-len(data) // sector_size)
            sector = failures = 0
            while sector < sectors:
                start = sector * sector_size
                for packet in protocol.encode_sector(
                        sector, data[start:start + sector_size], chunk_size):
                    await self.write(client, protocol.FILE_DATA_UUID, packet)
                acknowledgement = await self.sector_acknowledgement(sector)
                if acknowledgement is None:  # resend the sector
                    failures = self.count_failure(failures, path, sector)
                    continue
                if acknowledgement.status == protocol.SectorStatus.WRITE_ERROR:
                    raise IOError(f"{path}: the device could not write sector {sector}")
                if acknowledgement.status == protocol.SectorStatus.OK:
                    failures = 0
                    if on_progress:
                        on_progress(min((sector + 1) * sector_size, len(data)), len(data))
                else:
                    failures = self.count_failure(failures, path, sector)
                sector = acknowledgement.next_sector

    async def sector_acknowledgement(self, sector: int):
        """The device's acknowledgement of this sector, None on a timeout."""
        try:
            while True:
                acknowledgement = protocol.decode_acknowledgement(
                    await asyncio.wait_for(self.file_data.get(), REPLY_TIMEOUT_SECONDS))
                if acknowledgement and acknowledgement.sector == sector:
                    return acknowledgement
        except asyncio.TimeoutError:
            return None

    async def set(self, property: Property, value) -> Reply:
        return await self.request(protocol.encode_set(property, value))

    async def send_data(self, speed_kmh: int, rpm: int, fuel_percent: int,
                        command: protocol.Command = protocol.Command.NONE) -> None:
        await self.write(self.connected_client(), protocol.MESSAGE_UUID,
                         protocol.encode_data(speed_kmh, rpm, fuel_percent, command))
