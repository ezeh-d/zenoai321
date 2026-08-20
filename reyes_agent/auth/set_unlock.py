"""Set the ZENO device-unlock phrase, privately.

    python -m reyes_agent.auth.set_unlock

Read with getpass, so the phrase never shows on screen, never lands on the
command line (shell history, process list) and is never logged -- only its
scrypt hash is stored. This is the phrase you (or your voice) type on a new
browser to approve it without walking to the PC.
"""

from __future__ import annotations

import getpass

from reyes_agent.auth.unlock import get_unlock


def main() -> int:
    print("ZENO unlock phrase")
    print("-" * 40)
    print("A new browser can be approved by typing (or speaking) this phrase,")
    print("instead of approving from the PC. Keep it secret; it is a second")
    print("password, separate from your login.\n")
    phrase = getpass.getpass("Unlock phrase (hidden): ")
    confirm = getpass.getpass("Confirm phrase: ")
    if phrase != confirm:
        print("They did not match. Nothing changed.")
        return 1
    ok, message = get_unlock().set_phrase(phrase)
    print(("\n" + message) if ok else ("\nRefused: " + message))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
