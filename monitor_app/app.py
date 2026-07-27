# Copyright 2025 MOKUKU Inc. All rights reserved.

import asyncio
import sys
import time
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QFrame,
    QMessageBox,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
)
from PyQt5.QtCore import Qt, Q_ARG, QMetaObject, pyqtSignal
from PyQt5.QtGui import QIntValidator, QDoubleValidator

import theme
from common.qt_loading_dialog import LoadingDialog, DownloadingDialog
from common.qt_table import create_qt_table
from common.log import logging
from ble_client import BleClient, BleQtWidget
from messager import messager
from common.log import logging

send_realtime_data = False
ble_client_widget = BleQtWidget("mokuku", send_realtime_data)
MOKUKU_CONFIG_FILE_PATH = "/sd/config.txt"
MEME_METADATA_PATH = Path(__file__).resolve().parent.parent / "assets" / "meta"
APP_TAG_NAMES = {
    0: "Daily",
    1: "Scene",
    2: "Drive",
    3: "Mood",
    4: "Play",
    5: "不可编辑",
}


def create_command_table(widget):
    table_data = [
        ["6", "reboot"],
        ["10", "left-right swipe"],
        ["43", "left click"],
        ["53", "right click"],
        ["66", "left ota update"],
        ["67", "right ota update"],
        ["68", "left meme update"],
        ["69", "right meme update"],
    ]
    table = create_qt_table(["Command", "detail"], table_data, True)
    table.setStyleSheet(
        "QTableWidget { background-color: #000000; }"
        "QTableWidget::item { background-color: #000000; }"
        "QTableWidget::item:selected { background-color: rgba(5, 207, 120, 0.18); }"
    )
    table.setSelectionBehavior(QAbstractItemView.SelectColumns)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setFixedSize(widget.size().width(), int(widget.size().height() * 0.15))
    return table


def load_meme_metadata():
    memes = []
    with MEME_METADATA_PATH.open(encoding="utf-8") as metadata_file:
        for line in metadata_file:
            fields = line.split()
            if len(fields) < 2:
                continue
            memes.append((int(fields[0]), int(fields[1]), fields[2] if len(fields) > 2 else ""))
    return memes


