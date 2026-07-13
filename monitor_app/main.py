#!/usr/bin/env python3
# Copyright 2026 MOKUKU Inc. All rights reserved.
"""Single entry point for the packaged MOKUKU Vibe Monitor.

Both bundled executables are built from this file (see
packaging/vibe_monitor.spec) and dispatch on argv *before* any heavy import:

    <exe>                     -> launch the PyQt5 GUI (imports PyQt5 + bleak)
    <exe> --hook-report ...   -> forward one Claude Code / Codex hook event
                                 (imports only stdlib + the tiny IPC client)

Keeping the hook path off the GUI/BLE imports is what makes it cheap enough
to run on every hook event - Claude Code fires these constantly. The GUI is
a windowed exe (`MOKUKU Vibe Monitor`); the installed hook command points at
the console exe (`mokuku-vibe-hook`, see install_hooks.hook_command) so it can
read the JSON payload piped in on stdin - a windowed exe has no stdin. Either
way the end user never needs a Python interpreter of their own.
"""
import sys


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--hook-report":
        from vibe_monitor import report_status
        return report_status.main(argv[1:])
    from vibe_monitor_app import run_gui
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
