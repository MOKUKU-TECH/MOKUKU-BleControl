# Copyright 2026 MOKUKU Inc. All rights reserved.

import threading
import time
import psutil
from common.log import logging


class CpuMonitor:
    def __init__(self):
        self.running = False  # Flag to control the thread
        self.thread = None  # Store the thread instance
        self.cpu_usage = 0  # Shared variable to store CPU usage
        self.lock = threading.Lock()  # Protect access to shared variable
        self.tag = "[CPU monitor] "
        self.start_cpu_monitoring()

    def cpu_monitor(self):
        logging.info(self.tag + "thread started.")
        # Run monitoring in a loop while the flag is True
        while self.running:
            # Example: Get CPU usage (replace with your logic)
            usage = psutil.cpu_percent(interval=0.5)
            with self.lock:
                self.cpu_usage = int(usage)  # store as integer 0-100
            time.sleep(0.5)  # Short delay to reduce CPU load
        logging.info(self.tag + "thread stopped.")

    def start_cpu_monitoring(self):
        if not self.running:
            self.running = True
            # Start the thread with daemon=True (auto-exit when main program ends)
            self.thread = threading.Thread(target=self.cpu_monitor, daemon=True)
            self.thread.start()

    def stop_cpu_monitoring(self):
        if self.running:
            self.running = False
            # Wait for the thread to finish (optional but recommended)
            if self.thread is not None:
                self.thread.join()  # Wait for the loop to exit

    def get_cpu_usage(self):
        result = 0
        with self.lock:
            result = self.cpu_usage
        return result


cpu_monitor_ = None


def start_cpu_monitor():
    global cpu_monitor_
    if cpu_monitor_:
        return
    cpu_monitor_ = CpuMonitor()


def stop_cpu_monitor():
    global cpu_monitor_
    if not cpu_monitor_:
        return
    cpu_monitor_.stop_cpu_monitoring()
    cpu_monitor_ = None


def get_cpu_usage():
    if not cpu_monitor_:
        return 0
    return cpu_monitor_.get_cpu_usage()
