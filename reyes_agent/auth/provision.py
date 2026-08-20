"""Set the ZENO owner password, safely and interactively.

    python -m reyes_agent.auth.provision

The password is read with getpass, so it is never shown on screen, never
placed on the command line (where it would land in shell history and the
process list), never logged, and never written anywhere but the scrypt hash
in the owner database. Provisioning revokes every existing session, so setting
a new password also logs out anything that was signed in with the old one.

This replaces any temporary password used during setup or testing.
"""

from __future__ import annotations

import getpass
import sys

from reyes_agent.auth.owner import get_owner_auth


def main() -> int:
    print("ZENO owner password setup")
    print("-" * 40)
    auth = get_owner_auth()
    if auth.is_provisioned():
        print("An owner is already provisioned. Setting a new password will")
        print("replace it and log out every current session.\n")

    email = input("Owner email: ").strip()
    if "@" not in email:
        print("That does not look like an email address.")
        return 1

    password = getpass.getpass("New password (min 12 chars, hidden): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("The two passwords did not match. Nothing was changed.")
        return 1

    ok, message = auth.provision(email, password)
    # message never contains the password.
    print(("\n" + message) if ok else ("\nRefused: " + message))
    if ok:
        print("Done. Sign in from the web app; a new browser will still need")
        print("approval from this PC before it gets access.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
