"""What an MCP server is allowed to do, and how it earns that.

THE THREAT
----------
An MCP server is arbitrary code with a tool manifest. Installing one from a
registry is closer to installing a browser extension than to adding a
library: it runs, it can read files, it can reach the network, and its tool
descriptions are text that goes into a model prompt. A registry entry is a
CLAIM by a stranger, not a fact.

So discovery and trust are separated absolutely. Finding a server tells
ZENO it exists. Nothing else.

THE STATES
----------
    DISCOVERED  seen in a registry. Cannot run. Cannot be prompted about.
    UNTRUSTED   inspected; its manifest is recorded. Still cannot run.
    REVIEWED    ZENO has checked it against the rules below and has an
                opinion. Still cannot run.
    APPROVED    the owner said yes, at a stated permission level.
    INSTALLED   present on disk.
    ENABLED     running and callable.
    DISABLED    installed, deliberately not running.
    BLOCKED     refused. Never offered again.

Only ENABLED is callable, and reaching it requires an explicit human act at
APPROVED. Nothing promotes itself.

THE RULE THAT MATTERS MOST
--------------------------
"Unknown MCP servers must not receive automatic full-system access." So
permissions are not inherited from the manifest -- a server asking for
filesystem access does not get filesystem access, it gets a REQUEST for it
that the owner has to grant. What a server asks for and what it receives are
two different fields, deliberately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DISCOVERED = "DISCOVERED"
UNTRUSTED = "UNTRUSTED"
REVIEWED = "REVIEWED"
APPROVED = "APPROVED"
INSTALLED = "INSTALLED"
ENABLED = "ENABLED"
DISABLED = "DISABLED"
BLOCKED = "BLOCKED"

STATES = (DISCOVERED, UNTRUSTED, REVIEWED, APPROVED, INSTALLED,
          ENABLED, DISABLED, BLOCKED)

# The only state in which a server's tools may be called.
CALLABLE = frozenset({ENABLED})

# Legal moves. Everything else is refused, including anything that skips
# APPROVED -- there is no path to running that avoids the owner.
_TRANSITIONS: dict[str, frozenset[str]] = {
    DISCOVERED: frozenset({UNTRUSTED, BLOCKED}),
    UNTRUSTED:  frozenset({REVIEWED, BLOCKED}),
    REVIEWED:   frozenset({APPROVED, BLOCKED}),
    APPROVED:   frozenset({INSTALLED, BLOCKED}),
    INSTALLED:  frozenset({ENABLED, DISABLED, BLOCKED}),
    ENABLED:    frozenset({DISABLED, BLOCKED}),
    DISABLED:   frozenset({ENABLED, BLOCKED}),
    BLOCKED:    frozenset(),          # terminal, on purpose
}

# Capabilities a server can ask for. Asking is free; receiving is not.
CAPABILITIES = ("filesystem_read", "filesystem_write", "network", "shell",
                "credentials", "environment", "process_spawn")

# Capabilities that are never granted automatically at any trust level.
NEVER_AUTOMATIC = frozenset({"shell", "credentials", "process_spawn", "filesystem_write"})

# Things in a manifest that mean "do not offer this to the owner at all".
_DISQUALIFYING = (
    (r"(?i)\b(keylog|exfiltrat|backdoor|rootkit|miner|ransom)", "malicious intent in the manifest"),
    (r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions", "prompt injection in the manifest"),
    (r"(?i)\b(disregard|override)\s+(your|the)\s+(system|rules|policy)", "prompt injection in the manifest"),
    (r"(?i)you\s+are\s+now\s+(a|an)\b", "prompt injection in the manifest"),
)

_COMPILED = tuple((re.compile(p), why) for p, why in _DISQUALIFYING)


@dataclass
class Manifest:
    """What a server SAYS about itself. None of it is verified."""

    name: str
    publisher: str = ""
    source: str = ""
    description: str = ""
    commands: list[str] = field(default_factory=list)
    requested: list[str] = field(default_factory=list)
    network_access: bool = False
    filesystem_access: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "publisher": self.publisher, "source": self.source,
                "description": self.description[:400], "commands": self.commands[:20],
                "requested": self.requested, "network_access": self.network_access,
                "filesystem_access": self.filesystem_access}

    def text(self) -> str:
        return " ".join([self.name, self.publisher, self.description,
                         " ".join(self.commands), " ".join(self.requested)])


@dataclass
class Review:
    verdict: str                      # ok | caution | refuse
    reasons: list[str] = field(default_factory=list)
    granted: list[str] = field(default_factory=list)
    withheld: list[str] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return self.verdict == "refuse"

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reasons": self.reasons,
                "granted": self.granted, "withheld": self.withheld}


def may_move(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def review(manifest: Manifest, *, publisher_trusted: bool = False) -> Review:
    """Form an opinion. Never an installation.

    The output separates what the server asked for from what ZENO is willing
    to hand over without the owner deciding -- which for the dangerous half
    is nothing, at any trust level.
    """
    result = Review(verdict="ok")

    body = manifest.text()
    for pattern, why in _COMPILED:
        if pattern.search(body):
            result.verdict = "refuse"
            result.reasons.append(why)
            result.withheld = list(manifest.requested)
            return result

    if not manifest.publisher:
        result.verdict = "caution"
        result.reasons.append("no publisher is named")
    if not manifest.source:
        result.verdict = "caution"
        result.reasons.append("no source is given, so nothing can be checked")

    unknown = [c for c in manifest.requested if c not in CAPABILITIES]
    if unknown:
        result.verdict = "caution"
        result.reasons.append(f"asks for capabilities ZENO does not recognise: {unknown}")

    for capability in manifest.requested:
        if capability in NEVER_AUTOMATIC or not publisher_trusted:
            result.withheld.append(capability)
        else:
            result.granted.append(capability)

    if set(manifest.requested) & NEVER_AUTOMATIC:
        result.verdict = "caution" if result.verdict == "ok" else result.verdict
        result.reasons.append(
            "asks for "
            + ", ".join(sorted(set(manifest.requested) & NEVER_AUTOMATIC))
            + " -- never granted automatically, whatever the publisher")

    if not result.reasons:
        result.reasons.append("nothing disqualifying found; the owner still decides")
    return result


def describe_states() -> dict[str, Any]:
    return {
        "states": list(STATES),
        "callable_states": sorted(CALLABLE),
        "transitions": {state: sorted(targets) for state, targets in _TRANSITIONS.items()},
        "never_automatic": sorted(NEVER_AUTOMATIC),
        "rule": ("Discovery is not trust. A server reaches ENABLED only via APPROVED, "
                 "and APPROVED requires the owner. What a server asks for and what it "
                 "receives are separate fields on purpose."),
    }
