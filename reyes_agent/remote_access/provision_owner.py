"""Provision (or re-provision) the single owner credential.

Run on the DEPLOYED gateway, over an authenticated Fly SSH session:

    fly ssh console -a <app> -C "python -m reyes_agent.remote_access.provision_owner"

or non-interactively, reading from the environment (useful in CI):

    ZENO_OWNER_EMAIL=... ZENO_OWNER_PASSWORD=... \\
        python -m reyes_agent.remote_access.provision_owner --from-env

WHY THIS IS A SEPARATE ENTRY POINT
----------------------------------
Provisioning sets the owner password without knowing the old one, which is
only safe on a machine that already has full authority -- the deployed
gateway reached through Fly's authenticated SSH, or the desktop. There is
deliberately no HTTP route that does this, so it can never be reached from
the internet.

The password is read with getpass (no echo) or from the environment; it is
never taken from a command-line argument, because arguments show up in the
process list and shell history.
"""

from __future__ import annotations

import getpass
import os
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from_env = "--from-env" in argv

    from reyes_agent.auth import get_owner_auth

    auth = get_owner_auth()
    if auth.is_provisioned() and "--force" not in argv:
        print("An owner is already provisioned.")
        print("Re-provisioning changes the password and revokes every session.")
        print("Pass --force if that is what you intend.")
        return 1

    if from_env:
        email = os.environ.get("ZENO_OWNER_EMAIL", "").strip()
        password = os.environ.get("ZENO_OWNER_PASSWORD", "")
        if not email or not password:
            print("--from-env needs ZENO_OWNER_EMAIL and ZENO_OWNER_PASSWORD set.")
            return 2
    else:
        email = input("Owner email: ").strip()
        password = getpass.getpass("Owner password (min 12 chars, hidden): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords did not match.")
            return 2

    ok, message = auth.provision(email, password)
    print(message)
    if ok:
        # Never echo the password back, and clear the env copy if it was used.
        os.environ.pop("ZENO_OWNER_PASSWORD", None)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
