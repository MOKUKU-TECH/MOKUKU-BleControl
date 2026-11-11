# Copyright 2026 MOKUKU Inc. All rights reserved.
"""MOKUKU II BLE wire format: data, set, and get messages on one characteristic.

Reference: doc/MOKUKU_II_BLE_CONTROL.md in the MobiliMOKUKU repository.
"""
import binascii
import struct
from enum import IntEnum
from typing import List, NamedTuple, Optional, Tuple

SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
MESSAGE_UUID = "d222e154-1a80-4e71-9a63-2aa2c0ce0a8c"
FILE_COMMAND_UUID = "18bf25fe-c5c8-40fe-ab13-9aa144d65b69"
FILE_DATA_UUID = "737cbd9b-848b-4fad-87b8-5c3b9f75768d"
DEVICE_NAME_PREFIX = "mokukuii"
STRING_MAX_LENGTH = 64
RECORDING_DIRECTORY = "/sdcard/record"
# File data packets: sector index (2), sequence number (1), bytes.
PACKET_HEADER_SIZE = 3
# Sequence number of a sector's last packet, which ends with the sector's CRC.
LAST_PACKET = 0xFF


class MessageType(IntEnum):
    DATA = 1
    SET = 2
    GET = 3


class Property(IntEnum):
    VERSION = 1
    MAC_ADDRESS = 2
    WIFI_NAME = 3
    WIFI_PASSWORD = 4
    REMOTE_ADDRESS = 5
    OBD_ENABLED = 6
    SD_CARD = 7
    WAKE_WORD_MODEL = 8
    MULTINET_LANGUAGE = 9
    DIRECTORY = 10
    DELETE_RECORDINGS = 13
    PANELS = 14
    PANEL_ACTION = 15
    FIRMWARE_UPDATE = 200
    ROLLBACK = 201


class Result(IntEnum):
    OK = 0
    UNKNOWN_PROPERTY = 1
    READ_ONLY = 2
    INVALID_VALUE = 3
    UNAVAILABLE = 4
    WRITE_ONLY = 5


class Command(IntEnum):
    NONE = 0
    REBOOT = 6
    ENABLE_OBD = 34
    DISABLE_OBD = 35


STRING_PROPERTIES = (Property.WIFI_NAME, Property.WIFI_PASSWORD, Property.REMOTE_ADDRESS)
# Set without a value; firmware update and rollback reboot the device after the reply.
ACTION_PROPERTIES = (Property.DELETE_RECORDINGS, Property.FIRMWARE_UPDATE, Property.ROLLBACK)


class PanelType(IntEnum):
    """The data panels an eye can list; memes are always shown as well."""
    SPEED = 1
    RPM = 2
    GRAVITY = 3
    PITCH_ROLL = 4
    FUEL = 5
    TRIP_DISTANCE = 6
    DRIVING_TIME = 7
    ROUTE = 8
    CLOCK = 9
    MUSIC = 10


class PanelAction(IntEnum):
    NEXT_LEFT = 1  # in meme mode, both eyes return to their data panels
    NEXT_RIGHT = 2
    TOGGLE_MODE = 3  # memes or data, both eyes


PANELS_PER_EYE = 5
EYES = ("left", "right")


def encode_panels(left, right) -> bytes:
    """Each eye's PANELS_PER_EYE different data panels, in "next page" order."""
    for eye, panels in zip(EYES, (left, right)):
        if len(panels) != PANELS_PER_EYE or len(set(panels)) != PANELS_PER_EYE:
            raise ValueError(f"the {eye} eye needs {PANELS_PER_EYE} different panels")
    return bytes(PanelType(panel) for panel in (*left, *right))


def decode_panels(value: bytes) -> Tuple[List[PanelType], List[PanelType]]:
    """Raises ValueError for a value that is not two eyes' panel types."""
    if len(value) != len(EYES) * PANELS_PER_EYE:
        raise ValueError(f"panels value of {len(value)} bytes")
    panels = [PanelType(byte) for byte in value]
    return panels[:PANELS_PER_EYE], panels[PANELS_PER_EYE:]


def panel_name(panel: PanelType) -> str:
    return panel.name.lower()


def parse_panels(text: str) -> List[PanelType]:
    """Comma-separated panel names, for example speed,rpm,gravity,pitch_roll,clock."""
    try:
        return [PanelType[name.strip().upper()] for name in text.split(",")]
    except KeyError as error:
        raise ValueError(f"unknown panel {error}; one of "
                         f"{', '.join(map(panel_name, PanelType))}") from None


class Reply(NamedTuple):
    message_type: MessageType
    property: int
    result: int
    value: bytes


def encode_get(property: Property, value: bytes = b"") -> bytes:
    return bytes([MessageType.GET, property]) + value


def encode_list_directory(first: int, path: str) -> bytes:
    """Names from index first on; the device replies with as many as one notification holds."""
    return encode_get(Property.DIRECTORY, struct.pack("<H", first) + path.encode("utf-8"))


def decode_directory(value: bytes) -> List[str]:
    return value.decode("utf-8", "replace").split(",") if value else []


class FileCommand(IntEnum):
    START_UPLOAD = 1
    START_DOWNLOAD = 2
    REPLY = 3
    STOP = 4


class CommandStatus(IntEnum):
    ACCEPTED = 0
    INVALID = 1
    UNAVAILABLE = 2


class SectorStatus(IntEnum):
    OK = 0
    CRC_ERROR = 1
    INDEX_ERROR = 2
    WRITE_ERROR = 3


class CommandReply(NamedTuple):
    command: int
    status: int
    values: bytes


