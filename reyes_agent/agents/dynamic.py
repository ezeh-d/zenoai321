"""Temporary specialists -- expertise for one task, not a new personality.

    "Create an expert in Shopify automation for this task."

WHY TEMPORARY IS THE POINT
--------------------------
The brief is explicit: "This is NOT a permanent new personality by default."
An assistant that spawns a permanent specialist for every unfamiliar domain
accumulates a cast of half-remembered personas, each with its own opinions,
none of them maintained. Six months later nobody knows why ZENO has a
Shopify expert or whether it still works.

So a dynamic specialist is a CONTEXT with an expiry. It exists for the task,
it is consulted through the existing agent machinery, and when the task ends
its runtime context is discarded.

WHAT SURVIVES, AND WHAT DOES NOT
--------------------------------
    discarded   the persona, the prompt, the conversation, the scratch state
    retained    what was LEARNED -- a skill, or a knowledge note with sources

That asymmetry is the whole design. The useful residue of "be a Shopify
expert for an hour" is a working procedure, not a personality. Retaining the
procedure and dropping the persona is how ZENO gets more capable without
getting more crowded.

IT BORROWS REACH, IT DOES NOT GRANT IT
--------------------------------------
A dynamic specialist can use only capabilities that are already usable, and
its skills go through the same constitution and approval as any other. A
temporary expert that could authorise itself would be a permission bypass
wearing a hat.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# A specialist outlives its task by this much, then goes.
DEFAULT_TTL_S = 3600.0

# More than this many at once is a sign something is spawning them in a loop.
MAX_ACTIVE = 6

ACTIVE = "ACTIVE"
FINISHED = "FINISHED"
EXPIRED = "EXPIRED"

_specialists: dict[str, "Specialist"] = {}


@dataclass
class Specialist:
    domain: str
    task: str
    specialist_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    created_at: float = field(default_factory=time.time)
    ttl_s: float = DEFAULT_TTL_S
    state: str = ACTIVE
    capabilities: list[str] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    retained: list[str] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_s

    @property
    def alive(self) -> bool:
        return self.state == ACTIVE and not self.expired

    def brief(self) -> str:
        """The context handed to the model. Deliberately narrow.

        It says what the specialist is FOR and, just as importantly, that it
        is temporary and borrows its reach -- a specialist told it is an
        authority tends to behave like one.
        """
        tools = ", ".join(self.capabilities) or "no additional tools"
        return (
            f"You are ZENO, working on one task that needs {self.domain} expertise: "
            f"{self.task}\n"
            f"Draw on what you know about {self.domain}. You have these capabilities "
            f"and no others: {tools}.\n"
            "This context is temporary and exists only for this task. You are not a "
            "separate assistant and you have no additional authority -- anything that "
            "needs permission still needs it. If you do not know something about "
            f"{self.domain}, say so and research it rather than inventing it."
        )

    def note(self, what: str, *, source: str = "") -> None:
        """Something learned that might outlive the task."""
        self.notes.append({"what": str(what)[:1000], "source": str(source)[:300],
                           "at": time.time()})
        del self.notes[:-40]

    def as_dict(self) -> dict[str, Any]:
        return {"specialist_id": self.specialist_id, "domain": self.domain,
                "task": self.task[:200], "state": self.state, "alive": self.alive,
                "age_s": round(time.time() - self.created_at, 1),
                "ttl_s": self.ttl_s, "capabilities": self.capabilities,
                "notes": len(self.notes), "retained": self.retained}


def _sweep() -> None:
    for specialist in list(_specialists.values()):
        if specialist.state == ACTIVE and specialist.expired:
            specialist.state = EXPIRED
            specialist.notes.clear()          # runtime context goes


def create(domain: str, task: str, *, ttl_s: float = DEFAULT_TTL_S
           ) -> tuple[Specialist | None, str]:
    """Spin up a task-scoped specialist, if a permanent one does not already fit."""
    _sweep()

    existing = _permanent_match(domain)
    if existing:
        return None, (f"'{existing}' already covers {domain} -- I will use it rather "
                      "than inventing a temporary specialist.")

    alive = [s for s in _specialists.values() if s.alive]
    if len(alive) >= MAX_ACTIVE:
        return None, (f"There are already {len(alive)} temporary specialists open. "
                      "That usually means something is spawning them in a loop, so I "
                      "have stopped rather than adding another.")

    specialist = Specialist(domain=str(domain).strip(), task=str(task).strip(),
                            ttl_s=max(60.0, float(ttl_s)))
    specialist.capabilities = _borrowable()
    _specialists[specialist.specialist_id] = specialist
    return specialist, (f"Working as a temporary {specialist.domain} specialist for "
                        "this task. The context goes when the task is done; anything "
                        "genuinely useful becomes a skill or a note.")


def _permanent_match(domain: str) -> str:
    """Is there already a real agent for this. Prefer it -- always."""
    text = str(domain or "").strip().lower()
    if not text:
        return ""
    try:
        from reyes_agent.agents import registry

        for agent in registry.agents():
            haystack = f"{agent.name} {getattr(agent, 'role', '')} " \
                       f"{getattr(agent, 'description', '')}".lower()
            if text in haystack:
                return agent.name
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _borrowable() -> list[str]:
    """Only what is ALREADY usable. A specialist cannot grant itself reach."""
    try:
        from reyes_agent.capabilities import registry

        registry.status()
        return registry.usable_names()
    except Exception:  # noqa: BLE001
        return []


def get(specialist_id: str) -> Specialist | None:
    _sweep()
    return _specialists.get(str(specialist_id or ""))


def finish(specialist_id: str, *, retain_skill: str = "",
           retain_note: str = "") -> dict[str, Any]:
    """End the task: keep what was learned, discard the persona."""
    specialist = _specialists.get(str(specialist_id or ""))
    if specialist is None:
        return {"ok": False, "say": "no such specialist"}

    kept: list[str] = []
    if retain_skill:
        kept.append(f"skill:{retain_skill}")
    if retain_note:
        kept.append(f"note:{retain_note[:80]}")
        _remember(specialist, retain_note)

    specialist.retained = kept
    specialist.state = FINISHED
    discarded = len(specialist.notes)
    specialist.notes.clear()          # the runtime context does not survive

    return {"ok": True, "retained": kept, "discarded_notes": discarded,
            "say": (f"Done. I kept {', '.join(kept)} and dropped the temporary "
                    f"{specialist.domain} context."
                    if kept else
                    f"Done. Nothing from that was worth keeping, so the temporary "
                    f"{specialist.domain} context is gone.")}


def _remember(specialist: Specialist, note: str) -> None:
    try:
        from reyes_agent.knowledge import vector

        vector.add(f"specialist-{specialist.specialist_id}", note,
                   collection="learned_knowledge",
                   metadata={"domain": specialist.domain, "source": "dynamic_specialist"})
    except Exception:  # noqa: BLE001
        pass


def active() -> list[Specialist]:
    _sweep()
    return [s for s in _specialists.values() if s.alive]


def reset() -> None:
    _specialists.clear()


def status() -> dict[str, Any]:
    _sweep()
    return {
        "state": "ONLINE",
        "active": [s.as_dict() for s in active()],
        "max_active": MAX_ACTIVE,
        "default_ttl_s": DEFAULT_TTL_S,
        "note": ("Temporary by default. A permanent agent is always preferred when "
                 "one fits. The persona is discarded when the task ends; what was "
                 "learned becomes a skill or a knowledge note."),
        "authority": "borrows only already-usable capabilities; grants nothing",
    }
