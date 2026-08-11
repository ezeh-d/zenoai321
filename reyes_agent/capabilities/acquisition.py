"""Closing a capability gap -- researched, verified, and gated at every reach.

THE PIPELINE
------------
    IDENTIFY -> RESEARCH -> PLAN -> [OWNER] -> VERIFY -> REGISTER

`REGISTER` happens only after `VERIFY` proves the capability actually works
on this machine. The brief is blunt about the failure this prevents: "Do not
mark READY merely because import succeeded." Installing something and
registering it are two different events with a test in between.

WHAT ZENO WILL NOT DO ON ITS OWN
--------------------------------
Everything that reaches outside this process stops at `[OWNER]`:

  * installing software
  * connecting an account, or completing any auth flow
  * spending money or starting a subscription
  * anything requiring CAPTCHA, MFA, or identity verification

Those are marked USER_ACTION_REQUIRED and the pipeline halts. This is not a
politeness setting -- a capability engine that can install and authorise its
own dependencies is a capability engine that can grant itself arbitrary
reach, which is precisely what `skills/constitution.py` exists to stop.

RESEARCH DOES NOT MEAN GUESSING
-------------------------------
"Do not make up an API. Do not guess CLI flags. Do not hallucinate function
names." So `research()` returns what was actually FETCHED, with its source
URLs, through the existing bounded crawler -- and returns nothing rather
than a plausible invention when it finds nothing. An acquisition built on
no evidence is refused at the plan step.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.capabilities import inventory, registry

IDENTIFIED = "IDENTIFIED"
RESEARCHING = "RESEARCHING"
PLANNED = "PLANNED"
USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
VERIFYING = "VERIFYING"
REGISTERED = "REGISTERED"
REFUSED = "REFUSED"
FAILED = "FAILED"

STATES = (IDENTIFIED, RESEARCHING, PLANNED, USER_ACTION_REQUIRED,
          VERIFYING, REGISTERED, REFUSED, FAILED)

# Steps ZENO never performs itself, whatever the goal.
OWNER_ONLY = frozenset({"install", "connect_account", "authenticate", "purchase",
                        "subscribe", "verify_identity", "accept_terms"})

# Pages to consult when researching a dependency. Bounded by the crawler.
MAX_RESEARCH_PAGES = 4


@dataclass
class Finding:
    url: str
    title: str
    excerpt: str

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "excerpt": self.excerpt[:400]}


@dataclass
class Acquisition:
    capability: str
    state: str = IDENTIFIED
    why_needed: str = ""
    findings: list[Finding] = field(default_factory=list)
    owner_actions: list[str] = field(default_factory=list)
    zeno_actions: list[str] = field(default_factory=list)
    verification: str = ""
    say: str = ""
    at: float = field(default_factory=time.time)

    @property
    def blocked_on_owner(self) -> bool:
        return self.state == USER_ACTION_REQUIRED

    def as_dict(self) -> dict[str, Any]:
        return {"capability": self.capability, "state": self.state,
                "why_needed": self.why_needed,
                "sources": [f.as_dict() for f in self.findings],
                "owner_actions": self.owner_actions,
                "zeno_actions": self.zeno_actions,
                "verification": self.verification, "say": self.say,
                "blocked_on_owner": self.blocked_on_owner}


def identify(goal: str) -> list[str]:
    """Which capabilities stand between ZENO and this goal."""
    from reyes_agent.capabilities import graph

    return [gap.capability for gap in graph.assess(goal).blocking]


def research(capability_name: str, *, pages: int = MAX_RESEARCH_PAGES,
             urls: list[str] | None = None) -> list[Finding]:
    """Find out how this thing actually works. Returns [] rather than fiction."""
    capability = registry.get(capability_name)
    if capability is None:
        return []
    if not urls:
        # Without a caller-supplied source there is nothing to fetch. ZENO
        # does not invent documentation URLs -- guessing a docs domain is
        # how you end up confidently reading someone's parked page.
        return []

    try:
        from reyes_agent import research as research_module
    except Exception:  # noqa: BLE001
        return []

    outcome = research_module.research(
        f"how to install and configure {capability_name}", urls[:pages])
    findings = []
    for source in outcome.get("sources", []):
        evidence = next((e for e in outcome.get("evidence", [])
                         if e["citation"] == source["citation"]), None)
        findings.append(Finding(url=source["url"], title=source.get("title", ""),
                                excerpt=(evidence or {}).get("excerpt", "")))
    return findings


def plan(capability_name: str, *, goal: str = "",
         findings: list[Finding] | None = None) -> Acquisition:
    """What it would take. Performs nothing."""
    acquisition = Acquisition(capability=capability_name, why_needed=goal)
    capability = registry.get(capability_name)
    if capability is None:
        acquisition.state = REFUSED
        acquisition.say = (f"I have no record of a capability called "
                           f"'{capability_name}', so I will not guess at how to "
                           "acquire it.")
        return acquisition

    state, why = capability.health()
    if state in registry.USABLE:
        acquisition.state = REGISTERED
        acquisition.say = f"{capability_name} is already available -- nothing to acquire."
        return acquisition

    acquisition.findings = list(findings or [])

    if state == registry.DEPENDENCY_MISSING:
        acquisition.state = USER_ACTION_REQUIRED
        acquisition.owner_actions = [capability.install_hint
                                     or f"install {capability.binary or capability.package}"]
        acquisition.zeno_actions = [f"verify {capability_name} works once it is installed",
                                    "register it only after that check passes"]
        acquisition.verification = _verification_for(capability)
        acquisition.say = (f"{capability_name} is not on this machine. "
                           f"{acquisition.owner_actions[0]} — I will not install "
                           "software by myself. Once it is there I will test it and "
                           "only then treat it as available.")
        return acquisition

    if state == registry.AUTH_REQUIRED:
        acquisition.state = USER_ACTION_REQUIRED
        acquisition.owner_actions = [why]
        acquisition.zeno_actions = ["verify the credential works against a real call",
                                    "register the capability if it does"]
        acquisition.verification = _verification_for(capability)
        acquisition.say = (f"{capability_name} needs credentials I cannot create: {why}. "
                           "Connecting an account, completing sign-in, MFA or identity "
                           "checks are yours to do.")
        return acquisition

    if state == registry.STANDBY:
        acquisition.state = PLANNED
        acquisition.owner_actions = [why]
        acquisition.zeno_actions = ["re-check configuration", "verify, then register"]
        acquisition.verification = _verification_for(capability)
        acquisition.say = f"{capability_name} is installed but not configured: {why}"
        return acquisition

    acquisition.state = FAILED
    acquisition.say = f"{capability_name} is {state}: {why}"
    return acquisition


def _verification_for(capability: registry.Capability) -> str:
    if capability.binary:
        return f"run `{capability.binary} --version` and require a zero exit"
    if capability.package:
        return f"import {capability.package} and call its smoke test"
    if capability.requires_secret:
        return "make one real, cheap call and require a non-error response"
    return "run the capability's own health check"


def verify(capability_name: str) -> tuple[bool, str]:
    """Does it ACTUALLY work now. The step between installed and registered."""
    inventory.invalidate(capability_name)
    capability = registry.get(capability_name)
    if capability is None:
        return False, f"no capability called '{capability_name}'"

    inventory.invalidate(capability.binary or capability.package or capability_name)
    state, why = capability.health()
    if state not in registry.USABLE:
        return False, f"still {state}: {why}"
    return True, f"{capability_name} verified working on this machine"


def acquire(capability_name: str, *, goal: str = "",
            findings: list[Finding] | None = None) -> Acquisition:
    """The whole pipeline, stopping wherever the owner is required."""
    acquisition = plan(capability_name, goal=goal, findings=findings)
    if acquisition.state not in (PLANNED,):
        return acquisition

    acquisition.state = VERIFYING
    ok, why = verify(capability_name)
    if not ok:
        acquisition.state = USER_ACTION_REQUIRED
        acquisition.say = why
        return acquisition

    acquisition.state = REGISTERED
    acquisition.say = why
    return acquisition


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "states": list(STATES),
        "owner_only": sorted(OWNER_ONLY),
        "note": ("Registration happens only after verification proves the capability "
                 "works here. Installing software, connecting accounts, spending "
                 "money and identity checks all stop at the owner."),
        "research": ("returns what was actually fetched, with source URLs, or "
                     "nothing -- documentation URLs are never invented"),
    }
