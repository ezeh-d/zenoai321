"""Local administration for ZENO Anywhere.

This is intentionally a desktop/operator command, not a public setup route.
It is the trusted bootstrap for the first owner and first browser approval.
Passwords are read with getpass and never accepted as command-line arguments,
where they would be exposed in shell history and process listings.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

# Support the documented ``python tools/zeno_anywhere_admin.py`` invocation
# without requiring the repository to be installed as a package first.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reyes_agent.auth import get_owner_auth
from reyes_agent.remote_access.device_link import get_link


def _print(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administer ZENO Anywhere locally")
    sub = parser.add_subparsers(dest="command", required=True)

    provision = sub.add_parser("provision-owner", help="create the single owner")
    provision.add_argument("--email", required=True)

    sub.add_parser("status")
    sub.add_parser("list-browsers")
    approve_browser = sub.add_parser("approve-browser")
    approve_browser.add_argument("device_id")
    block_browser = sub.add_parser("block-browser")
    block_browser.add_argument("device_id")

    sub.add_parser("list-devices")
    register_device = sub.add_parser("register-device")
    register_device.add_argument("--label", default="Main Windows laptop")
    register_device.add_argument("--platform", default="windows")
    approve_device = sub.add_parser("approve-device")
    approve_device.add_argument("device_id")
    revoke_device = sub.add_parser("revoke-device")
    revoke_device.add_argument("device_id")

    args = parser.parse_args(argv)
    auth, link = get_owner_auth(), get_link()

    if args.command == "provision-owner":
        first = getpass.getpass("New owner password: ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            print("Passwords do not match.", file=sys.stderr)
            return 2
        ok, reason = auth.provision(args.email, first)
        _print({"ok": ok, "reason": reason})
        return 0 if ok else 1
    if args.command == "status":
        _print({"auth": auth.status(), "queue": link.stats()})
    elif args.command == "list-browsers":
        _print({"browser_devices": auth.browser_devices()})
    elif args.command == "approve-browser":
        _print({"ok": auth.approve_browser_device(args.device_id)})
    elif args.command == "block-browser":
        _print({"ok": auth.set_browser_device_state(args.device_id, "BLOCKED")})
    elif args.command == "list-devices":
        _print({"devices": link.devices()})
    elif args.command == "register-device":
        _print(link.register(label=args.label, platform=args.platform))
    elif args.command == "approve-device":
        _print({"ok": link.approve_device(args.device_id)})
    elif args.command == "revoke-device":
        _print({"ok": link.revoke_device(args.device_id)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
