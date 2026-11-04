# Copyright 2026 MOKUKU Inc. All rights reserved.
"""MOKUKU II BLE wire format: data, set, and get messages on one characteristic.

Reference: doc/MOKUKU_II_BLE_CONTROL.md in the MobiliMOKUKU repository.
"""
import struct
from enum import IntEnum
from typing import List, NamedTuple, Optional, Tuple

SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
MESSAGE_UUID = "d222e154-1a80-4e71-9a63-2aa2c0ce0a8c"
DEVICE_NAME_PREFIX = "mokukuii"
STRING_MAX_LENGTH = 64
RECORDING_DIRECTORY = "/sdcard/record"


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
    FILE = 11
    FILE_DATA = 12
    DELETE_RECORDINGS = 13


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


def encode_open_file(path: str) -> bytes:
    return encode_get(Property.FILE, path.encode("utf-8"))


def encode_read_file(key: int, position: int) -> bytes:
    """The device sends as much as one notification holds."""
    return encode_get(Property.FILE_DATA, struct.pack("<II", key, position))


def decode_directory(value: bytes) -> List[str]:
    return value.decode("utf-8", "replace").split(",") if value else []


def decode_open_file(value: bytes) -> Tuple[int, int]:
    """File key and size."""
    return struct.unpack("<II", value)


def decode_file_data(value: bytes) -> Tuple[int, bytes]:
    """Position and bytes."""
    return struct.unpack_from("<I", value)[0], value[4:]


def encode_set(property: Property, value) -> bytes:
    """Strings for the text properties, bool for OBD enabled, None for delete recordings."""
    if property in STRING_PROPERTIES:
        encoded = value.encode("utf-8")
        if not 1 <= len(encoded) <= STRING_MAX_LENGTH:
            raise ValueError(f"{property.name} must be 1-{STRING_MAX_LENGTH} bytes")
    elif property == Property.OBD_ENABLED:
        encoded = bytes([1 if value else 0])
    elif property == Property.DELETE_RECORDINGS:
        encoded = b""
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
