"""Plan an authorized assessment, and refuse what must be refused.

TWO GATES, BOTH ENFORCED HERE
-----------------------------
1. SCOPE. Any operation naming a target checks `authorization.get_scope()`.
   A target the owner has not personally authorized gets nothing back but a
   refusal telling them how to authorize it. This is the rule the owner
   stated: AVA acts only on the people they give her.

2. TECHNIQUE. A short list of techniques is refused regardless of scope,
   because they cause indiscriminate or lasting harm rather than assessing a
   target: denial of service, mass/untargeted attacks, self-propagating
   malware, destructive payloads, supply-chain compromise. An authorization
   does not turn those into assessment.

Everything else -- the full recon → exploit → post-exploit chain, offensive
and defensive -- is planned in full for an authorized target.

WHAT A PLAN IS
--------------
A methodology: the phases to work through, the tools for each, and the real
commands to run, with the target substituted in. It is a briefing a
penetration tester would recognise, not a button that fires.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.security.testing import authorization, catalog

# Techniques refused whatever the scope. Matched against the stated goal.
# Each entry: (name, pattern, why).
_REFUSED: tuple[tuple[str, str, str], ...] = (
    ("denial_of_service",
     r"\b(?:ddos|dos attack|denial[ -]of[ -]service|flood|stress[ -]?test(?:er)?|"
     r"slowloris|amplif(?:y|ication)|volumetric|knock (?:it|them) offline|take (?:it|them) down)\b",
     "Denial-of-service degrades a target rather than assessing it, and is on the refuse "
     "list regardless of authorization. A resilience test that genuinely needs load belongs "
     "with the target's own operations team, not here."),
    ("mass_targeting",
     r"\b(?:mass (?:scan|exploit|attack)|spray the internet|entire internet|"
     r"everyone on|all (?:hosts|ips) (?:on|in) the internet|untargeted|scan the world)\b",
     "Untargeted, internet-wide attacks are not a scoped engagement and are refused."),
    ("malware_propagation",
     r"\b(?:worm|self[ -]propagat|ransomware|wiper|build (?:a|me) (?:virus|malware|trojan)|"
     r"spread (?:to|across) (?:other|every))\b",
     "Self-propagating or destructive malware causes harm beyond any authorized target and "
     "is refused. Payloads for an authorized engagement stay scoped to that engagement's hosts."),
    ("supply_chain",
     # Allow words between the verb and its object: "poison the npm package".
     r"\b(?:supply[ -]chain|poison\b.{0,20}\b(?:package|dependenc|repo|registry|supply)|"
     r"backdoor\b.{0,20}\b(?:package|library|dependenc|update|registry)|typosquat)",
     "Supply-chain compromise harms everyone downstream of the target, not the target, and "
     "is refused."),
    ("real_world_fraud",
     r"\b(?:steal (?:real )?(?:money|funds|identit)|"
     r"drain\b.{0,15}\b(?:wallet|account|funds)|carding|launder)",
     "That describes fraud, not a security assessment, and is refused."),
)

_REFUSED_C = tuple((name, re.compile(pat, re.IGNORECASE), why) for name, pat, why in _REFUSED)

# Map words in a goal to the kill-chain phases they imply.
_PHASE_HINTS: dict[str, tuple[str, ...]] = {
    "recon": ("recon", "reconnaissance", "osint", "subdomain", "footprint", "information gathering", "enumerate the domain"),
    "scanning": ("scan", "port", "discover host", "ping sweep", "open ports", "service"),
    "enumeration": ("enumerate", "smb", "shares", "ldap", "active directory", "ad ", "snmp", "users"),
    "vuln_analysis": ("vulnerab", "cve", "weakness", "misconfig", "outdated", "patch"),
    "web": ("web", "http", "website", "sql injection", "sqli", "xss", "csrf", "burp", "api", "login page", "wordpress"),
    "password": ("password", "credential", "brute", "hash", "crack", "kerberoast", "login"),
    "wireless": ("wifi", "wi-fi", "wireless", "wpa", "handshake", "access point"),
    "exploitation": ("exploit", "gain access", "shell", "rce", "remote code", "metasploit", "payload", "foothold"),
    "post_exploit": ("privilege", "privesc", "escalat", "lateral", "pivot", "persistence", "domain admin", "post-exploit", "mimikatz"),
    "c2": ("command and control", "c2", "beacon", "implant", "red team"),
    "forensics": ("forensic", "incident", "ir ", "memory dump", "triage", "compromise", "breach", "malware analysis"),
    "reversing": ("reverse", "disassemble", "decompile", "binary", "firmware"),
    "defense": ("harden", "defend", "detect", "monitor", "siem", "secure my", "protect", "baseline", "audit my"),
}


@dataclass
class PhaseStep:
    phase: str
    tools: list[dict[str, Any]]
    commands: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "tools": self.tools, "commands": self.commands}


@dataclass
class Plan:
    ok: bool
    target: str = ""
    side: str = "both"
    reason: str = ""
    refused_technique: str = ""
    steps: list[PhaseStep] = field(default_factory=list)
    scope_note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "target": self.target, "side": self.side,
                "reason": self.reason, "refused_technique": self.refused_technique,
                "scope_note": self.scope_note,
                "steps": [s.as_dict() for s in self.steps]}


def check_technique(goal: str) -> tuple[bool, str, str]:
    """Is the stated goal a refused technique? (ok, name, why)."""
    text = str(goal or "")
    for name, pattern, why in _REFUSED_C:
        if pattern.search(text):
            return False, name, why
    return True, "", ""


def _phases_for(goal: str, *, defensive: bool) -> list[str]:
    text = str(goal or "").casefold()
    hit: list[str] = []
    for phase, hints in _PHASE_HINTS.items():
        if any(h in text for h in hints):
            hit.append(phase)
    if not hit:
        # No specific phase named. A full assessment walks the standard chain.
        if defensive:
            return ["defense", "vuln_analysis", "forensics"]
        return ["recon", "scanning", "enumeration", "vuln_analysis", "exploitation", "post_exploit"]
    # Keep them in canonical kill-chain order.
    return [p for p in catalog.PHASES if p in hit]


def _commands_for(tool: dict[str, Any], target: str) -> list[str]:
    """Substitute the authorized target into a tool's example command."""
    example = tool.get("example") or ""
    if not example or not target:
        return []
    host = re.sub(r"^https?://", "", target).split("/", 1)[0]
    filled = (example
              .replace("example.com", host)
              .replace("https://target", target if target.startswith("http") else f"https://{host}")
              .replace("target", host)
              .replace("10.0.0.5", host)
              .replace("10.0.0.0/24", target if "/" in target else host))
    return [filled]


