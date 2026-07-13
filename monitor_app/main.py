#!/usr/bin/env python3
# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Single entry point for the packaged MOKUKU Vibe Monitor.

The bundled executable does double duty, dispatched on argv *before* any
heavy import:

    <exe>                     -> launch the PyQt5 GUI (imports PyQt5 + bleak)
    <exe> --hook-report ...   -> forward one Claude Code / Codex hook event
                                 (imports only stdlib + the tiny IPC client)

Keeping the hook path off the GUI/BLE imports is what makes it cheap enough
to run on every hook event - Claude Code fires these constantly. The
installed hook command points here (see install_hooks.report_command), so
the end user never needs a Python interpreter of their own.
"""
import sys


def _hook_log_path():
    import os
    from pathlib import Path

    root = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
    path = Path(root) / "MOKUKU Vibe Monitor" / "hook.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _log_hook_exception():
    import traceback

    try:
        with _hook_log_path().open("a", encoding="utf-8") as f:
            f.write("\n=== hook-report crash ===\n")
            f.write("argv: " + repr(sys.argv) + "\n")
            traceback.print_exc(file=f)
    except Exception:
        pass


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--hook-report":
        try:
            from vibe_monitor import report_status
            return report_status.main(argv[1:])
        except Exception:
            _log_hook_exception()
            return 0
    from vibe_monitor_app import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
