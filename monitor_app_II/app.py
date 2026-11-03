#!/usr/bin/env python3
# Copyright 2026 MOKUKU Inc. All rights reserved.
"""MOKUKU II monitor: scan, connect, read device info, edit settings, and send dashboard data."""
import sys
import time
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# The look is shared with monitor_app; appended so local modules (ble_client) win.
sys.path.append(str(Path(__file__).resolve().parent.parent / "monitor_app"))
import theme  # noqa: E402

import protocol  # noqa: E402
from ble_client import MokukuIIClient  # noqa: E402
from protocol import Command, Property, Result  # noqa: E402

INFO_LABELS = {
    Property.VERSION: "MOKUKU version",
    Property.MAC_ADDRESS: "MAC address",
    Property.SD_CARD: "SD card",
}
TEXT_SETTING_LABELS = {
    Property.WIFI_NAME: "Wi-Fi name",
    Property.WIFI_PASSWORD: "Wi-Fi password",
    Property.REMOTE_ADDRESS: "Remote address",
}
# (label, maximum, default)
DATA_FIELDS = (("Speed km/h", 255, 60), ("RPM", 16383, 2400), ("Fuel %", 100, 75))


class MonitorWindow(QWidget):
    # Carries a finished concurrent Future and its success handler to the Qt thread.
    request_finished = pyqtSignal(object, object)
    device_disconnected = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.client = MokukuIIClient(on_disconnect=self.device_disconnected.emit)
        self.request_finished.connect(self.finish_request)
        self.device_disconnected.connect(lambda: self.set_connected(False))
        self.connected_widgets = []

        self.setWindowTitle("MOKUKU II Monitor")
        self.setGeometry(300, 300, 520, 780)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 12)
        layout.setSpacing(8)
        self.add_device_section(layout)
        layout.addWidget(self.horizontal_line())
        self.add_info_section(layout)
        layout.addWidget(self.horizontal_line())
        self.add_settings_section(layout)
        layout.addWidget(self.horizontal_line())
        self.add_data_section(layout)
        layout.addWidget(self.horizontal_line())
        layout.addWidget(theme.section_label("Activity Log"))
        self.log_view = QTextEdit(readOnly=True)
        self.log_view.setFont(theme.monospace_font(9))
        layout.addWidget(self.log_view, stretch=1)
        self.set_connected(False)

    @staticmethod
    def horizontal_line():
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.BORDER}; border: none;")
        return line

    def add_device_section(self, layout):
        layout.addWidget(theme.section_label("MOKUKU II Device"))
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        self.device_list = QListWidget()
        self.device_list.setFixedHeight(80)
        self.device_list.setFont(theme.monospace_font())
        layout.addWidget(self.device_list)

        row = QHBoxLayout()
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.scan)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("accent", True)
        self.connect_button.clicked.connect(self.connect_device)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_device)
        for button in (self.scan_button, self.connect_button, self.disconnect_button):
            row.addWidget(button)
        layout.addLayout(row)

    def add_info_section(self, layout):
        layout.addWidget(theme.section_label("Device Info"))
        form = QFormLayout()
        self.info_labels = {}
        for property, label in INFO_LABELS.items():
            value_label = QLabel("-")
            value_label.setFont(theme.monospace_font())
            value_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.info_labels[property] = value_label
            form.addRow(theme.hint_label(label), value_label)
        layout.addLayout(form)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_info)
        layout.addWidget(refresh_button)
        self.connected_widgets.append(refresh_button)

    def add_settings_section(self, layout):
        layout.addWidget(theme.section_label("Settings"))
        form = QFormLayout()
        self.setting_fields = {}
        for property, label in TEXT_SETTING_LABELS.items():
            field = QLineEdit()
            field.setMaxLength(protocol.STRING_MAX_LENGTH)
            if property == Property.WIFI_PASSWORD:
                field.setEchoMode(QLineEdit.Password)
            self.setting_fields[property] = field
            form.addRow(theme.hint_label(label), self.setting_row(property, field))
        self.obd_box = QCheckBox("OBD scanning")
        form.addRow(theme.hint_label("OBD"), self.setting_row(Property.OBD_ENABLED, self.obd_box))
        layout.addLayout(form)

    def setting_row(self, property, field):
        row = QHBoxLayout()
        row.addWidget(field, stretch=1)
        for text, handler in (("Get", self.get_setting), ("Set", self.set_setting)):
            button = QPushButton(text)
            button.clicked.connect(lambda _, handler=handler: handler(property))
            row.addWidget(button)
            self.connected_widgets.append(button)
        return row

    def add_data_section(self, layout):
        layout.addWidget(theme.section_label("Dashboard Data"))
        row = QHBoxLayout()
        self.data_fields = []
        for label, maximum, default in DATA_FIELDS:
            field = QLineEdit(str(default))
            field.setValidator(QIntValidator(0, maximum))
            row.addWidget(theme.hint_label(label))
            row.addWidget(field)
            self.data_fields.append(field)
        layout.addLayout(row)
        button_row = QHBoxLayout()
        send_button = QPushButton("Send Data")
        send_button.clicked.connect(lambda: self.send_data(Command.NONE))
        reboot_button = QPushButton("Reboot")
        reboot_button.clicked.connect(lambda: self.send_data(Command.REBOOT))
        button_row.addWidget(send_button)
        button_row.addWidget(reboot_button)
        layout.addLayout(button_row)
        self.connected_widgets += [send_button, reboot_button]

    def log(self, text):
        self.log_view.append(f"{time.strftime('%H:%M:%S')}  {text}")

    def run(self, coroutine, on_success=None):
        future = self.client.submit(coroutine)
        future.add_done_callback(lambda done: self.request_finished.emit(done, on_success))

    def finish_request(self, future, on_success):
        error = future.exception()
        if error:
            self.log(f"error: {error}")
            if not self.client.connected:
                self.set_connected(False)
        elif on_success:
            on_success(future.result())

    def set_status(self, state, text):
        color = theme.CONNECTION_COLORS.get(state, theme.TEXT_FAINT)
        self.status_label.setText(f"● {text}")
        self.status_label.setStyleSheet(f"color: {color}; font-size: 14px;")

    def set_connected(self, connected, name=""):
        self.set_status("connected" if connected else "disconnected",
                        f"Connected to {name}" if connected else "Disconnected")
        self.scan_button.setEnabled(not connected)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        for widget in self.connected_widgets:
            widget.setEnabled(connected)

    def scan(self):
        self.scan_button.setEnabled(False)
        self.set_status("scanning", "Scanning…")

        def show_devices(devices):
            self.scan_button.setEnabled(True)
            self.device_list.clear()
            for device in devices:
                item = QListWidgetItem(f"{device.name}   {device.address}   {device.rssi} dBm")
                item.setData(Qt.UserRole, device)
                self.device_list.addItem(item)
            if devices:
                self.device_list.setCurrentRow(0)
            self.set_status("disconnected", f"{len(devices)} found")

        self.run(self.client.scan(), show_devices)

    def connect_device(self):
        item = self.device_list.currentItem()
        if item is None:
            self.log("scan and pick a device first")
            return
        device = item.data(Qt.UserRole)
        self.connect_button.setEnabled(False)
        self.set_status("connecting", f"Connecting to {device.name}…")

        def connected(_):
            self.set_connected(True, device.name)
            self.log(f"connected to {device.name}")
            self.refresh_info()
            for property in (*TEXT_SETTING_LABELS, Property.OBD_ENABLED):
                self.get_setting(property)

        self.run(self.client.connect(device.address), connected)

    def disconnect_device(self):
        self.run(self.client.disconnect(), lambda _: self.set_connected(False))

    def refresh_info(self):
        for property in INFO_LABELS:
            self.run(self.client.get(property), self.show_info)

    def show_info(self, reply):
        label = self.info_labels[Property(reply.property)]
        if reply.result == Result.OK:
            label.setText(protocol.describe_value(reply.property, reply.value))
        else:
            label.setText(protocol.describe_result(reply.result))

    def get_setting(self, property):
        def show_setting(reply):
            if reply.result != Result.OK:
                self.log(f"get {protocol.property_name(property)}: "
                         f"{protocol.describe_result(reply.result)}")
            elif property == Property.OBD_ENABLED:
                self.obd_box.setChecked(reply.value[:1] == b"\x01")
            else:
                self.setting_fields[property].setText(reply.value.decode("utf-8", "replace"))

        self.run(self.client.get(property), show_setting)

    def set_setting(self, property):
        if property == Property.OBD_ENABLED:
            value = self.obd_box.isChecked()
        else:
            value = self.setting_fields[property].text()
        try:
            protocol.encode_set(property, value)
        except ValueError as error:
            self.log(str(error))
            return
        self.run(self.client.set(property, value),
                 lambda reply: self.log(f"set {protocol.property_name(property)}: "
                                        f"{protocol.describe_result(reply.result)}"))

    def send_data(self, command):
        speed_kmh, rpm, fuel_percent = (int(field.text() or 0) for field in self.data_fields)
        self.run(self.client.send_data(speed_kmh, rpm, fuel_percent, command),
                 lambda _: self.log(f"data sent ({command.name.lower()})"))

    def closeEvent(self, event):
        if self.client.connected:
            self.client.submit(self.client.disconnect()).result(timeout=5)
        super().closeEvent(event)


def main():
    application = QApplication(sys.argv)
    application.setStyleSheet(theme.APP_STYLESHEET)
    window = MonitorWindow()
    window.show()
    return application.exec_()


if __name__ == "__main__":
    sys.exit(main())
