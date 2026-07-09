# Copyright 2025 Mobili Inc. All rights reserved.

import logging
import logging.config
import os
import sys
from pathlib import Path

"""Logging configuration"""


def _log_dir() -> Path:
    """A user-writable directory for the log files. The packaged app can be
    launched from a read-only location (Program Files, an extracted release
    folder), so writing info.log/error.log into the current directory - as
    this module used to - can make dictConfig() raise at import time and stop
    the app from starting at all."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or Path.home()
    else:
        base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    path = Path(base) / "mokuku-vibe-monitor"
    path.mkdir(parents=True, exist_ok=True)
    return path


_LOG_DIR = _log_dir()

LOGGING_CONFIG = {
    "version": 1,
    "loggers": {
        "": {  # root logger
            "level": "NOTSET",
            "handlers": [
                "debug_console_handler",
                "info_rotating_file_handler",
                "error_file_handler",
            ],
        },
        "my.package": {
            "level": "WARNING",
            "propagate": False,
            "handlers": ["info_rotating_file_handler", "error_file_handler"],
        },
    },
    "handlers": {
        "debug_console_handler": {
            "level": "DEBUG",
            "formatter": "colored_console",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
        "info_rotating_file_handler": {
            "level": "INFO",
            "formatter": "info",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(_LOG_DIR / "info.log"),
            "mode": "a",
            "maxBytes": 1048576,
            "backupCount": 10,
        },
        "error_file_handler": {
            "level": "WARNING",
            "formatter": "error",
            "class": "logging.FileHandler",
            "filename": str(_LOG_DIR / "error.log"),
            "mode": "a",
        },
    },
    "formatters": {
        "colored_console": {
            "()": "coloredlogs.ColoredFormatter",
            "format": "%(asctime)s - %(levelname)s [%(process)s - %(filename)s:%(lineno)d] %(message)s",
            "datefmt": "%H:%M:%S",
        },
        "format_for_file": {
            "format": "%(asctime)s - %(levelname)s [%(process)s - %(filename)s:%(lineno)d] %(message)s",
            "datefmt": "%H:%M:%S",
        },
        "info": {
            "format": "%(asctime)s-%(levelname)s-%(name)s::%(module)s|%(lineno)s:: %(message)s"
        },
        "error": {
            "format": "%(asctime)s-%(levelname)s-%(name)s-%(process)d::%(module)s|%(lineno)s:: %(message)s"
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
