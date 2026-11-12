#!/usr/bin/env python3
# Copyright 2026 MOKUKU Inc. All rights reserved.
"""MOKUKU II monitor: scan, connect, read device info, edit settings, download recordings, send
dashboard data, and update the firmware."""
import sys
import time
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
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
from protocol import Command, PanelAction, PanelType, Property, Result  # noqa: E402

INFO_LABELS = {
    Property.VERSION: "MOKUKU version",
    Property.MAC_ADDRESS: "MAC address",
    Property.SD_CARD: "SD card",
    Property.WAKE_WORD_MODEL: "Wake word",
}
TEXT_SETTING_LABELS = {
    Property.WIFI_NAME: "Wi-Fi name",
    Property.WIFI_PASSWORD: "Wi-Fi password",
    Property.REMOTE_ADDRESS: "Remote address",
}
# (label, maximum, default)
DATA_FIELDS = (("Speed km/h", 255, 60), ("RPM", 16383, 2400), ("Fuel %", 100, 75))
# Where build_idf.sh writes the app image.
FIRMWARE_DIRECTORY = Path(__file__).resolve().parents[2] / "IDF_MOKUKU_II_prototype" / "output"


class FirmwareDialog(QDialog):
    """Sends a firmware image into the device's other slot with a progress bar, or rolls back to the
    firmware in that slot. Either way the device restarts."""
    progress = pyqtSignal(int, int)

    def __init__(self, monitor):
        super().__init__(monitor)
        self.monitor = monitor
        self.future = None
        self.setWindowTitle("Firmware Update")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(theme.section_label("Update"))
        file_row = QHBoxLayout()
        self.path_field = QLineEdit(placeholderText="App image (.bin), for example "
                                                    "IDF_MOKUKU_II_prototype.bin")
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.browse)
        file_row.addWidget(self.path_field, stretch=1)
        file_row.addWidget(self.browse_button)
        layout.addLayout(file_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.status_label = theme.hint_label("Both eyes show the update's progress; the device "
                                             "restarts when it ends.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        update_row = QHBoxLayout()
        self.update_button = QPushButton("Update")
        self.update_button.clicked.connect(self.start_update)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_update)
        self.cancel_button.setEnabled(False)
        update_row.addWidget(self.update_button)
        update_row.addWidget(self.cancel_button)
        layout.addLayout(update_row)

        layout.addWidget(monitor.horizontal_line())
        layout.addWidget(theme.section_label("Firmware Slots"))
        self.slots_list = QListWidget()
        self.slots_list.setFont(theme.monospace_font(9))
        self.slots_list.setFixedHeight(64)
        layout.addWidget(self.slots_list)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_slots)
        layout.addWidget(self.refresh_button)

        layout.addWidget(monitor.horizontal_line())
        layout.addWidget(theme.section_label("Other Slot"))
        slot_hint = theme.hint_label("Restarts into the firmware in the device's other slot: "
                                     "Rollback only if it is older, Switch Slot always.")
        slot_hint.setWordWrap(True)
        layout.addWidget(slot_hint)
        slot_row = QHBoxLayout()
        self.rollback_button = QPushButton("Rollback…")
        self.rollback_button.clicked.connect(
            lambda: self.change_slot("Rollback", "Restart the device into the older firmware in "
                                     "its other slot?", self.monitor.client.rollback))
        self.switch_button = QPushButton("Switch Slot…")
        self.switch_button.clicked.connect(
            lambda: self.change_slot("Switch Slot", "Restart the device into the firmware in its "
                                     "other slot, even if it is newer?",
                                     self.monitor.client.switch_slot))
        slot_row.addWidget(self.rollback_button)
        slot_row.addWidget(self.switch_button)
        layout.addLayout(slot_row)
        self.progress.connect(self.show_progress)

    def showEvent(self, event):
        super().showEvent(event)
        if self.future is None:
            self.refresh_slots()

    def refresh_slots(self):
        if not self.monitor.client.connected:
            self.slots_list.clear()
            self.slots_list.addItem("Connect to a device first.")
            return

        def show_slots(lines):
            self.slots_list.clear()
            self.slots_list.addItems(lines or ["No OTA slots."])
            self.monitor.log(f"firmware slots read: {len(lines)}")

        self.monitor.run(self.monitor.client.firmware_slots(), show_slots)

    def browse(self):
        start = self.path_field.text() or str(FIRMWARE_DIRECTORY)
        path, _ = QFileDialog.getOpenFileName(self, "Firmware image", start,
                                              "App images (*.bin);;All files (*)")
        if path:
            self.path_field.setText(path)

    def set_running(self, running):
        for widget in (self.path_field, self.browse_button, self.update_button,
                       self.rollback_button, self.switch_button, self.refresh_button):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def start_update(self):
        path = Path(self.path_field.text().strip())
        if not path.is_file():
            self.status_label.setText("Pick a firmware image first.")
            return
        if not self.monitor.client.connected:
            self.status_label.setText("Connect to a device first.")
            return
        data = path.read_bytes()
        self.monitor.log(f"updating the firmware with {path.name}, {len(data)} bytes")
        self.progress_bar.setRange(0, max(len(data), 1))
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Sending {path.name}…")
        self.start_time = time.monotonic()
        self.set_running(True)

        def installed(_):
            seconds = time.monotonic() - self.start_time
            self.status_label.setText(f"Installed in {seconds:.1f} s; the device restarts into it.")
            self.monitor.log("firmware installed; the device restarts")

        def finished():
            self.future = None
            self.set_running(False)
            if self.progress_bar.value() < self.progress_bar.maximum():
                self.status_label.setText("Stopped or failed: the device shows why, then restarts "
                                          "into its old firmware. See the activity log.")

        self.future = self.monitor.run(self.monitor.client.update_firmware(data, self.progress.emit),
                                       installed, on_finished=finished)

    def show_progress(self, sent, size):
        self.progress_bar.setValue(sent)
        rate = sent / max(time.monotonic() - self.start_time, 1e-3) / 1024
        self.status_label.setText(f"{sent / 1048576:.2f} of {size / 1048576:.2f} MB, "
                                  f"{sent * 100 // max(size, 1)}%, {rate:.1f} KB/s")

    def cancel_update(self):
        if self.future:
            self.future.cancel()

    def change_slot(self, title, question, request):
        if not self.monitor.client.connected:
            self.status_label.setText("Connect to a device first.")
            return
        if QMessageBox.question(self, title, question) != QMessageBox.Yes:
            return

        def changed(_):
            self.status_label.setText(f"{title}: the device restarts.")
            self.monitor.log(f"{title.lower()}: the device restarts")

        self.monitor.run(request(), changed)

    def closeEvent(self, event):
        # Closing stops a running update; the device then restarts into its old firmware.
        self.cancel_update()
        super().closeEvent(event)

    def reject(self):
        if self.future is None:
            super().reject()


