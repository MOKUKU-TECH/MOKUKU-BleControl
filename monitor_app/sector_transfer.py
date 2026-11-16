# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Sector file download over File Command and File Data, the protocol of monitor_app_II/protocol.py."""

import asyncio
import binascii
import struct

FILE_COMMAND_UUID = "18bf25fe-c5c8-40fe-ab13-9aa144d65b69"
FILE_DATA_UUID = "737cbd9b-848b-4fad-87b8-5c3b9f75768d"
COMMAND_START_DOWNLOAD = 2
COMMAND_REPLY = 3
COMMAND_STOP = 4
COMMAND_STATUS_NAMES = {1: "invalid path or not allowed", 2: "missing or unreadable"}
SECTOR_OK = 0
SECTOR_CRC_ERROR = 1
# Sequence number of a sector's last packet, which ends with the sector's CRC.
LAST_PACKET = 0xFF
PACKET_HEADER_SIZE = 3
REPLY_TIMEOUT_SECONDS = 3.0
# Consecutive failed sectors a download survives before it gives up.
SECTOR_RETRIES = 3


def crc16(data, crc=0):
    return binascii.crc_hqx(data, crc)


def with_crc(body):
    return body + struct.pack("<H", crc16(body))


def without_crc(frame):
    if len(frame) < 2 or struct.unpack_from("<H", frame, len(frame) - 2)[0] != crc16(frame[:-2]):
        return None
    return frame[:-2]


def encode_start_download(offset, path):
    return with_crc(struct.pack("<HI", COMMAND_START_DOWNLOAD, offset) + path.encode("utf-8"))


def encode_stop():
    return with_crc(struct.pack("<H", COMMAND_STOP))


def encode_acknowledgement(sector, status, next_sector):
    return with_crc(struct.pack("<HHH", sector, status, next_sector))


class SectorDownload:
    """Downloads a device file into an open FileTransfer, resuming after its saved bytes."""

    def __init__(self, client, commands, data):
        self.client = client
        self.commands = commands
        self.data = data

    async def start(self, transfer):
        """Returns (size, sector_size) once the device accepts the download."""
        await self.client.write_gatt_char(
            FILE_COMMAND_UUID, encode_start_download(transfer.current_pos, transfer.remote_path), response=True)
        # The device reads the saved prefix to check its CRC: allow for that at a slow 1 MB/s.
        timeout = REPLY_TIMEOUT_SECONDS + transfer.current_pos / 1e6
        while True:
            body = without_crc(await asyncio.wait_for(self.commands.get(), timeout))
            if body and len(body) >= 6 and struct.unpack_from("<HH", body) == (COMMAND_REPLY, COMMAND_START_DOWNLOAD):
                break
        status = struct.unpack_from("<H", body, 4)[0]
        if status != 0:
            raise IOError(f"{transfer.remote_path}: {COMMAND_STATUS_NAMES.get(status, f'refused ({status})')}")
        size, sector_size, device_crc = struct.unpack_from("<IIH", body, 6)
        if device_crc != transfer.crc:
            raise IOError(f"{transfer.download_path} is not the start of {transfer.remote_path}")
        return size, sector_size

    async def receive_sector(self, sector, length):
        """The sector's bytes; None when packets are missing, its CRC fails, or packets stop."""
        blob, next_sequence, intact = bytearray(), 0, True
        try:
            while True:
                packet = await asyncio.wait_for(self.data.get(), REPLY_TIMEOUT_SECONDS)
                index, sequence = struct.unpack_from("<HB", packet)
                if index != sector:
                    continue  # left over from a resent sector
                if sequence == 0:
                    blob, next_sequence, intact = bytearray(), 0, True
                if sequence != LAST_PACKET:
                    intact = intact and sequence == next_sequence
                    next_sequence = sequence + 1
                blob += packet[PACKET_HEADER_SIZE:]
                if sequence == LAST_PACKET:
                    body = without_crc(bytes(blob))
                    return body if intact and body is not None and len(body) == length else None
        except asyncio.TimeoutError:
            return None

    async def run(self, transfer, stopped):
        """Saves sectors into transfer until the file is complete or stopped() is true."""
        for queue in (self.commands, self.data):
            while not queue.empty():
                queue.get_nowait()
        size, sector_size = await self.start(transfer)
        transfer.file_size = size
        sector = failures = 0
        while transfer.current_pos < size:
            if stopped():
                await self.client.write_gatt_char(FILE_COMMAND_UUID, encode_stop(), response=True)
                return
            body = await self.receive_sector(sector, min(sector_size, size - transfer.current_pos))
            if body is None:
                failures += 1
                if failures > SECTOR_RETRIES:
                    raise IOError(f"sector {sector} failed {failures} times")
                status, next_sector = SECTOR_CRC_ERROR, sector
            else:
                transfer.write(body)
                failures = 0
                status, next_sector = SECTOR_OK, sector + 1
            await self.client.write_gatt_char(
                FILE_DATA_UUID, encode_acknowledgement(sector, status, next_sector), response=False)
            sector = next_sector
