"""AVA's tools -- authorized security testing, offensive and defensive.

THE SHAPE
---------
`security_authorize` is the only tool that adds a target to scope, and it
requires the owner's confirmation and an attestation. Every other tool that
touches a target reads that scope and refuses anything not in it. So the owner
grants AVA a target once, deliberately, and from then on AVA works the full
engagement against it -- and against nothing else.

The planning tools return methodology and real commands. They do not execute:
running an offensive tool against even an authorized host is the owner's
deliberate act, through the normal confirmation-gated command path, not a
side effect of asking AVA to think.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register


@register(
    name="security_authorize",
    description=(
        "Authorize a target for AVA to security-test. AVA acts ONLY on targets "
        "authorized here -- the owner's own systems, a lab/CTF, or a target with "
        "written permission. Use for 'AVA can test 10.0.0.5', 'authorize "
        "example.lab for pentest', 'add this to scope'. Requires an attestation "
        "of the right to test it. Refuses third-party infrastructure the owner "
        "cannot consent for."),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string",
                    "description": "IP, CIDR range, hostname or URL to authorize."},
        "attestation": {"type": "string",
                        "enum": ["i_own_it", "written_permission", "ctf_or_lab", "bug_bounty_scope"],
                        "description": "How the owner is entitled to test this target."},
        "note": {"type": "string", "description": "Optional engagement note."}},
        "required": ["target", "attestation"]},
    requires_confirmation=True,
)
def security_authorize(target: str, attestation: str, note: str = "") -> str:
    from reyes_agent.security.testing import authorization

    ok, message = authorization.get_scope().authorize(target, attestation, note=note)
    return json.dumps({"authorized": ok, "detail": message, "target": target})


@register(
    name="security_scope",
    description=("Show which targets AVA is currently authorized to test. Use for "
                 "'what's in scope', 'what can AVA test', 'show the engagement'."),
    input_schema={"type": "object", "properties": {}},
)
def security_scope() -> str:
    from reyes_agent.security.testing import authorization

    targets = [t.as_dict() for t in authorization.get_scope().targets(active_only=True)]
    return json.dumps({"authorized_targets": targets, "count": len(targets),
                       "note": "AVA operates only on these. Nothing else is in scope."})


@register(
    name="security_revoke",
    description=("Remove a target from AVA's authorized scope, or clear all scope. "
                 "Use for 'AVA stop testing 10.0.0.5', 'end the engagement', "
                 "'clear the scope'."),
    input_schema={"type": "object", "properties": {
        "target": {"type": "string", "description": "Target to revoke. Omit with all=true to clear everything."},
        "all": {"type": "boolean", "description": "Revoke every authorized target."}},
    },
    requires_confirmation=True,
)
def security_revoke(target: str = "", all: bool = False) -> str:  # noqa: A002
    from reyes_agent.security.testing import authorization

    scope = authorization.get_scope()
    if all:
        return json.dumps({"revoked_all": True, "count": scope.clear()})
    return json.dumps({"revoked": scope.revoke(target), "target": target})


@register(
    name="security_toolkit",
    description=(
        "AVA's security toolkit -- the offensive and defensive tools for a phase "
        "or task. Use for 'what tools for web testing', 'password cracking tools', "
        "'AVA's forensics toolkit', 'how would you enumerate SMB'. Reference only; "
        "knowing a tool is not running it."),
    input_schema={"type": "object", "properties": {
        "query": {"type": "string",
                  "description": "A phase (recon, scanning, web, exploitation, post_exploit, "
                                 "forensics, defense, ...) or a keyword (sqli, wifi, kerberos)."},
        "side": {"type": "string", "enum": ["offense", "defense", "both"],
                 "description": "Filter to offensive or defensive tools. Default both."}},
        "required": ["query"]},
)
def security_toolkit(query: str, side: str = "both") -> str:
    from reyes_agent.security.testing import catalog

    q = str(query or "").strip().lower()
    if q in catalog.PHASES:
        matches = catalog.tools(phase=q, side=("" if side == "both" else side))
    else:
        matches = catalog.find(q)
        if side != "both":
            matches = [t for t in matches if t.side in (side, catalog.DUAL)]
    return json.dumps({
        "query": query,
        "tools": [t.as_dict() for t in matches[:20]],
        "count": len(matches),
        "catalog": catalog.summary(),
    })


@register(
    name="security_archive_catalog",
    description=(
        "Inspect the owner-supplied AllHackingTools archive through AVA's safe "
        "catalog. Every upstream reference is classified as defensive, authorized-"
        "testing, blocked, or quarantined. The archive is never extracted, installed "
        "or executed. Use for 'show the AllHackingTools catalog', 'which archive "
        "tools are safe', or 'why is this hacking tool blocked'."),
    input_schema={"type": "object", "properties": {
        "query": {"type": "string", "description": "Tool, category or path text."},
        "state": {"type": "string", "enum": ["DEFENSIVE_REFERENCE", "AUTHORIZED_TESTING", "BLOCKED", "QUARANTINED_INSTALLER", "DOCUMENTATION"]},
        "limit": {"type": "integer", "description": "Maximum rows, capped at 200."},
        "include_files": {"type": "boolean", "description": "Also show bounded archive-file entries."},
    }},
)
def security_archive_catalog(query: str = "", state: str = "", limit: int = 50,
                             include_files: bool = False) -> str:
    from reyes_agent.security.testing import archive_catalog

    return json.dumps(archive_catalog.query(query, state=state, limit=limit,
                                            include_entries=include_files))


@register(
    name="security_plan",
    description=(
        "Plan a security assessment of an AUTHORIZED target -- the phases, the "
        "tools, and the real commands, offensive and/or defensive. Use for 'AVA "
        "pentest 10.0.0.5', 'plan a web assessment of example.lab', 'how would you "
        "attack this box', 'harden my server'. Refuses targets not in scope and "
        "techniques that cause indiscriminate harm (DoS, mass attacks, malware)."),
    input_schema={"type": "object", "properties": {
        "goal": {"type": "string", "description": "What to achieve, in plain words."},
        "target": {"type": "string",
                   "description": "The authorized target. Required for anything touching a live system."},
        "side": {"type": "string", "enum": ["offense", "defense", "both"],
                 "description": "Offensive, defensive, or both. Default both."}},
        "required": ["goal"]},
)
def security_plan(goal: str, target: str = "", side: str = "both") -> str:
    from reyes_agent.security.testing import engagement

    result = engagement.plan(goal, target, side=side)
    return json.dumps(result.as_dict())


@register(
    name="security_authorization_log",
    description=("The audit trail of what AVA was authorized to test and when. Use "
                 "for 'show the scope history', 'what has AVA been authorized for'."),
    input_schema={"type": "object", "properties": {
        "limit": {"type": "integer", "description": "How many entries (default 50)."}},
    },
)
def security_authorization_log(limit: int = 50) -> str:
    from reyes_agent.security.testing import authorization

    return json.dumps({"entries": authorization.get_scope().audit_log(limit)})


@register(
    name="security_sanctioned_targets",
    description=(
        "Real public servers whose owners published permission to test them "
        "(Nmap's scanme host, Acunetix's vulnerable test sites, IBM's demo bank). "
        "List them, or authorize one for AVA. Use for 'give AVA a real target to "
        "practise on', 'authorize scanme.nmap.org', 'legal targets to hack'."),
    input_schema={"type": "object", "properties": {
        "authorize": {"type": "string",
                      "description": "A sanctioned host to authorize (e.g. testphp.vulnweb.com). Omit to just list them."}},
    },
    requires_confirmation=True,
)
def security_sanctioned_targets(authorize: str = "") -> str:
    from reyes_agent.security.testing import bounty

    if not str(authorize or "").strip():
        return json.dumps({"sanctioned": bounty.sanctioned_targets(),
                           "note": "Each owner has published permission to test these. "
                                   "Authorize one to let AVA work it."})
    ok, detail = bounty.authorize_sanctioned(authorize)
    return json.dumps({"authorized": ok, "target": authorize, "detail": detail})


@register(
    name="security_import_bounty_scope",
    description=(
        "Load a bug-bounty programme's published scope into AVA's authorization, "
        "so its in-scope assets become testable in one step. Give the programme's "
        "scope (its in-scope and out-of-scope lists, pasted or as JSON). Out-of-scope "
        "entries are skipped and third-party assets refused. Use for 'import this "
        "HackerOne scope', 'authorize the bug bounty targets'."),
    input_schema={"type": "object", "properties": {
        "scope": {"type": "string",
                  "description": "The programme scope: JSON {\"in_scope\":[...],\"out_of_scope\":[...]} "
                                 "or pasted text with in-scope / out-of-scope sections."},
        "program": {"type": "string", "description": "Programme name, for the audit trail."}},
        "required": ["scope"]},
    requires_confirmation=True,
)
def security_import_bounty_scope(scope: str, program: str = "bug-bounty programme") -> str:
    from reyes_agent.security.testing import bounty

    report = bounty.import_program(scope, program=program)
    return json.dumps(report.as_dict())


@register(
    name="security_lab",
    description=(
        "AVA's local vulnerable lab -- real servers (DVWA, OWASP Juice Shop, "
        "WebGoat) in Docker on localhost for full exploitation practice. Starting "
        "one auto-authorizes it (localhost is yours). Use for 'start the DVWA lab', "
        "'give AVA something to hack', 'spin up juice shop', 'stop the lab'."),
    input_schema={"type": "object", "properties": {
        "action": {"type": "string", "enum": ["list", "start", "stop", "status"],
                   "description": "list the labs, start/stop one, or show what's running."},
        "lab": {"type": "string", "enum": ["dvwa", "juice-shop", "webgoat"],
                "description": "Which lab, for start/stop."}},
        "required": ["action"]},
    requires_confirmation=True,
)
def security_lab(action: str, lab: str = "") -> str:
    from reyes_agent.security.testing import lab as lab_mod

    act = str(action or "").strip().lower()
    if act == "list":
        return json.dumps({"labs": lab_mod.catalog()})
    if act == "status":
        return json.dumps(lab_mod.status())
    if act == "start":
        return json.dumps(lab_mod.start(lab).as_dict())
    if act == "stop":
        return json.dumps(lab_mod.stop(lab).as_dict())
    return json.dumps({"error": f"unknown action {action!r}"})
