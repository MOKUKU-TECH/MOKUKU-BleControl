# Copyright 2026 MOKUKU Inc. All rights reserved.

import struct
import threading
from collections import deque
from common.log import logging


class MokukuMessager:
    def __init__(self):
        self.ack_message_lock = threading.Lock()
        self.ack_message_queue = deque()
        self.ack_message_wakeup = None
        # self.command_lock = threading.Lock()
        # self.command_queue = deque()
        self.tag = "[messager]"

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
            self.ack_message_queue.append(bytes(message))
            wakeup = self.ack_message_wakeup
        if wakeup:
            wakeup()

    def set_ack_message_wakeup(self, wakeup):
        with self.ack_message_lock:
            self.ack_message_wakeup = wakeup
            has_messages = bool(self.ack_message_queue)
        if wakeup and has_messages:
            wakeup()

    def wake_ack_sender(self):
        with self.ack_message_lock:
            wakeup = self.ack_message_wakeup
        if wakeup:
            wakeup()

    def discard_file_read_requests(self):
        with self.ack_message_lock:
            self.ack_message_queue = deque(
                message for message in self.ack_message_queue if message[0] != 66
            )

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

    def push_reboot(self):
        # id=6 on the ack characteristic triggers esp_restart() immediately.
        # Note: this is NOT the same as command byte 6 (push_command(6)),
        # which is a different, unrelated code path.
        self.push_ack_message(list(struct.pack("<B", 6)))

    """
    Meme enable/disable (idle, meme id 0, can never be disabled - device ignores it):
    | 1          | 2     | 3 - N              |
    |------------|-------|--------------------|
    | 54 (enable) / 55 (disable) | count | meme id (1 byte) x count |
    """

    def push_meme_toggle(self, meme_ids, disabled):
        message_id = 55 if disabled else 54
        byte_data = []
        byte_data.extend(struct.pack("<B", message_id))
        byte_data.extend(struct.pack("<B", len(meme_ids)))
        for meme_id in meme_ids:
            byte_data.extend(struct.pack("<B", meme_id))
        self.push_ack_message(byte_data)

    def push_meme_states_request(self):
        self.push_ack_message([56])

    def push_himokuku_wakeword_model_request(self):
        self.push_ack_message([57])

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
