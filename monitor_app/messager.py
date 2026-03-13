# Copyright 2026 MOKUKU Inc. All rights reserved.

import asyncio
import struct
import threading
import time
from collections import deque
from common.log import logging
from cpu_monitor import get_cpu_usage, start_cpu_monitor
from gpu_monitor import get_gpu_usage, start_gpu_monitor


def get_current_time_ms():
    # Current time in seconds as float
    unix_time = time.time()
    t = time.localtime(unix_time)
    seconds_since_midnight = t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec
    return seconds_since_midnight


class MokukuMessager:
    def __init__(self):
        self.ack_message_lock = threading.Lock()
        self.ack_message_queue = deque()
        # self.command_lock = threading.Lock()
        # self.command_queue = deque()
        self.tag = "[messager]"
        start_cpu_monitor()
        start_gpu_monitor()

    # data format is
    # | 1 |  2  |  3   |   4  |  5  |     6       |     7       |      8      |     9       |     10    |   11    |
    # |---|-----|------|------|-----|-------------|-------------|-------------|-------------|-----------|---------|
    # | 1 | VEL | RPM_A| RPM_B| GAS | TIMESTAMP_1 | TIMESTAMP_2 | TIMESTAMP_3 | TIMESTAMP_4 | BACKLIGHT | COMMAND |
    def get_message_to_send(self):
        cpu_usage = get_cpu_usage()

        byte_data = []
        byte_data.extend(struct.pack("<B", 1))  # first byte for message type ID
        byte_data.extend(struct.pack("<B", cpu_usage))

        # rpm_ = ((rpm_A * 256) + rpm_B) / 4;
        rpm = get_gpu_usage()
        rpm_A = int(rpm * 4 / 256)
        rpm_B = int(rpm * 4 - rpm_A * 256)
        byte_data.extend(struct.pack("<B", rpm_A))
        byte_data.extend(struct.pack("<B", rpm_B))
        byte_data.extend(struct.pack("<B", 25))  # gas

        t_sec = get_current_time_ms()
        byte_data.extend(struct.pack("<I", t_sec))

        # set up backlight
        byte_data.extend(struct.pack("<B", 90))

        # for command (not used anymore)
        byte_data.extend(struct.pack("<B", 0))
        return byte_data

    def pop_ack_message_to_send(self):
        with self.ack_message_lock:
            if len(self.ack_message_queue) > 0:
                command = self.ack_message_queue.popleft()
                return command
        return None

    def push_command(self, command):
        logging.info(f"{self.tag} add command {command}")
        byte_data = []
        byte_data.extend(struct.pack("<B", 1))
        byte_data.extend(struct.pack("<B", command))
        self.push_ack_message(byte_data)

    def push_ack_message(self, message):
        # logging.info(f"{self.tag} add message {message}")
        with self.ack_message_lock:
            # push message to the queue
            self.ack_message_queue.append(message)

    """
    1. Wifi Name :
    | 1 | 2 | 3 - N |
    |---|---|-------|
    | 7 | string length | string |
    2. Wifi Password :
    | 1 | 2 | 3 - N |
    |---|---|-------|
    | 8 | string length | string |
    """

    def push_wifi_name(self, wifi_name):
        self.push_string_message(7, wifi_name)

    def push_wifi_pw(self, wifi_pw):
        self.push_string_message(8, wifi_pw)

    def push_string_message(self, id, message):
        str_bytes = message.encode("utf-8")
        if len(str_bytes) > 255:
            logging.error(f"too long message {message}")
            return
        byte_data = []
        byte_data.extend(struct.pack("<B", id))  # first byte for message type ID
        byte_data.extend(struct.pack("<B", len(str_bytes)))
        byte_data.extend(str_bytes)
        self.push_ack_message(byte_data)


messager = MokukuMessager()
messager.push_string_message(44, "mobili0731")
