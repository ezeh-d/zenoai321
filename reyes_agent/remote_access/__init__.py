"""Remote Access -- the only place ZENO talks to the outside world.

Networking, origin policy, device authorisation and rate limiting live here
and nowhere else, so the boundary can be audited in one place instead of
being spread through unrelated modules.

It is strictly OPTIONAL. Every entry point degrades to "closed" rather than
"open" when unconfigured, and nothing in here may take desktop ZENO down:
if the tunnel dies, the internet drops, or a phone session goes bad, the
assistant keeps working locally.

Reused, not rebuilt:
  * `reyes_agent.phone_security`   -- WebAuthn, devices, sessions, pairing
  * `reyes_agent.cloudflare_tunnel`-- outbound ingress
  * `reyes_agent.agent.run_agent`  -- the ONE router. No second brain.
"""

from __future__ import annotations

from reyes_agent.remote_access import domains, policy

__all__ = ["domains", "policy"]
