"""T21 Services company knowledge, shared by phone and laptop.

WHY THIS EXISTS
---------------
Asked "tell me about T21 Services", ZENO used to answer "vault's blank" -- the
SIWES evidence tools describe Divine's PORTFOLIO, not the company, and no tool
held company context. This adds one, on the SHARED brain, so the answer is the
same from either device.

It is owner-maintained, never fabricated: the knowledge lives in a Markdown
file in the vault that the owner edits (or dictates to ZENO with `t21_remember`).
ZENO returns only what is written there, plus the few facts the system already
knows for certain (the placement, the project, the SIWES period). It never
invents company facts.
"""

from __future__ import annotations

from reyes_agent import config
from reyes_agent.tools import register

_KB = config.VAULT_PATH / "knowledge" / "t21_services.md"

_SEED = """# T21 Services

<!-- ZENO reads this file to answer questions about T21 Services on any device.
     Edit it freely, or tell ZENO "remember about T21 that ..." to expand it.
     Only what is written here is treated as fact; ZENO never invents company
     details. -->

## What ZENO already knows for certain
- T21 Services is Divine's SIWES (industrial training) placement.
- The main project built there is REYES, later renamed ZENO.
- SIWES period: {start} to {end}.
- Divine's institution: Redeemer's University.

## About the company
_(Add what T21 Services does, its products/services, and its mission here.)_

## Structure
_(Add teams, departments, or how the company is organised.)_

## People
_(Add staff, roles, and who does what.)_

## Notes
_(Anything else worth remembering about T21 Services.)_
"""


def _ensure_seed() -> str:
    if not _KB.exists():
        from reyes_agent.presentation import timeline

        _KB.parent.mkdir(parents=True, exist_ok=True)
        _KB.write_text(
            _SEED.format(start=timeline.SIWES_START, end=timeline.SIWES_END),
            encoding="utf-8")
    return _KB.read_text(encoding="utf-8")


@register(
    name="t21_services",
    description=("Answer questions about T21 Services -- the company itself: what "
                 "it does, its structure, its people, and Divine's placement "
                 "there. Use for 'tell me about T21 Services', 'what does T21 do', "
                 "'who works at T21', company context and business knowledge. "
                 "Shared by phone and laptop."),
    input_schema={"type": "object", "properties": {}})
def t21_services() -> str:
    """Return the owner-maintained T21 Services knowledge."""
    try:
        return _ensure_seed()
    except OSError as exc:  # noqa: BLE001
        return f"Could not read the T21 knowledge file: {exc}"


@register(
    name="t21_remember",
    description=("Add a fact to the T21 Services knowledge so ZENO remembers it on "
                 "every device. Use for 'remember about T21 that ...', 'note that "
                 "T21 ...'."),
    input_schema={"type": "object", "properties": {
        "fact": {"type": "string", "description": "The T21 fact to remember."}},
        "required": ["fact"]})
def t21_remember(fact: str) -> str:
    fact = " ".join(str(fact or "").split())
    if not fact:
        return "Nothing to remember -- give me a fact about T21."
    try:
        _ensure_seed()
        with _KB.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- {fact}\n")
    except OSError as exc:  # noqa: BLE001
        return f"Could not update the T21 knowledge: {exc}"
    return f"Noted about T21 Services: {fact}"
