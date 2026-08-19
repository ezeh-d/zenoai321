"""Load real, authorized targets into AVA's scope in one command.

TWO HONEST SOURCES OF REAL TARGETS
----------------------------------
1. SANCTIONED PUBLIC HOSTS. A handful of real servers whose owners have
   *published* that you may test them -- Nmap's scanme host, Acunetix's
   deliberately-vulnerable test sites, IBM's Altoro Mutual demo. These are
   real machines on the public internet, and hitting them is legal because
   the owner said so in writing. Perfect for demonstrating the full chain
   against something that is not localhost.

2. A BUG-BOUNTY PROGRAMME'S SCOPE. You give AVA a programme's published scope
   (its in-scope and out-of-scope lists) and she authorizes the in-scope
   assets and *only* those -- out-of-scope entries are skipped, and anything
   the owner cannot grant permission over is refused. That is real production
   infrastructure you are invited, in writing, to attack.

Both run every entry through the same `authorization.is_grantable` check, so
the importer can never widen scope past what the programme actually granted.
It authorizes; it does not fetch a live programme feed and pretend the result
is current -- you supply the scope you were shown.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from reyes_agent.security.testing import authorization

# Real hosts published by their owners as legal to test. Each carries the
# public sanction it rests on, so the claim is checkable, not asserted.
SANCTIONED: tuple[dict[str, str], ...] = (
    {"target": "scanme.nmap.org",
     "by": "Nmap Project",
     "sanction": "Nmap publishes: 'You are authorized to scan this machine.' Light scanning only -- do not hammer it.",
     "good_for": "scanning, service/OS fingerprinting"},
    {"target": "testphp.vulnweb.com",
     "by": "Acunetix",
     "sanction": "Acunetix publishes this as an intentionally vulnerable test site for security tools.",
     "good_for": "web app testing, SQL injection, the full web chain"},
    {"target": "testasp.vulnweb.com",
     "by": "Acunetix",
     "sanction": "Acunetix intentionally-vulnerable ASP test site.",
     "good_for": "web app testing"},
    {"target": "testaspnet.vulnweb.com",
     "by": "Acunetix",
     "sanction": "Acunetix intentionally-vulnerable ASP.NET test site.",
     "good_for": "web app testing"},
    {"target": "rest.vulnweb.com",
     "by": "Acunetix",
     "sanction": "Acunetix intentionally-vulnerable REST API test site.",
     "good_for": "API testing"},
    {"target": "demo.testfire.net",
     "by": "IBM (Altoro Mutual)",
     "sanction": "IBM publishes Altoro Mutual as a demo banking site for security testing.",
     "good_for": "web app testing, authentication, a realistic banking target"},
)


@dataclass
class ImportReport:
    program: str
    authorized: list[str]
    skipped_out_of_scope: list[str]
    refused: list[dict[str, str]]

    def as_dict(self) -> dict[str, Any]:
        return {"program": self.program,
                "authorized": self.authorized,
                "authorized_count": len(self.authorized),
                "skipped_out_of_scope": self.skipped_out_of_scope,
                "refused": self.refused,
                "note": ("AVA is now authorized on the in-scope assets and nothing else. "
                         "Out-of-scope and non-grantable entries were not added.")}


def sanctioned_targets() -> list[dict[str, str]]:
    return [dict(s) for s in SANCTIONED]


def authorize_sanctioned(target: str) -> tuple[bool, str]:
    """Authorize one of the publicly-sanctioned hosts, by name."""
    value = str(target or "").strip().casefold()
    match = next((s for s in SANCTIONED
                  if s["target"].casefold() == value
                  or value in s["target"].casefold()), None)
    if match is None:
        names = ", ".join(s["target"] for s in SANCTIONED)
        return False, f"Not a known sanctioned host. Available: {names}"
    ok, message = authorization.get_scope().authorize(
        match["target"], "sanctioned_public",
        note=f"Sanctioned by {match['by']}: {match['sanction'][:80]}")
    return ok, (message if not ok else
                f"{message}\nSanction: {match['sanction']}")


# --- programme scope ----------------------------------------------------
_ASSET_RE = re.compile(r"[A-Za-z0-9*][A-Za-z0-9.\-/:]*\.[A-Za-z]{2,}|"
                       r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?")


def parse_scope(raw: Any) -> tuple[list[str], list[str]]:
    """Pull (in_scope, out_of_scope) from whatever the owner pasted.

    Accepts a dict ({"in_scope": [...], "out_of_scope": [...]}) or free text
    with 'in scope' / 'out of scope' sections. Deliberately forgiving on
    input and strict on output -- every candidate is validated later.
    """
    if isinstance(raw, dict):
        return ([str(x).strip() for x in raw.get("in_scope", []) if str(x).strip()],
                [str(x).strip() for x in raw.get("out_of_scope", []) if str(x).strip()])

    text = str(raw or "")
    # Try JSON first.
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return parse_scope(data)
    except (json.JSONDecodeError, TypeError):
        pass

    # Split into an in-scope and an out-of-scope region by heading.
    lower = text.lower()
    out_at = next((lower.find(h) for h in ("out of scope", "out-of-scope", "not in scope",
                                           "excluded") if h in lower), -1)
    in_region = text if out_at < 0 else text[:out_at]
    out_region = "" if out_at < 0 else text[out_at:]
    in_scope = _ASSET_RE.findall(in_region)
    out_scope = _ASSET_RE.findall(out_region)
    # An asset named in both is out of scope -- the exclusion wins.
    out_set = {a.casefold() for a in out_scope}
    in_scope = [a for a in in_scope if a.casefold() not in out_set]
    return list(dict.fromkeys(in_scope)), list(dict.fromkeys(out_scope))


def import_program(scope: Any, *, program: str = "bug-bounty programme",
                   ttl_days: int = 30) -> ImportReport:
    """Authorize a programme's in-scope assets, and only those."""
    in_scope, out_scope = parse_scope(scope)
    store = authorization.get_scope()

    authorized: list[str] = []
    refused: list[dict[str, str]] = []
    for asset in in_scope:
        grantable, why = authorization.is_grantable(asset)
        if not grantable:
            refused.append({"target": asset, "reason": why})
            continue
        ok, message = store.authorize(asset, "bug_bounty_scope",
                                      ttl_s=ttl_days * 24 * 3600,
                                      note=f"In scope: {program}"[:200])
        (authorized if ok else refused).append(asset if ok else {"target": asset, "reason": message})

    return ImportReport(program=program, authorized=authorized,
                        skipped_out_of_scope=out_scope, refused=refused)
