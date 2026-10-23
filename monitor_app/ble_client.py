# Copyright 2026 MOKUKU Inc. All rights reserved.

import asyncio
import struct
import threading
import os
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QFrame,
    QMessageBox,
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)
from PyQt5.QtCore import Qt, Q_ARG

import theme
from common.qt_loading_dialog import LoadingDialog, DownloadingDialog
from bleak import BleakClient, BleakScanner, BleakError
from common.log import logging
from messager import messager

FILE_BUFFER_SIZE = 128
FILE_DOWNLOAD_CHUNK_SIZE = 255
CONFIG_FILE_PATH = "assets/config.txt"


class FileTransfer:
    def __init__(self, file_path=None):
        self.complete_callback = None
        self.reset()
        if file_path:
            self.open_file(file_path)

    def open_file(self, file_path):
        self.file = open(file_path, "rb")
        self.file_size = os.stat(file_path).st_size

    def reset(self):
        self.file_id = 0
        self.file_size = 0
        self.current_pos = 0
        self.file = None
        self.download_path = None
        self.error = None

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
        if len(data) != 10 or data[1] != 1:
            self.call_complete("Invalid file open response")
            return False
        ptr_value = int.from_bytes(data[2:6], byteorder="little")
        file_size = int.from_bytes(data[6:10], byteorder="little")
        logging.info(
            f"📥 Received file open {data[0]} {data[1]} : 0x{ptr_value:08X} {file_size}"
        )
        if ptr_value == 0 or file_size == 0:
            self.call_complete("Remote file is missing or empty")
            return False
        if not self.download_path:
            self.call_complete("No download destination selected")
            return False
        try:
            self.set(ptr_value, file_size, self.download_path)
        except OSError as error:
            self.call_complete(f"Cannot save file: {error}")
            return False
        return True

    def call_complete(self, error=None):
        if self.file and not self.file.closed:
            try:
                self.file.close()
            except OSError as close_error:
                if error is None:
                    error = f"Cannot finish saving file: {close_error}"
        self.error = error
        if error:
            logging.error("[FILE] %s", error)
        if self.complete_callback:
            self.complete_callback()
            self.complete_callback = None
        self.reset()

    def read_file_data(self, data):
        if self.file is None:
            return False
        if len(data) < 6 or len(data) != data[1] + 6:
            self.call_complete("Invalid file data packet")
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

        if data_size > 0:
            if self.current_pos + data_size > self.file_size:
                self.call_complete("File data exceeds the reported size")
                return False
            try:
                self.file.write(data[6:])
            except OSError as error:
                self.call_complete(f"Cannot write file: {error}")
                return False
            self.current_pos += data_size
        if self.current_pos == self.file_size:
            logging.info("[FILE] download file transfer complete: %s", self.download_path)
            self.call_complete()
            return False
        if data_size == 0:
            self.call_complete(f"Download stopped at {self.current_pos} of {self.file_size} bytes")
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
        self.last_file_request = None
        self.file_request_sent_at = 0
        self.file_request_retries = 0
        self.meme_states_callbacks = []
        self.info_query_callbacks = {}

    def request_meme_states(self, callback):
        self.meme_states_callbacks.append(callback)
        messager.push_meme_states_request()

    def request_info(self, message_id, callback, value="0"):
        self.info_query_callbacks[message_id] = callback
        if message_id == 57:
            messager.push_himokuku_wakeword_model_request()
        else:
            messager.push_string_message(message_id, value)

    def stop_client(self):
        self.client_stop = True
        messager.wake_ack_sender()

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
            if not d.name or not d.name.startswith(self.target_device):
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
                loop = asyncio.get_running_loop()
                message_ready = asyncio.Event()

                def wake_sender():
                    try:
                        loop.call_soon_threadsafe(message_ready.set)
                    except RuntimeError:
                        pass

                messager.set_ack_message_wakeup(wake_sender)
                next_realtime_send = loop.time()
                while not self.client_stop:
                    if not client.is_connected:
                        break
                    now = loop.time()
                    if self.send_realtime_data and now >= next_realtime_send:
                        byte_data = messager.get_message_to_send()
                        await client.write_gatt_char(
                            self.CHARACTERISTIC_UUID_MAIN, byte_data
                        )
                        next_realtime_send = loop.time() + 0.5

                    if self.client_stop:
                        break

                    message_ready.clear()
                    message_to_send = messager.pop_ack_message_to_send()
                    if message_to_send is not None:
                        if message_to_send[0] == 66:
                            self.last_file_request = message_to_send
                            self.file_request_sent_at = loop.time()
                        await client.write_gatt_char(
                            self.CHARACTERISTIC_UUID_ACK,
                            message_to_send,
                            response=message_to_send[0] != 66,
                        )
                        continue

                    now = loop.time()
                    if self.last_file_request and self.remote_file.file:
                        remaining = 5 - (now - self.file_request_sent_at)
                        if remaining <= 0:
                            if self.file_request_retries == 3:
                                self.last_file_request = None
                                self.remote_file.call_complete("No file data received after 3 retries")
                            else:
                                self.file_request_retries += 1
                                self.file_request_sent_at = now
                                await client.write_gatt_char(
                                    self.CHARACTERISTIC_UUID_ACK,
                                    self.last_file_request,
                                    response=False,
                                )
                            continue
                    else:
                        remaining = None

                    if self.send_realtime_data:
                        realtime_wait = max(0, next_realtime_send - now)
                        remaining = min(remaining, realtime_wait) if remaining is not None else realtime_wait
                    remaining = min(remaining, 1.0) if remaining is not None else 1.0
                    try:
                        await asyncio.wait_for(message_ready.wait(), timeout=remaining)
                    except asyncio.TimeoutError:
                        pass

                logging.info("Process End!")
        except BleakError as e:
            if self.message_label:
                self.message_label.setText(f"BLE Error: {str(e)}")
            logging.error(f"BLE Error: {str(e)}")
        finally:
            messager.set_ack_message_wakeup(None)
            self.connected = False
            if self.remote_file.complete_callback:
                self.remote_file.call_complete("BLE connection closed before download completed")
        logging.info("ble client stopped!")

    def require_file_data(self):
        # id(=66), buffer_size, file_id, begin
        byte_data = []
        byte_data.extend(struct.pack("<B", 66))  # first byte for message type ID
        byte_data.extend(struct.pack("<B", FILE_DOWNLOAD_CHUNK_SIZE))
        byte_data.extend(struct.pack("<I", self.remote_file.file_id))
        byte_data.extend(struct.pack("<I", self.remote_file.current_pos))
        messager.push_ack_message(byte_data)

    # This callback is called every time ESP32 sends a notification
    def notification_handler(self, sender: int, data: bytearray):
        if not data:
            logging.error("[BLE] empty notification")
            return
        if data[0] == 65:
            self.last_file_request = None
            self.file_request_retries = 0
            if self.remote_file.downloadfile_remote_created(data):
                self.require_file_data()
        elif data[0] == 66:
            self.last_file_request = None
            self.file_request_retries = 0
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
        elif data[0] == 56:
            state_count = data[1] if len(data) > 1 else 0
            if len(data) != state_count + 2:
                logging.error(f"[MEME] invalid state response length: {len(data)}")
                return
            meme_states = {meme_id: bool(data[meme_id + 2]) for meme_id in range(state_count)}
            logging.info(f"[MEME] received states for {state_count} memes")
            callbacks = self.meme_states_callbacks
            self.meme_states_callbacks = []
            for callback in callbacks:
                callback(meme_states)
        elif data[0] == 57:
            callback = self.info_query_callbacks.pop(57, None)
            if len(data) != 3 or data[1] != 1:
                logging.error(f"[SR] invalid wakeword-model response: {list(data)}")
                if callback:
                    callback(57, False, "Invalid right-eye model response.")
                return
            model = "wn10_himokuku" if data[2] else "Other WakeNet model"
            logging.info("[SR] right-eye wakeword model: %s", model)
            if callback:
                callback(57, True, model)
        else:
            if len(data) < 2:
                logging.error("[BLE] incomplete notification: %s", list(data))
                callback = self.info_query_callbacks.pop(data[0], None)
                if callback:
                    callback(data[0], False, "Incomplete device response.")
                return
            data_str = bytes(data[2:]).decode("utf-8", errors="replace")
            logging.info(
                f"📥 Received {len(data)}, id: {data[0]}, ret: {data[1]}, data: {data_str}"
            )
            callback = self.info_query_callbacks.pop(data[0], None)
            if callback:
                callback(data[0], data[1] == 1, data_str)


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
        device = self.device_table.item(item.row(), 0).data(Qt.UserRole)
        logging.info(f"Selected: {device['name']} ({device['address']})")

    def populate_device_table(self, devices):
        self.device_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            name_item = QTableWidgetItem(device["name"])
            name_item.setData(Qt.UserRole, device)
            self.device_table.setItem(row, 0, name_item)
            self.device_table.setItem(row, 1, QTableWidgetItem(device["address"]))
            self.device_table.setItem(row, 2, QTableWidgetItem(f"{device['rssi']} dBm"))
        self.device_table.resizeRowsToContents()

    def scan_done_event(self):
        logging.info("scan_done_event")
        if self.loading_dialog:
            self.loading_dialog.close()
        self.ble_scan_button.setEnabled(True)  # Re-enable button
        self.populate_device_table(self.ble_client.devices_list)

    def connect_ble(self):
        current_row = self.device_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self.parent, "WARNING", "Select a BLE device first.")
            return
        device = self.device_table.item(current_row, 0).data(Qt.UserRole)
        logging.info(f"Connect to: {device['name']} ({device['address']})")
        self.ble_client.start_threading_connect_to_device(device["address"])

    def init_wedgets(self, widget, message_label):
        self.parent = widget
        self.message_label = message_label
        self.ble_client.message_label = message_label

        elements = []

        cmd_label = theme.section_label("Bluetooth Connect")
        cmd_label.setFixedSize(widget.width, widget.line_height)
        elements.append(cmd_label)

        # ble interface
        self.ble_scan_button = QPushButton("BLE Scan for MOKUKU", widget)
        self.ble_scan_button.clicked.connect(self.start_ble_scan)
        elements.append(self.ble_scan_button)

        self.device_table = QTableWidget(0, 3, widget)
        self.device_table.setHorizontalHeaderLabels(["Name", "Address", "RSSI"])
        self.device_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.device_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.device_table.setToolTip("Select a device to connect")
        self.device_table.setStyleSheet(
            "QTableWidget { background-color: #000000; }"
            "QTableWidget::item { background-color: #000000; }"
            "QTableWidget::item:selected { background-color: rgba(5, 207, 120, 0.18); }"
        )
        self.device_table.itemClicked.connect(self.on_device_clicked)
        self.device_table.setFixedSize(
            widget.size().width(), int(widget.size().height() * 0.3)
        )
        elements.append(self.device_table)

        # connect ble
        self.ble_connect_button = QPushButton("Connect BLE", widget)
        self.ble_connect_button.clicked.connect(self.connect_ble)
        elements.append(self.ble_connect_button)

        return elements