def plan(goal: str, target: str = "", *, side: str = "both") -> Plan:
    """Build an assessment plan for an AUTHORIZED target.

    `side`: "offense", "defense" or "both". `target` may be empty only for a
    purely defensive or advisory plan (hardening your own posture, explaining a
    technique) -- anything that touches a remote system needs a scoped target.
    """
    goal = str(goal or "").strip()
    defensive = side == "defense"

    ok_tech, refused_name, why = check_technique(goal)
    if not ok_tech:
        return Plan(False, target=target, reason=why, refused_technique=refused_name)

    phases = _phases_for(goal, defensive=defensive)

    # Which tools would actually appear, given the side filter. A purely
    # defensive plan (defend your own posture) does not touch a remote system,
    # so it must not be forced to name a scoped target -- the touch check runs
    # against the SAME filtered set the plan will present, not every tool in
    # the phase. Otherwise one target-touching defensive tool (Atomic Red Team)
    # would make "harden my server" demand a target it never needs.
    def _phase_tools(p: str) -> list:
        ts = catalog.tools(phase=p)
        if side in ("offense", "defense"):
            ts = [t for t in ts if t.side == side or t.side == catalog.DUAL]
        return ts

    touches = any(t.touches_target for p in phases for t in _phase_tools(p))
    # A defensive-only plan without a target simply omits the few active
    # defensive tools rather than refusing.
    drop_active = defensive and not target

    scope_note = ""
    if touches and not drop_active:
        if not target:
            return Plan(False, reason=(
                "This assessment touches a live target, so it needs one you have authorized. "
                "Name the target and authorize it with security_authorize first."),
                steps=[])
        check = authorization.get_scope().check(target)
        if not check.allowed:
            return Plan(False, target=target, reason=check.reason)
        scope_note = f"In scope: matched your authorization for {check.matched}."

    steps: list[PhaseStep] = []
    for phase in phases:
        phase_tools = _phase_tools(phase)
        if drop_active:
            # No scoped target: keep only tools that do not reach a remote host.
            phase_tools = [t for t in phase_tools if not t.touches_target]
        chosen = phase_tools[:6]
        tool_dicts = [t.as_dict() for t in chosen]
        commands: list[str] = []
        if target:
            for td in tool_dicts:
                if td["touches_target"]:
                    commands.extend(_commands_for(td, target))
        steps.append(PhaseStep(phase=phase, tools=tool_dicts, commands=commands))

    return Plan(True, target=target, side=side,
                reason="Authorized assessment plan prepared." if target
                       else "Advisory plan prepared (no live target).",
                steps=steps, scope_note=scope_note)