class SectorAcknowledgement(NamedTuple):
    sector: int
    status: int
    next_sector: int


def crc16(data: bytes) -> int:
    """CRC-16/XMODEM, as Espressif's ble_ota."""
    return binascii.crc_hqx(data, 0)


def with_crc(body: bytes) -> bytes:
    return body + struct.pack("<H", crc16(body))


def without_crc(frame: bytes) -> Optional[bytes]:
    """The frame's body, or None when its CRC does not match."""
    if len(frame) < 2 or struct.unpack_from("<H", frame, len(frame) - 2)[0] != crc16(frame[:-2]):
        return None
    return frame[:-2]


def encode_start_upload(size: int, path: str) -> bytes:
    return with_crc(struct.pack("<HI", FileCommand.START_UPLOAD, size) + path.encode("utf-8"))


def encode_start_download(offset: int, path: str) -> bytes:
    """Sector 0 starts at offset; a resumed download's offset is the length already received."""
    return with_crc(struct.pack("<HI", FileCommand.START_DOWNLOAD, offset) + path.encode("utf-8"))


def encode_stop() -> bytes:
    return with_crc(struct.pack("<H", FileCommand.STOP))


def decode_command_reply(frame: bytes) -> Optional[CommandReply]:
    body = without_crc(frame)
    if body is None or len(body) < 6 or struct.unpack_from("<H", body)[0] != FileCommand.REPLY:
        return None
    command, status = struct.unpack_from("<HH", body, 2)
    return CommandReply(command, status, body[6:])


def encode_acknowledgement(sector: int, status: SectorStatus, next_sector: int) -> bytes:
    return with_crc(struct.pack("<HHH", sector, status, next_sector))


def decode_acknowledgement(frame: bytes) -> Optional[SectorAcknowledgement]:
    body = without_crc(frame)
    return SectorAcknowledgement(*struct.unpack("<HHH", body)) if body and len(body) == 6 else None


def encode_sector(sector: int, data: bytes, chunk_size: int) -> List[bytes]:
    """The packets of a sector: chunk_size bytes each of data and its CRC."""
    blob = with_crc(data)
    chunks = [blob[offset:offset + chunk_size] for offset in range(0, len(blob), chunk_size)]
    return [struct.pack("<HB", sector, LAST_PACKET if i == len(chunks) - 1 else i) + chunk
            for i, chunk in enumerate(chunks)]


def decode_packet(packet: bytes) -> Tuple[int, int, bytes]:
    """Sector, sequence number, bytes."""
    sector, sequence = struct.unpack_from("<HB", packet)
    return sector, sequence, packet[PACKET_HEADER_SIZE:]


def encode_set(property: Property, value) -> bytes:
    """Strings for the text properties, bool for OBD enabled, None for the action properties,
    (left, right) panel lists for panels, and a PanelAction for panel action."""
    if property in STRING_PROPERTIES:
        encoded = value.encode("utf-8")
        if not 1 <= len(encoded) <= STRING_MAX_LENGTH:
            raise ValueError(f"{property.name} must be 1-{STRING_MAX_LENGTH} bytes")
    elif property == Property.OBD_ENABLED:
        encoded = bytes([1 if value else 0])
    elif property in ACTION_PROPERTIES:
        encoded = b""
    elif property == Property.PANELS:
        encoded = encode_panels(*value)
    elif property == Property.PANEL_ACTION:
        encoded = bytes([PanelAction(value)])
    else:
        raise ValueError(f"{property.name} is read-only")
    return bytes([MessageType.SET, property]) + encoded


def encode_data(speed_kmh: int, rpm: int, fuel_percent: int,
                command: Command = Command.NONE) -> bytes:
    """Seconds since midnight and backlight are sent as zero until the device uses them."""
    rpm_times_four = min(max(rpm, 0) * 4, 0xFFFF)
    return bytes([MessageType.DATA, speed_kmh & 0xFF, rpm_times_four >> 8, rpm_times_four & 0xFF,
                  fuel_percent & 0xFF, 0, 0, 0, 0, 0, command])


def decode_reply(data: bytes) -> Optional[Reply]:
    if len(data) < 3 or data[0] not in (MessageType.SET, MessageType.GET):
        return None
    return Reply(MessageType(data[0]), data[1], data[2], bytes(data[3:]))


def describe_value(property: int, value: bytes) -> str:
    if property == Property.MAC_ADDRESS and len(value) == 6:
        return ":".join(f"{byte:02X}" for byte in value)
    if property == Property.OBD_ENABLED and len(value) == 1:
        return "on" if value[0] else "off"
    if property == Property.SD_CARD and len(value) == 8:
        total_megabytes, free_megabytes = struct.unpack("<II", value)
        return f"{total_megabytes} MB, {free_megabytes} MB free"
    if property == Property.PANELS:
        try:
            lists = decode_panels(value)
        except ValueError:
            return value.hex(" ")
        return "; ".join(f"{eye}: {', '.join(map(panel_name, panels))}"
                         for eye, panels in zip(EYES, lists))
    if property == Property.MULTINET_LANGUAGE:
        language = value.decode("utf-8", "replace")
        return {"cn": "Mandarin (cn)", "en": "English (en)"}.get(language, language)
    return value.decode("utf-8", errors="replace")


def property_name(property: int) -> str:
    try:
        return Property(property).name.lower()
    except ValueError:
        return f"property {property}"


def describe_result(result: int) -> str:
    try:
        return Result(result).name.lower().replace("_", " ")
    except ValueError:
        return f"result {result}"


def describe_failure(reply: Reply) -> str:
    return f"{property_name(reply.property)}: {describe_result(reply.result)}"