class MonitorWindow(QWidget):
    # Carries a finished concurrent Future and its success handler to the Qt thread.
    request_finished = pyqtSignal(object, object)
    device_disconnected = pyqtSignal()
    download_progress = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.client = MokukuIIClient(on_disconnect=self.device_disconnected.emit)
        self.request_finished.connect(self.finish_request)
        self.device_disconnected.connect(lambda: self.set_connected(False))
        self.download_dialog = None
        self.download_progress.connect(self.show_download_progress)
        self.connected_widgets = []
        self.firmware_dialog = FirmwareDialog(self)

        self.setWindowTitle("MOKUKU II Monitor")
        self.setGeometry(300, 300, 620, 980)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 12)
        layout.setSpacing(8)
        self.add_device_section(layout)
        layout.addWidget(self.horizontal_line())
        self.add_info_section(layout)
        layout.addWidget(self.horizontal_line())
        self.add_settings_section(layout)
        layout.addWidget(self.horizontal_line())
        self.add_panels_section(layout)
        layout.addWidget(self.horizontal_line())
        self.add_recordings_section(layout)
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
        self.language_box = QComboBox()
        for code, name in protocol.MULTINET_LANGUAGES.items():
            self.language_box.addItem(name, code)
        self.language_box.setToolTip("Setting a different language restarts the device")
        form.addRow(theme.hint_label("Command language"),
                    self.setting_row(Property.MULTINET_LANGUAGE, self.language_box))
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

    def add_panels_section(self, layout):
        layout.addWidget(theme.section_label(
            f"Panels ({protocol.PANELS_PER_EYE} per eye in next-page order, besides memes)"))
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        self.panel_boxes = []
        for row, eye in enumerate(protocol.EYES):
            grid.addWidget(theme.hint_label(eye.capitalize()), row, 0)
            boxes = []
            for column in range(protocol.PANELS_PER_EYE):
                box = QComboBox()
                for panel in PanelType:
                    box.addItem(protocol.panel_name(panel), panel)
                box.setCurrentIndex(row * protocol.PANELS_PER_EYE + column)  # distinct until Get
                grid.addWidget(box, row, column + 1)
                boxes.append(box)
            self.panel_boxes.append(boxes)
        layout.addLayout(self.setting_row(Property.PANELS, grid_widget))
        row = QHBoxLayout()
        for text, action in (("Left Next", PanelAction.NEXT_LEFT),
                             ("Right Next", PanelAction.NEXT_RIGHT),
                             ("Data / Meme", PanelAction.TOGGLE_MODE)):
            button = QPushButton(text)
            button.clicked.connect(lambda _, action=action: self.panel_action(action))
            row.addWidget(button)
            self.connected_widgets.append(button)
        layout.addLayout(row)

    def panel_action(self, action):
        self.run(self.client.set(Property.PANEL_ACTION, action),
                 lambda reply: self.log(f"{action.name.lower()}: "
                                        f"{protocol.describe_result(reply.result)}"))

    def add_recordings_section(self, layout):
        layout.addWidget(theme.section_label(f"Recordings ({protocol.RECORDING_DIRECTORY})"))
        self.recording_list = QListWidget()
        self.recording_list.setFixedHeight(90)
        self.recording_list.setFont(theme.monospace_font())
        layout.addWidget(self.recording_list)
        row = QHBoxLayout()
        list_button = QPushButton("List")
        list_button.clicked.connect(self.list_recordings)
        download_button = QPushButton("Download")
        download_button.clicked.connect(self.download_recording)
        delete_button = QPushButton("Delete All")
        delete_button.clicked.connect(self.delete_recordings)
        row.addWidget(list_button)
        row.addWidget(download_button)
        row.addWidget(delete_button)
        layout.addLayout(row)
        self.connected_widgets += [list_button, download_button, delete_button]

    def list_recordings(self):
        def show_names(names):
            self.recording_list.clear()
            self.recording_list.addItems(sorted(names))
            self.log(f"{len(names)} recordings")

        self.run(self.client.list_directory(), show_names)

    def delete_recordings(self):
        answer = QMessageBox.question(
            self, "Delete recordings",
            f"Delete every file in {protocol.RECORDING_DIRECTORY}? This cannot be undone.")
        if answer != QMessageBox.Yes:
            return

        def deleted(_):
            self.recording_list.clear()
            self.log("recordings deleted")

        self.run(self.client.delete_recordings(), deleted)

    def download_recording(self):
        item = self.recording_list.currentItem()
        if item is None:
            self.log("list and pick a recording first")
            return
        name = item.text()
        output, _ = QFileDialog.getSaveFileName(
            self, "Save recording", name, options=QFileDialog.DontConfirmOverwrite)
        if not output:
            return
        resume = False
        if Path(output).exists():
            answer = QMessageBox.question(
                self, "Download", f"{Path(output).name} exists. Resume an interrupted download "
                "of it? No downloads it again.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                return
            resume = answer == QMessageBox.Yes
        self.log(f"downloading {name}")
        dialog = QProgressDialog(f"Downloading {name}…", "Cancel", 0, 1, self)
        dialog.setWindowTitle("Download")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumWidth(360)
        dialog.setValue(0)
        dialog.download_name = name
        dialog.start_time = time.monotonic()
        dialog.start_offset = Path(output).stat().st_size if resume else 0
        self.download_dialog = dialog

        def saved(size):
            self.log(f"saved {size} bytes to {output}")

        def close_dialog():
            dialog.close()
            self.download_dialog = None

        future = self.run(self.client.download(f"{protocol.RECORDING_DIRECTORY}/{name}",
                                               Path(output), resume, self.download_progress.emit),
                          saved, on_finished=close_dialog)
        dialog.canceled.connect(future.cancel)

    def show_download_progress(self, received, size):
        dialog = self.download_dialog
        if dialog is None:
            return
        dialog.setMaximum(max(size, 1))
        dialog.setValue(received)
        rate = ((received - dialog.start_offset)
                / max(time.monotonic() - dialog.start_time, 1e-3) / 1024)
        dialog.setLabelText(f"Downloading {dialog.download_name}\n"
                            f"{received / 1024:.1f} of {size / 1024:.1f} KB, {rate:.1f} KB/s")

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
        firmware_button = QPushButton("Firmware…")
        firmware_button.clicked.connect(self.firmware_dialog.show)
        button_row.addWidget(send_button)
        button_row.addWidget(reboot_button)
        button_row.addWidget(firmware_button)
        layout.addLayout(button_row)
        self.connected_widgets += [send_button, reboot_button, firmware_button]

    def log(self, text):
        self.log_view.append(f"{time.strftime('%H:%M:%S')}  {text}")

    def run(self, coroutine, on_success=None, on_finished=None):
        """on_finished runs after success, failure, or cancellation."""
        future = self.client.submit(coroutine)
        future.add_done_callback(
            lambda done: self.request_finished.emit(done, (on_success, on_finished)))
        return future

    def finish_request(self, future, handlers):
        on_success, on_finished = handlers
        if on_finished:
            on_finished()
        if future.cancelled():
            self.log("cancelled")
            return
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
            for property in (*TEXT_SETTING_LABELS, Property.OBD_ENABLED,
                             Property.MULTINET_LANGUAGE, Property.PANELS):
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
                self.log(f"get {protocol.describe_failure(reply)}")
            elif property == Property.OBD_ENABLED:
                self.obd_box.setChecked(reply.value[:1] == b"\x01")
            elif property == Property.MULTINET_LANGUAGE:
                self.language_box.setCurrentIndex(self.language_box.findData(reply.value.decode()))
            elif property == Property.PANELS:
                for boxes, panels in zip(self.panel_boxes, protocol.decode_panels(reply.value)):
                    for box, panel in zip(boxes, panels):
                        box.setCurrentIndex(box.findData(panel))
            else:
                self.setting_fields[property].setText(reply.value.decode("utf-8", "replace"))

        self.run(self.client.get(property), show_setting)

    def set_setting(self, property):
        if property == Property.OBD_ENABLED:
            value = self.obd_box.isChecked()
        elif property == Property.MULTINET_LANGUAGE:
            value = self.language_box.currentData()
        elif property == Property.PANELS:
            value = [[box.currentData() for box in boxes] for boxes in self.panel_boxes]
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
