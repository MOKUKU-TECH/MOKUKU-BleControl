"""Manual CLI for testing the MOKUKU vibe-coding monitor without live hooks.

    python -m vibe_monitor report working --session test1 --project myrepo --tool Edit
    python -m vibe_monitor daemon status
    python -m vibe_monitor daemon stop
"""
import argparse
import sys

from . import daemon, ipc_client

VALID_STATUSES = ("idle", "working", "waiting")


def cmd_report(args):
    ok = ipc_client.send(args.session, project=args.project, status=args.status, tool=args.tool, detail=args.detail)
    if not ok:
        print("failed to reach the daemon", file=sys.stderr)
        return 1
    print("sent")
    return 0


def cmd_daemon(args):
    if args.action == "stop":
        daemon.stop()
        print("daemon stopped")
        return 0

    if not daemon.is_running():
        print("daemon not running")
        return 0

    summary = ipc_client.query_status()
    if summary is None:
        print("daemon running but not responding")
        return 1

    print(f"sessions ({len(summary['sessions'])}):")
    for s in summary["sessions"]:
        print(f"  {s['id'][:8]}  {s['project']:<20} {s['status']}")

    print(f"devices ({len(summary['devices'])}):")
    for d in summary["devices"]:
        print(f"  {d['address']}  {'connected' if d['connected'] else 'disconnected'}")

    print(f"current text sent to MOKUKU: {summary['current_text']!r}")
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
    report_p.set_defaults(func=cmd_report)

    daemon_p = sub.add_parser("daemon", help="inspect or control the background daemon")
    daemon_p.add_argument("action", choices=("status", "stop"))
    daemon_p.set_defaults(func=cmd_daemon)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
