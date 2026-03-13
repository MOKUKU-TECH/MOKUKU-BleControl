# Copyright 2026 MOKUKU Inc. All rights reserved.

import asyncio
import sys
import time
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
    QTableWidget,
    QTableWidgetItem,
)
from PyQt5.QtCore import Qt, Q_ARG
from PyQt5.QtGui import QIntValidator, QDoubleValidator, QFont

from common.qt_loading_dialog import LoadingDialog, DownloadingDialog
from common.qt_table import create_qt_table
from common.log import logging
from ble_client import BleClient, BleQtWidget
from messager import messager
from common.log import logging

send_realtime_data = True
ble_client_widget = BleQtWidget("mokuku", send_realtime_data)
MOKUKU_CONFIG_FILE_PATH = "/sd/config.txt"


def create_command_table(widget):
    table_data = [
        ["10", "left-right swipe"],
        ["43", "left click"],
        ["53", "right click"],
        ["66", "left ota update"],
        ["67", "right ota update"],
    ]
    table = create_qt_table(["Command", "detail"], table_data, True)
    table.setFixedSize(widget.size().width(), int(widget.size().height() * 0.15))
    return table


class SimpleWindow(QWidget):
    width = 800
    height = 600
    line_height = 30
    subtitle_font = QFont()

    def __init__(self):
        super().__init__()
        self.subtitle_font.setPointSize(12)  # 16pt font
        self.initialize_ui()
        logging.info(" app started")

    def add_horizatal_line(self, main_layout):
        horizontal_line = QFrame()
        horizontal_line.setFrameShape(QFrame.HLine)
        horizontal_line.setFrameShadow(QFrame.Sunken)
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
        self.wifi_button = QPushButton("Set wifi", self)
        self.wifi_button.clicked.connect(self.set_wifi)

        layout_wifi = QHBoxLayout()
        layout_wifi.addWidget(self.wifi_name_input_box)
        layout_wifi.addWidget(self.wifi_pw_input_box)
        layout_wifi.addWidget(self.wifi_button)

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

        self.add_horizatal_line(layout)
        cmd_label = QLabel("Send Command")
        cmd_label.setFont(self.subtitle_font)
        cmd_label.setFixedSize(self.width, self.line_height)
        self.cmd_table = create_command_table(self)
        self.cmd_table.itemClicked.connect(
            self.on_table_item_clicked
        )  # Callback for item clicks
        layout.addWidget(cmd_label)
        layout.addWidget(self.cmd_table)
        layout.addLayout(layout_cmd)

        self.test_button = QPushButton("Test", self)
        self.test_button.clicked.connect(self.test_process)
        layout.addWidget(self.test_button)

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

        self.setLayout(layout)

    def test_process(self):
        messager.push_string_message(60, "/sd/record")
        messager.push_string_message(61, "0")
        messager.push_string_message(3, "0")

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

    def send_command(self):
        if len(self.command_input_box.text()) == 0:
            return
        command = int(self.command_input_box.text().strip())
        messager.push_command(command)

    def on_table_item_clicked(self, item):
        """Triggered when a table item is clicked"""
        # Get details about the clicked item
        col = item.column()  # Column index (0-based)
        cmd_number = self.cmd_table.item(0, col).text()
        self.command_input_box.setText(cmd_number)

    def set_wifi(self):
        wifi_name = self.wifi_name_input_box.text().strip()
        wifi_pw = self.wifi_pw_input_box.text().strip()
        if not wifi_name or not wifi_pw:
            QMessageBox.warning(self, "WARNING", "Please set wifi name and password.")
            return
        # send wifi to command list
        messager.push_wifi_name(wifi_name)
        messager.push_wifi_pw(wifi_pw)
        QMessageBox.information(self, "INFO", f"wifi {wifi_name} {wifi_pw} setup.")

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

    window = SimpleWindow()
    window.show()
    sys.exit(app.exec_())
