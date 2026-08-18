"""Owner authentication for ZENO's online surface.

WHY THIS IS SEPARATE FROM phone_security
-----------------------------------------
`phone_security` authenticates a DEVICE on the owner's own LAN. It is built
around a QR pairing token and a WebAuthn credential bound to that handset, and
it is deliberately refused from anywhere that is not the local network.

This module authenticates the OWNER over the public internet, where none of
those assumptions hold: there is no shared network to prove, the client may be
any browser, and the first factor has to be something the owner knows rather
than something the LAN implies.

The two are complementary, not duplicates. Nothing here replaces or weakens
the phone pairing path, and `phone_security` is not modified.

WHAT IS REUSED RATHER THAN REBUILT
----------------------------------
* `remote_access.policy.check_rate` -- the sliding-window limiter, already
  bounded against limiter-as-DoS, already has `login` and `auth_failure`
  buckets.
* `remote_access.policy.evaluate` -- SAFE / CONTROL / SENSITIVE / FINANCIAL.
  Owner authentication does not add a bypass; an authenticated owner still
  cannot move money from a phone.
* The `webauthn` library already vendored for phone passkeys.
"""

from reyes_agent.auth.owner import (  # noqa: F401
    AuthResult,
    OwnerAuthService,
    Session,
    get_owner_auth,
    reset_for_tests,
)

__all__ = ["AuthResult", "OwnerAuthService", "Session", "get_owner_auth",
           "reset_for_tests"]
