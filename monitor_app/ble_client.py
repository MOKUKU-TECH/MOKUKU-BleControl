# Copyright 2026 MOKUKU Inc. All rights reserved.

import asyncio
import struct
import psutil
import threading
import time
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QFrame,
    QMessageBox,
)
from PyQt5.QtCore import Qt, Q_ARG

from common.qt_loading_dialog import LoadingDialog, DownloadingDialog
from bleak import BleakClient, BleakScanner, BleakError
from common.log import logging
from messager import messager

FILE_BUFFER_SIZE = 128
CONFIG_FILE_PATH = "assets/config.txt"


class FileTransfer:
    file_id = 0
    file_size = 0
    current_pos = 0
    file = None
    complete_callback = None

    def __init__(self, file_path=None):
        self.reset()
        if file_path:
            open_file(file_path)

    def open_file(self, file_path):
        self.file = open(file_path, "rb")
        self.file_size = os.stat(file_path).st_size

    def reset(self):
        self.file_id = 0
        self.file_size = 0
        self.current_pos = 0
        self.file = None

    def set(self, id, size, file_name):
        self.file_id = id
        self.file_size = size
        self.current_pos = 0
        self.file = open(file_name, "wb")

    def extend_to_bytes(self, byte_data):
        byte_data.extend(struct.pack("<I", self.file_id))
        byte_data.extend(struct.pack("<I", self.file_size))
        byte_data.extend(struct.pack("<I", self.current_pos))
        return byte_data

    def downloadfile_remote_created(self, data):
        # getting file open response
        ptr_value = int.from_bytes(data[2:6], byteorder="little")
        file_size = int.from_bytes(data[6:10], byteorder="little")
        logging.info(
            f"📥 Received file open {data[0]} {data[1]} : 0x{ptr_value:08X} {file_size}"
        )
        if file_size == 0:
            logging.error("[FILE] file is Empty")
            self.call_complete()
            return False
        self.set(ptr_value, file_size, "data/test.rec")

    def call_complete(self):
        if self.complete_callback:
            self.complete_callback()
            self.complete_callback = None
        self.reset()

    def read_file_data(self, data):
        if self.file is None:
            logging.error("[FILE] file is None")
            self.call_complete()
            return False
        data_size = data[1]
        start_pos = int.from_bytes(data[2:6], byteorder="little")
        # check file beginning
        if start_pos != self.current_pos:
            # need to resend the request
            logging.error(
                f"[FILE] wrong file data position {start_pos}!={self.current_pos}"
            )
            return True

        # print progress

        if data_size > 0:
            self.file.write(data[6:])
            self.current_pos += data_size
        if data_size < FILE_BUFFER_SIZE:
            logging.info(f"[FILE] download file transfer complete")
            self.file.close()
            self.call_complete()
            return False
        return True

    def uploadfile_remote_created(self, data):
        self.file_id = int.from_bytes(data[2:6], byteorder="little")

    def uploadfile_send_data(self, data):
        if self.file is None:
            logging.error("[FILE] file is None")
            self.call_complete()
            return

        if data is not None:
            # check the message in data
            remote_file_id = int.from_bytes(data[1:5], byteorder="little")
            remote_data_begin = int.from_bytes(data[5:9], byteorder="little")
            if remote_file_id != self.file_id or remote_data_begin != self.current_pos:
                logging.error(
                    f"received wrong data {remote_file_id}?{self.file_id}, {remote_data_begin}?{self.current_pos}"
                )
                return

        data_begin = self.current_pos

        # read data and send
        chunk = self.file.read(FILE_BUFFER_SIZE)
        if not chunk:  # EOF
            # file reaches end
            # send a zero sized message to indicate file end
            byte_data = []
            byte_data.extend(struct.pack("<B", 64))  # first byte for message type ID
            byte_data.extend(struct.pack("<B", 0))
            byte_data.extend(struct.pack("<I", self.file_id))
            byte_data.extend(struct.pack("<I", self.current_pos))
            messager.push_ack_message(byte_data)

            logging.info(f"[FILE] upload file transfer complete")
            self.file.close()
            self.call_complete()
            return
        self.current_pos += len(chunk)

        # id(1 byte, =64), data_size(1 byte, n<255), file_key(4 bytes), begin_position(4 bytes), data(n bytes)
        byte_data = []
        byte_data.extend(struct.pack("<B", 64))  # first byte for message type ID
        byte_data.extend(struct.pack("<B", len(chunk)))
        byte_data.extend(struct.pack("<I", self.file_id))
        byte_data.extend(struct.pack("<I", data_begin))
        byte_data.extend(chunk)
        messager.push_ack_message(byte_data)


