# Copyright 2026 MOKUKU Inc. All rights reserved.

import threading
import time
import psutil
from common.log import logging
import pynvml


class GpuMonitor:
    def __init__(self):
        self.running = False  # Flag to control the thread
        self.thread = None  # Store the thread instance
        self.gpu_usage = 0  # Shared variable to store CPU usage
        self.lock = threading.Lock()  # Protect access to shared variable
        self.tag = "[GPU monitor] "
        self.start_gpu_monitoring()

    def gpu_monitor(self):
        logging.info(self.tag + "thread started.")
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)

        # Run monitoring in a loop while the flag is True
        while self.running:
            # GPU utilization (%)
            usage = pynvml.nvmlDeviceGetUtilizationRates(handle)

            # VRAM usage
            # mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            # print("Memory Used:", mem.used / 1024**2, "MB")
            # print("Memory Total:", mem.total / 1024**2, "MB")
            with self.lock:
                self.gpu_usage = int(usage.gpu)  # store as integer 0-100
            time.sleep(0.5)  # Short delay to reduce CPU load
        logging.info(self.tag + "thread stopped.")

    def start_gpu_monitoring(self):
        if not self.running:
            self.running = True
            # Start the thread with daemon=True (auto-exit when main program ends)
            self.thread = threading.Thread(target=self.gpu_monitor, daemon=True)
            self.thread.start()

    def stop_gpu_monitoring(self):
        if self.running:
            self.running = False
            # Wait for the thread to finish (optional but recommended)
            if self.thread is not None:
                self.thread.join()  # Wait for the loop to exit

    def get_gpu_usage(self):
        result = 0
        with self.lock:
            result = self.gpu_usage
        return result


gpu_monitor_ = None


def start_gpu_monitor():
    global gpu_monitor_
    if gpu_monitor_:
        return
    gpu_monitor_ = GpuMonitor()


def stop_gpu_monitor():
    global gpu_monitor_
    if not gpu_monitor_:
        return
    gpu_monitor_.stop_gpu_monitoring()
    gpu_monitor_ = None


def get_gpu_usage():
    if not gpu_monitor_:
        return 0
    return gpu_monitor_.get_gpu_usage()