class MemeTestPanel(QDialog):
    meme_states_received = pyqtSignal(dict)

    def __init__(self, ble_client, parent=None):
        super().__init__(parent)
        self.ble_client = ble_client
        self.memes_by_tag = {tag_id: [] for tag_id in APP_TAG_NAMES}
        for meme_id, tag_id, meme_name in load_meme_metadata():
            if tag_id in self.memes_by_tag:
                self.memes_by_tag[tag_id].append((meme_id, meme_name))
        self.meme_enabled_boxes = {}
        self.tag_enabled_boxes = {}
        self.meme_states_received.connect(self.set_meme_states)

        self.setWindowTitle("MOKUKU Meme Test")
        self.resize(700, 600)
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Requesting meme states…", self)
        layout.addWidget(self.status_label)
        tabs = QTabWidget(self)
        for tag_id, tag_name in APP_TAG_NAMES.items():
            tabs.addTab(self.create_tag_table(tag_id), tag_name)
        layout.addWidget(tabs)

        self.ble_client.request_meme_states(self.meme_states_received.emit)

    def create_tag_table(self, tag_id):
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        memes = self.memes_by_tag[tag_id]
        if tag_id != 5:
            tag_enabled_box = QCheckBox(f"Enable all {APP_TAG_NAMES[tag_id]} memes", widget)
            tag_enabled_box.clicked.connect(
                lambda enabled, current_tag_id=tag_id: self.toggle_tag(current_tag_id, enabled)
            )
            tag_enabled_box.setEnabled(False)
            self.tag_enabled_boxes[tag_id] = tag_enabled_box
            layout.addWidget(tag_enabled_box)

        table = QTableWidget(len(memes), 4, widget)
        table.setHorizontalHeaderLabels(["ID", "App tag", "Name", "Enabled"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setStyleSheet(
            "QTableWidget { background-color: #000000; }"
            "QTableWidget::item { background-color: #000000; }"
        )
        for row, (meme_id, meme_name) in enumerate(memes):
            table.setItem(row, 0, QTableWidgetItem(str(meme_id)))
            table.setItem(row, 1, QTableWidgetItem(APP_TAG_NAMES[tag_id]))
            table.setItem(row, 2, QTableWidgetItem(meme_name))
            enabled_box = QCheckBox(table)
            if tag_id == 5:
                enabled_box.setText("Cannot edit")
                enabled_box.setEnabled(False)
            else:
                enabled_box.setEnabled(False)
                enabled_box.stateChanged.connect(
                    lambda state, current_meme_id=meme_id, current_tag_id=tag_id: self.toggle_meme(
                        current_meme_id, current_tag_id, state
                    )
                )
            self.meme_enabled_boxes[meme_id] = enabled_box
            table.setCellWidget(row, 3, enabled_box)
        layout.addWidget(table)
        return widget

    def set_meme_states(self, meme_states):
        for meme_id, enabled_box in self.meme_enabled_boxes.items():
            enabled_box.blockSignals(True)
            if meme_id not in meme_states:
                enabled_box.setChecked(False)
                enabled_box.setEnabled(False)
                enabled_box.setText("Unavailable")
            elif meme_id != 0 and enabled_box.text() != "Cannot edit":
                enabled_box.setEnabled(True)
                enabled_box.setChecked(not meme_states[meme_id])
            enabled_box.blockSignals(False)
        for tag_id in self.tag_enabled_boxes:
            self.update_tag_state(tag_id)
        self.status_label.setText(f"Loaded states for {len(meme_states)} memes")

    def toggle_meme(self, meme_id, tag_id, state):
        enabled = state == Qt.Checked
        messager.push_meme_toggle([meme_id], disabled=not enabled)
        self.update_tag_state(tag_id)

    def toggle_tag(self, tag_id, enabled):
        meme_ids = [
            meme_id
            for meme_id, _ in self.memes_by_tag[tag_id]
            if self.meme_enabled_boxes[meme_id].isEnabled()
        ]
        if not meme_ids:
            return
        messager.push_meme_toggle(meme_ids, disabled=not enabled)
        for meme_id in meme_ids:
            enabled_box = self.meme_enabled_boxes[meme_id]
            enabled_box.blockSignals(True)
            enabled_box.setChecked(enabled)
            enabled_box.blockSignals(False)
        self.update_tag_state(tag_id)

    def update_tag_state(self, tag_id):
        enabled_boxes = [
            self.meme_enabled_boxes[meme_id]
            for meme_id, _ in self.memes_by_tag[tag_id]
            if self.meme_enabled_boxes[meme_id].isEnabled()
        ]
        enabled_count = sum(enabled_box.isChecked() for enabled_box in enabled_boxes)
        tag_enabled_box = self.tag_enabled_boxes[tag_id]
        tag_enabled_box.blockSignals(True)
        tag_enabled_box.setEnabled(bool(enabled_boxes))
        if not enabled_boxes:
            tag_enabled_box.setCheckState(Qt.Unchecked)
        elif enabled_count == len(enabled_boxes):
            tag_enabled_box.setCheckState(Qt.Checked)
        else:
            tag_enabled_box.setCheckState(Qt.Unchecked)
        tag_enabled_box.blockSignals(False)


class SimpleWindow(QWidget):
    width = 800
    height = 600
    line_height = 30

    def __init__(self):
        super().__init__()
        self.initialize_ui()
        logging.info(" app started")

    def add_horizatal_line(self, main_layout):
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setFixedHeight(1)
        horizontal_line.setStyleSheet(f"background: {theme.BORDER}; border: none;")
        main_layout.addSpacing(self.line_height)
        main_layout.addWidget(horizontal_line)

    def initialize_ui(self):
        self.setWindowTitle("MOKUKU CONTROL APP")
        self.setGeometry(300, 300, self.width, self.height)  # (x, y, width, height)

        # ble interface
        self.message_label = QLabel("program information", self)
        ble_widget_elements = ble_client_widget.init_wedgets(self, self.message_label)

        # wifi interface
        self.wifi_name_input_box = QLineEdit(self)
        self.wifi_name_input_box.setText("DEEP-RD")
        self.wifi_pw_input_box = QLineEdit(self)
        self.wifi_pw_input_box.setText("07310731")

        self.leftpanels_input_box = QLineEdit(self)
        self.leftpanels_input_box.setText("1-2-3-4-5")
        self.rightpanels_input_box = QLineEdit(self)
        self.rightpanels_input_box.setText("6-7-8-9-10")
        self.wifi_button = QPushButton("Set wifi", self)
        self.wifi_button.clicked.connect(self.set_wifi)

        layout_wifi = QHBoxLayout()
        layout_wifi.addWidget(self.wifi_name_input_box)
        layout_wifi.addWidget(self.wifi_pw_input_box)
        layout_wifi.addWidget(self.leftpanels_input_box)
        layout_wifi.addWidget(self.rightpanels_input_box)
        layout_wifi.addWidget(self.wifi_button)

        self.start_monitors_button = QPushButton("Start CPU/GPU Monitors", self)
        self.start_monitors_button.clicked.connect(self.start_monitors)
        self.enable_obd_ble_scan_button = QPushButton("Enable OBD BLE Scan", self)
        self.enable_obd_ble_scan_button.clicked.connect(
            lambda: self.send_device_command(34, "Enabled OBD BLE scan")
        )
        self.disable_obd_ble_scan_button = QPushButton("Disable OBD BLE Scan", self)
        self.disable_obd_ble_scan_button.clicked.connect(
            lambda: self.send_device_command(35, "Disabled OBD BLE scan")
        )
        self.start_meme_list_button = QPushButton("Start Meme List Playback", self)
        self.start_meme_list_button.clicked.connect(
            lambda: self.send_device_command(22, "Started meme list playback")
        )
        self.stop_meme_list_button = QPushButton("Stop Meme List Playback", self)
        self.stop_meme_list_button.clicked.connect(
            lambda: self.send_device_command(23, "Stopped meme list playback")
        )

        # command layout
        self.command_input_box = QLineEdit(self)
        # Restrict to integers between 1 and 100
        int_validator = QIntValidator(0, 255, self)  # (min, max, parent)
        self.command_input_box.setValidator(int_validator)
        self.command_button = QPushButton("Send Command", self)
        self.command_button.clicked.connect(self.send_command)
        layout_cmd = QHBoxLayout()
        layout_cmd.addWidget(self.command_input_box)
        layout_cmd.addWidget(self.command_button)

        layout = QVBoxLayout()
        layout.addWidget(self.message_label)

        self.add_horizatal_line(layout)
        for ele in ble_widget_elements:
            layout.addWidget(ele)
        layout.addLayout(layout_wifi)
        layout.addWidget(self.start_monitors_button)
        device_control_layout = QHBoxLayout()
        device_control_layout.addWidget(self.enable_obd_ble_scan_button)
        device_control_layout.addWidget(self.disable_obd_ble_scan_button)
        device_control_layout.addWidget(self.start_meme_list_button)
        device_control_layout.addWidget(self.stop_meme_list_button)
        layout.addLayout(device_control_layout)

        self.add_horizatal_line(layout)
        cmd_label = theme.section_label("Send Command")
        cmd_label.setFixedSize(self.width, self.line_height)
        self.cmd_table = create_command_table(self)
        self.cmd_table.itemClicked.connect(
            self.on_table_item_clicked
        )  # Callback for item clicks
        layout.addWidget(cmd_label)
        layout.addWidget(self.cmd_table)
        layout.addLayout(layout_cmd)

        test_label = theme.section_label("Info Queries")
        test_label.setFixedSize(self.width, self.line_height)
        layout.addWidget(test_label)

        self.list_directory_button = QPushButton("List /sd/record", self)
        self.list_directory_button.clicked.connect(self.test_list_directory)
        self.sd_info_button = QPushButton("SD Card Info", self)
        self.sd_info_button.clicked.connect(self.test_sd_info)
        self.firmware_version_button = QPushButton("Firmware Version", self)
        self.firmware_version_button.clicked.connect(self.test_firmware_version)
        self.mac_address_button = QPushButton("MAC Address", self)
        self.mac_address_button.clicked.connect(self.test_mac_address)
        self.meme_version_button = QPushButton("Meme Version", self)
        self.meme_version_button.clicked.connect(self.test_meme_version)
        layout_test = QHBoxLayout()
        layout_test.addWidget(self.list_directory_button)
        layout_test.addWidget(self.sd_info_button)
        layout_test.addWidget(self.firmware_version_button)
        layout_test.addWidget(self.mac_address_button)
        layout_test.addWidget(self.meme_version_button)
        layout.addLayout(layout_test)

        # command layout
        self.download_input_box = QLineEdit(self)
        self.download_input_box.setText("/sd/record")
        self.download_button = QPushButton("Download File", self)
        self.download_button.clicked.connect(self.start_downloading_file)
        layout_download = QHBoxLayout()
        layout_download.addWidget(self.download_input_box)
        layout_download.addWidget(self.download_button)
        layout.addLayout(layout_download)

        self.upload_button = QPushButton("Upload File", self)
        self.upload_button.clicked.connect(self.start_uploading_file)
        layout.addWidget(self.upload_button)

        self.add_horizatal_line(layout)
        meme_label = theme.section_label("Meme Enable/Disable (idle, id 0, can never be disabled)")
        meme_label.setFixedSize(self.width, self.line_height)
        layout.addWidget(meme_label)

        self.meme_ids_input_box = QLineEdit(self)
        self.meme_ids_input_box.setPlaceholderText("meme ids, comma separated e.g. 4,5,10")
        self.meme_enable_button = QPushButton("Enable Memes", self)
        self.meme_enable_button.clicked.connect(lambda: self.toggle_memes(False))
        self.meme_disable_button = QPushButton("Disable Memes", self)
        self.meme_disable_button.clicked.connect(lambda: self.toggle_memes(True))
        self.meme_states_button = QPushButton("Get Meme States", self)
        self.meme_states_button.clicked.connect(self.get_meme_states)
        layout_meme = QHBoxLayout()
        layout_meme.addWidget(self.meme_ids_input_box)
        layout_meme.addWidget(self.meme_enable_button)
        layout_meme.addWidget(self.meme_disable_button)
        layout_meme.addWidget(self.meme_states_button)
        layout.addLayout(layout_meme)
        self.meme_states_label = QLabel("Meme states: not requested", self)
        layout.addWidget(self.meme_states_label)
        self.meme_test_button = QPushButton("Open Meme Test Panel", self)
        self.meme_test_button.clicked.connect(self.open_meme_test_panel)
        layout.addWidget(self.meme_test_button)

        self.setLayout(layout)

    def test_list_directory(self):
        messager.push_string_message(60, "/sd/record")

    def test_sd_info(self):
        messager.push_string_message(61, "0")

    def test_firmware_version(self):
        messager.push_string_message(3, "0")

    def test_mac_address(self):
        messager.push_string_message(4, "0")

    def test_meme_version(self):
        messager.push_string_message(5, "0")

    def download_complete_callback(self):
        if self.downloading_dialog:
            self.downloading_dialog.close()
        self.download_button.setEnabled(True)  # Re-enable button

    def start_downloading_file(self):
        if len(self.download_input_box.text()) == 0:
            return
        download_file = self.download_input_box.text().strip()
        logging.info("start to download " + download_file)

        if not ble_client_widget.ble_client.connected:
            return
        # 1. Create and show custom loading dialog
        self.downloading_dialog = DownloadingDialog(self, title="Downloading")
        self.downloading_dialog.file_transfer = ble_client_widget.ble_client.remote_file
        self.downloading_dialog.show()
        # 2. Disable UI elements during scan
        self.download_button.setEnabled(False)

        # 3. Run scan asynchronously (non-blocking)
        messager.push_string_message(65, download_file)
        ble_client_widget.ble_client.remote_file.complete_callback = (
            self.download_complete_callback
        )

    def upload_complete_callback(self):
        if self.uploading_dialog:
            self.uploading_dialog.close()
        self.upload_button.setEnabled(True)  # Re-enable button

    def start_uploading_file(self):
        if not ble_client_widget.ble_client.connected:
            return
        # 1. Create and show custom loading dialog
        self.uploading_dialog = DownloadingDialog(self, title="Uploading")
        self.uploading_dialog.file_transfer = ble_client_widget.ble_client.local_file
        self.uploading_dialog.show()
        # 2. Disable UI elements during scan
        self.upload_button.setEnabled(False)

        messager.push_string_message(63, MOKUKU_CONFIG_FILE_PATH)
        ble_client_widget.ble_client.local_file.complete_callback = (
            self.upload_complete_callback
        )

    def start_monitors(self):
        messager.start_monitors()
        self.start_monitors_button.setEnabled(False)
        self.start_monitors_button.setText("CPU/GPU Monitors Running")

    def send_command(self):
        if len(self.command_input_box.text()) == 0:
            return
        command = int(self.command_input_box.text().strip())
        messager.push_command(command)

    def send_device_command(self, command, status):
        messager.push_command(command)
        self.message_label.setText(status)

    def on_table_item_clicked(self, item):
        column = item.column()
        command_item = self.cmd_table.item(0, column)
        detail_item = self.cmd_table.item(1, column)
        if command_item is None:
            return

        self.cmd_table.selectColumn(column)
        self.command_input_box.setText(command_item.text())
        self.message_label.setText(
            f"Selected command {command_item.text()}: {detail_item.text() if detail_item else ''}"
        )

    def set_wifi(self):
        wifi_name = self.wifi_name_input_box.text().strip()
        wifi_pw = self.wifi_pw_input_box.text().strip()
        if not wifi_name or not wifi_pw:
            QMessageBox.warning(self, "WARNING", "Please set wifi name and password.")
            return
        # send wifi to command list
        messager.push_wifi_name(wifi_name)
        messager.push_wifi_pw(wifi_pw)

        panels_left = self.leftpanels_input_box.text().strip()
        panels_right = self.rightpanels_input_box.text().strip()
        messager.push_string_message(50, panels_left)
        messager.push_string_message(51, panels_right)
        QMessageBox.information(self, "INFO", f"wifi {wifi_name} {wifi_pw} setup.")

    def toggle_memes(self, disabled):
        if not ble_client_widget.ble_client.connected:
            QMessageBox.warning(self, "WARNING", "Connect to MOKUKU over BLE first.")
            return
        text = self.meme_ids_input_box.text().strip()
        if not text:
            QMessageBox.warning(self, "WARNING", "Enter meme ids, comma separated.")
            return
        try:
            meme_ids = [int(part.strip()) for part in text.split(",") if part.strip()]
        except ValueError:
            QMessageBox.warning(self, "WARNING", f"Invalid meme id list: {text}")
            return
        if any(meme_id < 0 or meme_id > 255 for meme_id in meme_ids):
            QMessageBox.warning(self, "WARNING", "Meme ids must be between 0 and 255.")
            return
        messager.push_meme_toggle(meme_ids, disabled)
        QMessageBox.information(
            self, "INFO", f"{'Disabled' if disabled else 'Enabled'} memes: {meme_ids}"
        )

    def get_meme_states(self):
        if not ble_client_widget.ble_client.connected:
            QMessageBox.warning(self, "WARNING", "Connect to MOKUKU over BLE first.")
            return
        self.meme_states_label.setText("Meme states: requesting...")
        ble_client_widget.ble_client.request_meme_states(self.display_meme_states)

    def open_meme_test_panel(self):
        if not ble_client_widget.ble_client.connected:
            QMessageBox.warning(self, "WARNING", "Connect to MOKUKU over BLE first.")
            return
        self.meme_test_panel = MemeTestPanel(ble_client_widget.ble_client, self)
        self.meme_test_panel.show()

    def display_meme_states(self, meme_states):
        disabled_ids = [str(meme_id) for meme_id, disabled in meme_states.items() if disabled]
        text = f"Meme states: {len(meme_states) - len(disabled_ids)} enabled, {len(disabled_ids)} disabled"
        if disabled_ids:
            text += f" ({', '.join(disabled_ids)})"
        QMetaObject.invokeMethod(
            self.meme_states_label, "setText", Qt.QueuedConnection, Q_ARG(str, text)
        )

    # Override closeEvent to add custom logic
    def closeEvent(self, event):
        # Show a confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Quit",
            "Are you sure you want to quit?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,  # Default button
        )
        if reply == QMessageBox.Yes:
            # fully stop the ble client before quit
            ble_client_widget.ble_client.stop_client()
            while ble_client_widget.ble_client.running:
                time.sleep(0.1)
            event.accept()  # Allow the widget to close
        else:
            event.ignore()  # Cancel the close operation


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.APP_STYLESHEET)

    window = SimpleWindow()
    window.show()
    sys.exit(app.exec_())