class BleClient:
    def __init__(self, target_device, send_realtime_data, timeout=3):
        self.SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
        self.CHARACTERISTIC_UUID_MAIN = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
        self.CHARACTERISTIC_UUID_ACK = "d222e154-1a80-4e71-9a63-2aa2c0ce0a8c"
        self.timeout = timeout
        self.send_realtime_data = send_realtime_data
        self.target_device = target_device
        self.devices_list = []

        # set bleak logging level
        bleak_logger = logging.getLogger("bleak")
        bleak_logger.setLevel(logging.WARNING)
        self.connected = False

        # set thread
        self.client_stop = False
        self.running = False
        self.thread = None
        self.scan_done_event = None
        self.message_label = None
        self.remote_file = FileTransfer()
        self.local_file = FileTransfer()

    def stop_client(self):
        self.client_stop = True

    def scan_for_device_threading(self, scan_done_event):
        if self.running:
            return

        self.running = True
        self.scan_done_event = scan_done_event
        # Start the thread with daemon=True (auto-exit when main program ends)
        self.thread = threading.Thread(target=self.run_scan_for_device, daemon=True)
        self.thread.start()

    def run_scan_for_device(self):
        asyncio.run(self.scan_for_device())
        if self.scan_done_event:
            self.scan_done_event()
            self.scan_done_event = None
        self.running = False

    async def scan_for_device(self):
        if self.message_label:
            self.message_label.setText(f"BLE scanning...")

        logging.info("start scan for device " + self.target_device)
        scanner = BleakScanner()

        await scanner.start()  # start scanning
        await asyncio.sleep(self.timeout)  # scan duration
        await scanner.stop()  # stop scanning

        self.devices_list = []
        for d in scanner.discovered_devices:
            if not d.name.startswith(self.target_device):
                continue
            device = {}
            device["name"] = d.name
            device["address"] = d.address
            device["rssi"] = d.rssi
            self.devices_list.append(device)

        logging.info("ble scan done!")
        if self.message_label:
            self.message_label.setText(f"BLE scan done.")
        return None

    def start_threading_connect_to_device(self, service_address):
        if self.thread.is_alive():
            logging.warning("thread is running.")
            return

        self.service_address = service_address
        self.running = True
        # Start the thread with daemon=True (auto-exit when main program ends)
        self.thread = threading.Thread(target=self.run_connect_to_device, daemon=True)
        self.thread.start()

    def run_connect_to_device(self):
        asyncio.run(self.connect_to_device())
        self.running = False

    def print_all_services(self, services):
        for service in services:
            print(f"\nService: {service.uuid}")
            print(f"  Handle: {service.handle}")
            print(f"  Description: {service.description}")

            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"    Characteristic: {char.uuid}")
                print(f"      Handle: {char.handle}")
                print(f"      Properties: {props}")

                # Print descriptors under this characteristic
                for descriptor in char.descriptors:
                    print(f"        Descriptor: {descriptor.uuid}")
                    print(f"          Handle: {descriptor.handle}")

    async def connect_to_device(self):
        if self.message_label:
            self.message_label.setText(f"Connecting to {self.service_address}...")
        try:
            async with BleakClient(self.service_address) as client:
                if not client.is_connected:
                    logging.warning("Failed to connect.")
                    return

                logging.info(f"✅ Connected to {self.service_address}!")
                self.client_stop = False

                if self.message_label:
                    self.message_label.setText(
                        f"✅ Connected to {self.service_address} device!"
                    )

                # Access the 'services' property to trigger service discovery
                # This replaces the deprecated client.get_services()
                services = client.services  # <-- New: Triggers discovery automatically
                self.print_all_services(services)

                characteristic = services.get_characteristic(
                    self.CHARACTERISTIC_UUID_MAIN
                )
                if not characteristic:
                    logging.error(
                        f"Characteristic main {self.CHARACTERISTIC_UUID_MAIN} not found"
                    )
                    return

                # Enable notifications
                await client.start_notify(
                    self.CHARACTERISTIC_UUID_MAIN, self.notification_handler
                )
                logging.info("🔔 Notifications enabled.")

                characteristic_ack = services.get_characteristic(
                    self.CHARACTERISTIC_UUID_ACK
                )
                if not characteristic_ack:
                    logging.error(
                        f"Characteristic ack {self.CHARACTERISTIC_UUID_ACK} not found"
                    )
                    return
                logging.info("✅ Ack characteristic found.")

                self.connected = True
                last_time = time.time()
                check_interval = 2  # check services every 5 seconds
                while not self.client_stop:
                    curr_time = time.time()
                    if (curr_time - last_time) > check_interval:
                        services = client.services
                        last_time = curr_time

                    if self.send_realtime_data:
                        byte_data = messager.get_message_to_send()
                        # print("Sent:", [hex(b) for b in byte_data])
                        await client.write_gatt_char(
                            self.CHARACTERISTIC_UUID_MAIN, byte_data
                        )
                        await asyncio.sleep(0.5)  # 500 ms

                    if self.client_stop:
                        break

                    message_to_send = messager.pop_ack_message_to_send()
                    if message_to_send is None:
                        await asyncio.sleep(0.1)  # 100 ms
                    else:
                        await client.write_gatt_char(
                            self.CHARACTERISTIC_UUID_ACK, message_to_send
                        )
                        # await asyncio.sleep(0.1)  # 100 ms

                logging.info("Process End!")
        except BleakError as e:
            if self.message_label:
                self.message_label.setText(f"BLE Error: {str(e)}")
            logging.error(f"BLE Error: {str(e)}")
            self.connected = False
        logging.info("ble client stopped!")

    def require_file_data(self):
        # id(=66), buffer_size, file_id, begin
        byte_data = []
        byte_data.extend(struct.pack("<B", 66))  # first byte for message type ID
        byte_data.extend(struct.pack("<B", FILE_BUFFER_SIZE))
        byte_data.extend(struct.pack("<I", self.remote_file.file_id))
        byte_data.extend(struct.pack("<I", self.remote_file.current_pos))
        messager.push_ack_message(byte_data)

    # This callback is called every time ESP32 sends a notification
    def notification_handler(self, sender: int, data: bytearray):
        if data[0] == 65:
            # getting file open response
            self.remote_file.downloadfile_remote_created(data)
            self.require_file_data()
        elif data[0] == 66:
            if self.remote_file.read_file_data(data):
                self.require_file_data()
        elif data[0] == 63:
            # file opened, we could begin to send data
            self.local_file.open_file(CONFIG_FILE_PATH)
            self.local_file.uploadfile_remote_created(data)
            self.local_file.uploadfile_send_data(None)
        elif data[0] == 64:
            # keep sending data
            self.local_file.uploadfile_send_data(data)
        else:
            data_str = bytes.fromhex(data[2:].hex()).decode("utf-8")
            logging.info(
                f"📥 Received {len(data)}, id: {data[0]}, ret: {data[1]}, data: {data_str}"
            )


