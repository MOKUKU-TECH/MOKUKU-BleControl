#!/usr/bin/env python3
# Copyright 2026 MOKUKU Inc. All rights reserved.
"""MOKUKU II monitor: scan, connect, read device info, edit settings, and send dashboard data."""
import sys
import time

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import protocol
from ble_client import MokukuIIClient
from protocol import Command, Property, Result

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


class MonitorWindow(QWidget):
    # Carries a finished concurrent Future and its success handler to the Qt thread.
    request_finished = pyqtSignal(object, object)
    device_disconnected = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.client = MokukuIIClient(on_disconnect=self.device_disconnected.emit)
        self.request_finished.connect(self.finish_request)
        self.device_disconnected.connect(lambda: self.set_connected(False, "disconnected"))
        self.setWindowTitle("MOKUKU II Monitor")
        self.resize(560, 720)
        self.connected_widgets = []

        layout = QVBoxLayout(self)
        layout.addLayout(self.create_connection_row())
        layout.addWidget(self.create_info_group())
        layout.addWidget(self.create_settings_group())
        layout.addWidget(self.create_data_group())
        self.log_view = QTextEdit(readOnly=True)
        layout.addWidget(self.log_view, stretch=1)
        self.set_connected(False, "disconnected")

    def create_connection_row(self):
        row = QHBoxLayout()
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.scan)
        self.device_box = QComboBox()
        self.device_box.setMinimumWidth(220)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        self.status_label = QLabel()
        for widget in (self.scan_button, self.device_box, self.connect_button, self.status_label):
            row.addWidget(widget)
        row.addStretch()
        return row

    def create_info_group(self):
        group = QGroupBox("Device")
        form = QFormLayout(group)
        self.info_labels = {}
        for property, label in INFO_LABELS.items():
            self.info_labels[property] = QLabel("-")
            form.addRow(label, self.info_labels[property])
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_info)
        form.addRow(refresh_button)
        self.connected_widgets.append(refresh_button)
        return group

    def create_settings_group(self):
        group = QGroupBox("Settings")
        form = QFormLayout(group)
        self.setting_fields = {}
        for property, label in TEXT_SETTING_LABELS.items():
            field = QLineEdit()
            field.setMaxLength(protocol.STRING_MAX_LENGTH)
            if property == Property.WIFI_PASSWORD:
                field.setEchoMode(QLineEdit.Password)
            self.setting_fields[property] = field
            form.addRow(label, self.create_setting_row(property, field))
        self.obd_box = QCheckBox("OBD scanning")
        form.addRow("OBD", self.create_setting_row(Property.OBD_ENABLED, self.obd_box))
        return group

    def create_setting_row(self, property, field):
        row = QHBoxLayout()
        row.addWidget(field, stretch=1)
        get_button = QPushButton("Get")
        get_button.clicked.connect(lambda: self.get_setting(property))
        set_button = QPushButton("Set")
        set_button.clicked.connect(lambda: self.set_setting(property))
        row.addWidget(get_button)
        row.addWidget(set_button)
        self.connected_widgets += [get_button, set_button]
        return row

    def create_data_group(self):
        group = QGroupBox("Dashboard data")
        row = QHBoxLayout(group)
        self.speed_box = self.create_spin_box(0, 255, 60, " km/h")
        self.rpm_box = self.create_spin_box(0, 16383, 2400, " rpm")
        self.fuel_box = self.create_spin_box(0, 100, 75, " %")
        send_button = QPushButton("Send")
        send_button.clicked.connect(lambda: self.send_data(Command.NONE))
        reboot_button = QPushButton("Reboot")
        reboot_button.clicked.connect(lambda: self.send_data(Command.REBOOT))
        for widget in (self.speed_box, self.rpm_box, self.fuel_box, send_button, reboot_button):
            row.addWidget(widget)
        self.connected_widgets += [send_button, reboot_button]
        return group

    @staticmethod
    def create_spin_box(minimum, maximum, value, suffix):
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setValue(value)
        box.setSuffix(suffix)
        return box

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
                self.set_connected(False, "disconnected")
        elif on_success:
            on_success(future.result())

    def set_connected(self, connected, status):
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.status_label.setText(status)
        for widget in self.connected_widgets:
            widget.setEnabled(connected)

    def scan(self):
        self.scan_button.setEnabled(False)
        self.status_label.setText("scanning…")

        def show_devices(devices):
            self.scan_button.setEnabled(True)
            self.device_box.clear()
            for device in devices:
                self.device_box.addItem(f"{device.name}  {device.rssi} dBm", device.address)
            self.status_label.setText(f"{len(devices)} found")

        self.run(self.client.scan(), show_devices)

    def toggle_connection(self):
        if self.client.connected:
            self.run(self.client.disconnect(),
                     lambda _: self.set_connected(False, "disconnected"))
            return
        address = self.device_box.currentData()
        if not address:
            self.log("scan and pick a device first")
            return
        self.status_label.setText("connecting…")

        def connected(_):
            self.set_connected(True, "connected")
            self.log(f"connected to {self.device_box.currentText().split()[0]}")
            self.refresh_info()
            for property in (*TEXT_SETTING_LABELS, Property.OBD_ENABLED):
                self.get_setting(property)

        self.run(self.client.connect(address), connected)

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
        self.run(self.client.send_data(self.speed_box.value(), self.rpm_box.value(),
                                       self.fuel_box.value(), command),
                 lambda _: self.log(f"data sent ({command.name.lower()})"))

    def closeEvent(self, event):
        if self.client.connected:
            self.client.submit(self.client.disconnect()).result(timeout=5)
        super().closeEvent(event)


def main():
    application = QApplication(sys.argv)
    window = MonitorWindow()
    window.show()
    return application.exec_()


if __name__ == "__main__":
    sys.exit(main())
