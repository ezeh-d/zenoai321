"""Notice that a sequence keeps repeating -- and mostly, say nothing.

WHAT THIS LEARNS FROM
---------------------
`zeno_action_history`, the table ZENO already writes after every action it
takes (id, ts, action, resource, result, reversible...). No new watching is
introduced. On this machine it currently holds 122 real actions, dominated
by `write_project_file` (48), `build_project` (14) and `website_project`
(12) -- so there is genuine material here, and also genuinely not much of
it, which is exactly why the thresholds below matter.

WHY IT LEARNS ACTION NAMES AND NOT TARGETS
------------------------------------------
The `resource` column holds real paths -- documents, project folders,
occasionally someone's name. The useful pattern is "you open the project,
then build, then read the errors". The path is not the pattern; it is the
private part. So sequences are keyed on ACTION NAMES only, and a proposed
skill deliberately leaves its targets blank for the owner to fill in.

This mirrors `anticipation.py`, which learns from executable names and
never from window titles, for the same reason.

THE THRESHOLDS ARE THE POINT
----------------------------
The brief is explicit: ZENO must not turn one random action into powerful
automation. So a sequence must repeat on separate occasions, be long enough
to be worth automating, and be short enough to actually mean something.
Below any of those, `propose()` returns nothing. Silence is the normal
output of this module and is not a bug.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.skills import registry
from reyes_agent.skills.models import LEARNED, OBSERVED, Skill, Step

# A sequence must have been performed this many separate times before it is
# even a candidate. Three is the smallest number that distinguishes a habit
# from a coincidence plus a retry.
MIN_OCCURRENCES = 3

# Shorter than this is not a workflow, it is a command ZENO already has.
MIN_LENGTH = 3
MAX_LENGTH = 6

# Consecutive actions further apart than this are not one workflow, they are
# two things that happened in the same afternoon.
MAX_GAP_S = 300.0

# Proportion of that action-pair's occurrences that follow the pattern.
MIN_CONFIDENCE = 0.5

# Actions never worth turning into a skill: either trivially cheap already,
# or things that should always be a deliberate decision.
_NOT_WORTH_LEARNING = frozenset({
    "get_datetime", "list_capabilities", "system_health", "take_screenshot",
    "show_map", "web_search",
})


def _db() -> Path:
    return Path(config.VAULT_PATH) / "07-System" / "heartbeat" / "state.db"


def _history(limit: int = 4000) -> list[tuple[float, str]]:
    """(timestamp, action) oldest-first. Returns [] rather than raising."""
    path = _db()
    if not path.exists():
        return []
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = connection.execute(
                "SELECT ts, action FROM zeno_action_history "
                "WHERE action IS NOT NULL AND action != '' "
                "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return [(float(ts or 0.0), str(action)) for ts, action in reversed(rows)]


def _sessions(history: list[tuple[float, str]]) -> list[list[str]]:
    """Split the flat log into runs of actions that belong together."""
    sessions: list[list[str]] = []
    current: list[str] = []
    previous = 0.0
    for timestamp, action in history:
        if current and (timestamp - previous) > MAX_GAP_S:
            sessions.append(current)
            current = []
        if action not in _NOT_WORTH_LEARNING:
            current.append(action)
        previous = timestamp
    if current:
        sessions.append(current)
    return [s for s in sessions if len(s) >= MIN_LENGTH]


def observed_sequences() -> list[dict[str, Any]]:
    """Every repeated action sequence, with the counts behind it.

    This is the OBSERVED tier: raw statistics, nothing that can run.
    """
    sessions = _sessions(_history())
    counts: Counter[tuple[str, ...]] = Counter()
    for session in sessions:
        seen_here: set[tuple[str, ...]] = set()
        for length in range(MIN_LENGTH, MAX_LENGTH + 1):
            for start in range(len(session) - length + 1):
                window = tuple(session[start:start + length])
                if len(set(window)) < 2:
                    continue      # the same action repeated is not a workflow
                seen_here.add(window)
        # Count each distinct sequence ONCE per session, so a single long
        # session cannot manufacture its own evidence.
        for window in seen_here:
            counts[window] += 1

    total_sessions = max(1, len(sessions))
    results = []
    for window, occurrences in counts.most_common(50):
        if occurrences < MIN_OCCURRENCES:
            continue
        confidence = occurrences / total_sessions
        results.append({"actions": list(window), "occurrences": occurrences,
                        "sessions": total_sessions, "confidence": round(confidence, 3),
                        "meets_threshold": confidence >= MIN_CONFIDENCE})
    return results


def propose(*, dry_run: bool = False) -> list[Skill]:
    """Turn qualifying observations into LEARNED skills the owner can review.

    A proposed skill still cannot run -- `Skill.runnable` requires APPROVED,
    and only an explicit human act reaches that state.
    """
    proposals: list[Skill] = []
    for observation in observed_sequences():
        if not observation["meets_threshold"]:
            continue
        actions = observation["actions"]
        name = _name_for(actions)
        if registry.by_name(name):
            continue          # already known; `improver` handles updates

        skill = Skill(
            name=name,
            description=("Noticed because you did this " f"{observation['occurrences']} "
                         f"times: {' -> '.join(actions)}. Targets are left blank on "
                         "purpose -- ZENO learned the shape of the workflow, not your "
                         "files."),
            state=LEARNED,
            steps=[Step(action=a, target="", expect="") for a in actions],
            required_tools=sorted(set(actions)),
            triggers=[],
            verification="Each step reports its own result; the run stops at the first failure.",
            failure_recovery="stop",
            confidence=float(observation["confidence"]),
            observations=int(observation["occurrences"]),
            source="learned")

        if not dry_run:
            ok, _reason = registry.save(skill, event="proposed",
                                        detail=f"{observation['occurrences']} occurrences")
            if not ok:
                continue          # constitution refused it; do not surface it
        proposals.append(skill)
    return proposals


def _name_for(actions: list[str]) -> str:
    pretty = [a.replace("_", " ").strip().title() for a in actions]
    return f"{pretty[0]} then {pretty[-1]}" if len(pretty) > 1 else pretty[0]


def status() -> dict[str, Any]:
    history = _history()
    sessions = _sessions(history)
    observations = observed_sequences()
    qualifying = [o for o in observations if o["meets_threshold"]]
    return {
        "state": "ONLINE" if history else "NO DATA",
        "actions_recorded": len(history),
        "sessions": len(sessions),
        "repeated_sequences": len(observations),
        "meeting_threshold": len(qualifying),
        "thresholds": {"min_occurrences": MIN_OCCURRENCES, "min_confidence": MIN_CONFIDENCE,
                       "min_length": MIN_LENGTH, "max_length": MAX_LENGTH,
                       "max_gap_s": MAX_GAP_S},
        "source": "zeno_action_history (already recorded; nothing new is watched)",
        "privacy": "action names only -- resource paths are never learned from",
        "note": ("A proposal is a suggestion. Nothing here can execute until you "
                 "approve it, and approval is the only route to APPROVED."),
    }