class BleQtWidget:
    def __init__(self, ble_target, send_realtime_data):
        self.ble_client = BleClient(ble_target, send_realtime_data)
        self.parent = None

    def start_ble_scan(self):
        """Show scanning dialog and start async scan"""
        # 1. Create and show custom loading dialog
        self.loading_dialog = LoadingDialog(self.parent, title="BLE scanning")
        self.loading_dialog.show()
        # 2. Disable UI elements during scan
        self.ble_scan_button.setEnabled(False)
        # 3. Run scan asynchronously (non-blocking)
        self.ble_client.scan_for_device_threading(self.scan_done_event)

    def on_device_clicked(self, item):
        """Handle device selection (e.g., show more details)"""
        device = item.data(Qt.UserRole)  # Retrieve stored device data
        # self.status_label.setText(f"Selected: {device['name']} ({device['address']})")
        logging.info(f"Selected: {device['name']} ({device['address']})")

    def populate_device_list(self, devices):
        """Add scanned devices to the scrollable list"""
        self.device_list.clear()
        for device in devices:
            # Format device info (name, address, signal strength)
            item_text = (
                f"Name: {device['name']}\n"
                f"Address: {device['address']}\n"
                f"RSSI: {device['rssi']} dBm"  # Signal strength (lower = weaker)
            )
            # Create list item
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, device)  # Store full device data for later use
            self.device_list.addItem(item)

        # Optional: Allow selecting items
        self.device_list.itemClicked.connect(self.on_device_clicked)

    def scan_done_event(self):
        logging.info("scan_done_event")
        if self.loading_dialog:
            self.loading_dialog.close()
        self.ble_scan_button.setEnabled(True)  # Re-enable button
        self.populate_device_list(self.ble_client.devices_list)

    def connect_ble(self):
        current_item = self.device_list.currentItem().data(
            Qt.UserRole
        )  # Retrieve stored device data
        logging.info(f"Connect to: {current_item['name']} ({current_item['address']})")
        self.ble_client.start_threading_connect_to_device(current_item["address"])

    def init_wedgets(self, widget, message_label):
        self.parent = widget
        self.message_label = message_label
        self.ble_client.message_label = message_label

        elements = []

        cmd_label = QLabel("Bluetooth Connect")
        cmd_label.setFixedSize(widget.width, widget.line_height)
        cmd_label.setFont(widget.subtitle_font)
        elements.append(cmd_label)

        # ble interface
        self.ble_scan_button = QPushButton("BLE Scan for MOKUKU", widget)
        self.ble_scan_button.clicked.connect(self.start_ble_scan)
        elements.append(self.ble_scan_button)

        # Scrollable list for BLE devices
        self.device_list = QListWidget(widget)
        self.device_list.setAlternatingRowColors(True)  # Better readability
        self.device_list.setToolTip("Click a device to select it")
        self.device_list.setFixedSize(
            widget.size().width(), int(widget.size().height() * 0.3)
        )
        elements.append(self.device_list)

        # connect ble
        self.ble_connect_button = QPushButton("Connect BLE", widget)
        self.ble_connect_button.clicked.connect(self.connect_ble)
        elements.append(self.ble_connect_button)

        return elements
