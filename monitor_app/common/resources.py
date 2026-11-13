# Copyright 2026 MOKUKU Inc. All rights reserved.

from pathlib import Path
import sys


ASSETS_DIRECTORY = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "assets"
