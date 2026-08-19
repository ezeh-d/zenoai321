"""Generate VAPID keys for Web Push, straight into .env.

WHY THIS SCRIPT EXISTS RATHER THAN A ONE-LINER
----------------------------------------------
The private key is a real secret. A one-liner prints it to the terminal, into
scrollback, and into whatever is recording the session -- so this writes it to
.env (which .gitignore already blocks) and prints only the PUBLIC key.

VAPID keys identify this server to the push service. They are generated
locally by `py_vapid`: no account, no service, nothing to sign up for.

Re-running this REPLACES the keys, which invalidates every existing push
subscription -- browsers bind a subscription to the public key it was created
with. So it refuses unless --force is given.
"""

from __future__ import annotations

import base64
import pathlib
import re
import sys

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01

ENV = pathlib.Path(__file__).resolve().parent.parent / ".env"
PUBLIC = "ZENO_WEB_PUSH_PUBLIC_KEY"
PRIVATE = "ZENO_WEB_PUSH_PRIVATE_KEY"
SUBJECT = "ZENO_WEB_PUSH_SUBJECT"


def _b64(raw: bytes) -> str:
    """base64url without padding -- the encoding the Web Push spec wants."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _set(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(line, text)
    return text.rstrip("\n") + f"\n{line}\n"


def main() -> int:
    force = "--force" in sys.argv
    existing = ENV.read_text(encoding="utf-8") if ENV.exists() else ""

    already = re.search(rf"^{PRIVATE}=(.+)$", existing, re.MULTILINE)
    if already and already.group(1).strip() and not force:
        print(f"{PRIVATE} is already set in .env.")
        print("Re-generating invalidates every existing push subscription,")
        print("because a browser binds its subscription to the public key it")
        print("was created with. Pass --force if that is what you want.")
        return 1

    vapid = Vapid01()
    vapid.generate_keys()
    public = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")

    subject = ""
    found = re.search(rf"^{SUBJECT}=(.*)$", existing, re.MULTILINE)
    if found:
        subject = found.group(1).strip()
    if not subject:
        # Push services require a contact so they can reach the operator about
        # a misbehaving sender. mailto: is what the spec expects.
        subject = "mailto:owntred399@gmail.com"

    text = existing
    text = _set(text, PUBLIC, _b64(public))
    text = _set(text, PRIVATE, _b64(private))
    text = _set(text, SUBJECT, subject)
    ENV.write_text(text, encoding="utf-8")

    print(f"Written to {ENV}")
    print(f"  {PUBLIC}  = {_b64(public)}")
    print(f"  {PRIVATE} = [written to .env, not shown]")
    print(f"  {SUBJECT} = {subject}")
    print()
    print("The PUBLIC key is meant to be public -- the browser needs it to")
    print("subscribe. The private key must never leave this machine, and .env")
    print("is already blocked by .gitignore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
