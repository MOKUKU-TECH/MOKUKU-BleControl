"""Manual CLI for testing the MOKUKU vibe-coding monitor without live hooks.
Requires vibe_monitor_app.py to already be running (started manually, see
doc/VIBE_CODING_MONITOR.md) - there's no daemon to lazily launch here.

    python -m vibe_monitor report working --session test1 --project myrepo --tool Edit
    python -m vibe_monitor status
"""
import argparse
import sys

from . import ipc_client
from .protocol import STATE_NAMES

VALID_STATUSES = ("idle", "working", "waiting")


def cmd_report(args):
    ok = ipc_client.send(args.session, project=args.project, status=args.status, tool=args.tool, detail=args.detail,
                         agent=args.agent)
    if not ok:
        print("failed to reach vibe_monitor_app.py - is it running?", file=sys.stderr)
        return 1
    print("sent")
    return 0


def cmd_status(_args):
    summary = ipc_client.query_status()
    if summary is None:
        print("failed to reach vibe_monitor_app.py - is it running?", file=sys.stderr)
        return 1

    print(f"sessions ({len(summary['sessions'])}):")
    for s in summary["sessions"]:
        print(f"  {s['id'][:8]}  [{s.get('agent', 'claude')}] {s['project']:<20} {s['status']}")

    print(f"devices ({len(summary['devices'])}):")
    for d in summary["devices"]:
        print(f"  {d['address']}  {'connected' if d['connected'] else 'disconnected'}")

    state_name = STATE_NAMES.get(summary.get("current_state"), summary.get("current_state"))
    print(f"current state/text sent to MOKUKU: {state_name} / {summary['current_text']!r}")
    return 0


def main():
    parser = argparse.ArgumentParser(prog="vibe_monitor")
    sub = parser.add_subparsers(dest="command", required=True)

    report_p = sub.add_parser("report", help="send one status update as if from a hook")
    report_p.add_argument("status", choices=VALID_STATUSES)
    report_p.add_argument("--session", required=True, help="fake session id for testing")
    report_p.add_argument("--project", default="test-project")
    report_p.add_argument("--tool", default=None)
    report_p.add_argument("--detail", default=None)
    report_p.add_argument("--agent", default="claude", choices=("claude", "codex"))
    report_p.set_defaults(func=cmd_report)

    status_p = sub.add_parser("status", help="query the running app's tracked sessions/devices")
    status_p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
