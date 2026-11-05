#!/usr/bin/env python3
# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Command-line MOKUKU II client.

    python cli.py scan
    python cli.py get version sd_card
    python cli.py set wifi_name Home
    python cli.py set obd_enabled 0
    python cli.py data 60 2400 75 [--command reboot]
    python cli.py ls [/sdcard/record]
    python cli.py download /sdcard/record/mobili_1.record [--output mobili_1.record] [--resume]
    python cli.py upload firmware.bin /sdcard/firmware.bin
    python cli.py delete-recordings --yes

Without --address, it connects to the strongest mokukuii* device found. Ctrl-C stops a transfer on
the device too; an interrupted download keeps its bytes for --resume.
"""
import argparse
import sys
import time
from pathlib import Path

from bleak.exc import BleakError

import protocol
from ble_client import MokukuIIClient
from protocol import Command, Property


def parse_property(name: str) -> Property:
    try:
        return Property[name.upper()]
    except KeyError:
        raise argparse.ArgumentTypeError(
            f"unknown property {name}; one of {', '.join(p.name.lower() for p in Property)}")


def parse_set_value(property: Property, text: str):
    if property == Property.OBD_ENABLED:
        return text.lower() in ("1", "on", "true")
    return text


def transfer_rate(size: int, started: float) -> str:
    seconds = time.monotonic() - started
    return f" in {seconds:.1f} s, {size / 1024 / seconds:.1f} KB/s" if seconds > 0 else ""


def print_reply(reply) -> None:
    name = protocol.property_name(reply.property)
    if reply.result != protocol.Result.OK:
        print(protocol.describe_failure(reply))
    elif reply.message_type == protocol.MessageType.GET:
        print(f"{name}: {protocol.describe_value(reply.property, reply.value)}")
    else:
        print(f"{name}: set")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--address", help="device address; scans when omitted")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("scan")
    get_parser = commands.add_parser("get")
    get_parser.add_argument("properties", nargs="+", type=parse_property)
    set_parser = commands.add_parser("set")
    set_parser.add_argument("property", type=parse_property)
    set_parser.add_argument("value")
    data_parser = commands.add_parser("data")
    data_parser.add_argument("speed_kmh", type=int)
    data_parser.add_argument("rpm", type=int)
    data_parser.add_argument("fuel_percent", type=int)
    data_parser.add_argument("--command", choices=[c.name.lower() for c in Command], default="none")
    list_parser = commands.add_parser("ls")
    list_parser.add_argument("path", nargs="?", default=protocol.RECORDING_DIRECTORY)
    download_parser = commands.add_parser("download")
    download_parser.add_argument("path")
    download_parser.add_argument("--output", help="local file; the device file's name when omitted")
    download_parser.add_argument("--resume", action="store_true",
                                 help="continue after the bytes already in the local file")
    upload_parser = commands.add_parser("upload")
    upload_parser.add_argument("source", type=Path, help="local file")
    upload_parser.add_argument("path", help="device path under /sdcard; replaced when it exists")
    delete_parser = commands.add_parser("delete-recordings")
    delete_parser.add_argument("--yes", action="store_true", required=True,
                               help="confirm deleting every file in /sdcard/record")
    arguments = parser.parse_args()
    if arguments.action == "set":
        try:
            protocol.encode_set(arguments.property,
                                parse_set_value(arguments.property, arguments.value))
        except ValueError as error:
            parser.error(str(error))

    client = MokukuIIClient()

    def run(coroutine):
        future = client.submit(coroutine)
        try:
            return future.result()
        except KeyboardInterrupt:
            future.cancel()
            client.submit(client.wait_idle()).result(timeout=10)  # the device is told to stop
            raise

    address = arguments.address
    if arguments.action == "scan" or not address:
        devices = run(client.scan())
        if arguments.action == "scan":
            for device in devices:
                print(f"{device.name}  {device.address}  {device.rssi} dBm")
            return 0
        if not devices:
            print(f"no {protocol.DEVICE_NAME_PREFIX}* device found", file=sys.stderr)
            return 1
        address = devices[0].address

    try:
        run(client.connect(address))
    except (BleakError, ConnectionError) as error:
        print(f"{address}: {error}", file=sys.stderr)
        return 1
    print(f"connected to {address}")
    try:
        if arguments.action == "get":
            for property in arguments.properties:
                print_reply(run(client.get(property)))
        elif arguments.action == "set":
            print_reply(run(client.set(arguments.property,
                                       parse_set_value(arguments.property, arguments.value))))
        elif arguments.action == "ls":
            for name in run(client.list_directory(arguments.path)):
                print(name)
        elif arguments.action == "download":
            output = Path(arguments.output or Path(arguments.path).name)
            show = lambda received, size: print(f"\r{received}/{size} bytes", end="", flush=True)
            started = time.monotonic()
            transferred = run(client.download(arguments.path, output, arguments.resume, show))
            print(f"\nsaved {output}{transfer_rate(transferred, started)}")
        elif arguments.action == "upload":
            data = arguments.source.read_bytes()
            show = lambda sent, size: print(f"\r{sent}/{size} bytes", end="", flush=True)
            started = time.monotonic()
            run(client.upload(arguments.path, data, show))
            print(f"\nuploaded {arguments.path}{transfer_rate(len(data), started)}")
        elif arguments.action == "delete-recordings":
            run(client.delete_recordings())
            print("recordings deleted")
        else:
            run(client.send_data(arguments.speed_kmh, arguments.rpm, arguments.fuel_percent,
                                 Command[arguments.command.upper()]))
            print("data sent")
    except OSError as error:
        print(error, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        return 130
    finally:
        run(client.disconnect())
    return 0


if __name__ == "__main__":
    sys.exit(main())
