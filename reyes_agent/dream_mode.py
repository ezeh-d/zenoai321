"""Dream Mode: idle-time maintenance that costs no cloud AI usage.

DESIGN CONSTRAINT THAT SHAPED EVERYTHING HERE
---------------------------------------------
"Must not unnecessarily consume cloud AI usage." So every pass in this
module is deterministic local computation -- SQL, set operations, file
stats, string comparison. There is no model call anywhere in it. The daily
summary is assembled from recorded facts rather than written by an LLM,
which also makes it verifiable: every number traces back to a row.

SAFETY
------
Nothing is deleted. Duplicate memories are ARCHIVED (reversible, and the
living-memory ledger keeps versions), never purged. Anything destructive
is proposed as a notice for the user to act on, not performed.

Each pass is individually guarded so one failure cannot abort the rest,
and the whole run re-checks idle time between passes -- if the user comes
back mid-run, the remaining passes are skipped rather than competing for
the machine.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from reyes_agent import config

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_IDLE_REQUIRED_S = 120          # stop as soon as the user is back
_DUP_SIMILARITY = 0.92


@dataclass
class DreamReport:
    started: str = ""
    passes: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def summary(self) -> str:
        bits = [f"Dream Mode ran {len(self.passes)} pass(es) in {self.duration_s:.1f}s."]
        bits += [f"  {a}" for a in self.actions]
        bits += [f"  {f}" for f in self.findings]
        if self.skipped:
            bits.append(f"  skipped: {', '.join(self.skipped)}")
        return "\n".join(bits)


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _user_is_away() -> bool:
    try:
        from reyes_agent.activity_monitor import _idle_seconds

        return _idle_seconds() >= _IDLE_REQUIRED_S
    except Exception:  # noqa: BLE001
        return True   # can't tell -> assume away; every pass is read-mostly


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _similar(a: str, b: str) -> float:
    """Cheap token-overlap similarity. Deliberately not an embedding call:
    Dream Mode must not spend cloud usage, and near-duplicate memories are
    almost always near-identical strings."""
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# --- passes ------------------------------------------------------------
def _pass_duplicate_memories(rep: DreamReport) -> None:
    """Find near-duplicate memories and ARCHIVE the newer copy."""
    try:
        from reyes_agent import living_memory

        records = living_memory.list_memories(status="active")
    except Exception as exc:  # noqa: BLE001
        rep.skipped.append(f"memory dedup ({type(exc).__name__})")
        return

    seen: list[tuple[str, str]] = []
    archived = 0
    for rec in records:
        content = rec.get("content", "")
        mid = rec.get("id")
        if not content or not mid:
            continue
        match = next((s for s in seen if _similar(s[1], content) >= _DUP_SIMILARITY), None)
        if match:
            try:
                living_memory.archive(mid, actor="dream_mode",
                                      reason=f"near-duplicate of {match[0]}", source="dream")
                archived += 1
            except Exception:  # noqa: BLE001
                pass
        else:
            seen.append((mid, content))
    if archived:
        rep.actions.append(f"archived {archived} near-duplicate memor(y/ies) (reversible)")
    else:
        rep.findings.append("no duplicate memories found")
    rep.passes.append("memory-dedup")


def _pass_unfinished(rep: DreamReport) -> None:
    """Surface stalled missions and campaigns -- reported, never auto-closed."""
    stale_days = 7
    try:
        with _connect() as conn:
            missions = conn.execute(
                "SELECT id, name, status, updated FROM missions "
                "WHERE status NOT IN ('completed','archived','cancelled')"
            ).fetchall()
    except sqlite3.Error as exc:
        rep.skipped.append(f"unfinished-work ({exc})")
        return

    stalled = []
    for mid, name, status, updated in missions:
        try:
            age = (datetime.now() - datetime.strptime(updated, "%Y-%m-%d %H:%M")).days
        except (TypeError, ValueError):
            continue
        if age >= stale_days:
            stalled.append(f"#{mid} '{name}' ({status}, {age}d idle)")
    if stalled:
        rep.findings.append(f"{len(stalled)} stalled mission(s): " + "; ".join(stalled[:4]))
    else:
        rep.findings.append(f"no missions idle more than {stale_days} days")
    rep.passes.append("unfinished-work")


def _pass_daily_summary(rep: DreamReport) -> None:
    """Write a factual summary of the day from recorded activity."""
    today = date.today()
    since = time.time() - 24 * 3600
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT app FROM activity_log WHERE ts >= ? AND idle = 0", (since,)
            ).fetchall()
    except sqlite3.Error as exc:
        rep.skipped.append(f"daily-summary ({exc})")
        return

    apps = Counter(r[0] for r in rows if r[0])
    total_min = sum(apps.values())

    try:
        from reyes_agent import event_bus

        events = event_bus.history(limit=500, since=since)
    except Exception:  # noqa: BLE001
        events = []
    tools = Counter((e.get("payload") or {}).get("tool")
                    for e in events if e.get("type") == "tool.completed")
    tools.pop(None, None)

    if not total_min and not tools:
        rep.findings.append("nothing recorded in the last 24h -- no summary written")
        rep.passes.append("daily-summary")
        return

    lines = [f"# Day summary — {today.isoformat()}", "",
             f"Active time recorded: {total_min} minutes.", ""]
    if apps:
        lines.append("## Where the time went")
        lines += [f"- {a}: {n} min ({n / total_min:.0%})" for a, n in apps.most_common(6)]
        lines.append("")
    if tools:
        lines.append("## What ZENO did")
        lines += [f"- {t}: {n}x" for t, n in tools.most_common(8)]
        lines.append("")
    lines.append("_Assembled by Dream Mode from recorded activity. "
                 "Every figure above is a count of real rows -- no model was called._")

    try:
        from reyes_agent.tools.obsidian import write_note

        saved = write_note(title=f"Day summary {today.isoformat()}", content="\n".join(lines))
        rep.actions.append(f"wrote daily summary ({saved})")
    except Exception as exc:  # noqa: BLE001
        rep.skipped.append(f"daily-summary write ({type(exc).__name__})")
    rep.passes.append("daily-summary")


def _pass_tomorrow_agenda(rep: DreamReport) -> None:
    """Assemble tomorrow's agenda from calendar + missions + approvals."""
    tomorrow = date.today() + timedelta(days=1)
    items: list[str] = []
    try:
        with _connect() as conn:
            events = conn.execute(
                "SELECT title, when_text FROM calendar_events WHERE cancelled = 0"
            ).fetchall()
            items += [f"calendar: {t} ({w})" for t, w in events
                      if w and tomorrow.isoformat() in str(w)]
    except sqlite3.Error:
        pass
    try:
        from reyes_agent.tools.missions import list_missions_dicts

        top = [m for m in list_missions_dicts() if m["priority"] == "high"][:3]
        items += [f"mission: {m['name']} ({m['progress']}%)" for m in top]
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent import confirmation

        pending = len(confirmation.list_pending())
        if pending:
            items.append(f"{pending} action(s) waiting for your approval")
    except Exception:  # noqa: BLE001
        pass

    if items:
        rep.findings.append(f"tomorrow ({tomorrow.isoformat()}): " + "; ".join(items[:5]))
    else:
        rep.findings.append(f"nothing scheduled for {tomorrow.isoformat()}")
    rep.passes.append("tomorrow-agenda")


def _pass_knowledge_upkeep(rep: DreamReport) -> None:
    """Refresh the search index and report graph orphans."""
    try:
        from reyes_agent.tools.rag import reindex_vault

        rep.actions.append(f"search index: {reindex_vault()}")
    except Exception as exc:  # noqa: BLE001
        rep.skipped.append(f"reindex ({type(exc).__name__})")
    try:
        from reyes_agent import knowledge_graph

        st = knowledge_graph.stats()
        if st["orphan_count"]:
            rep.findings.append(
                f"{st['orphan_count']} note(s) nothing links to -- linking them in "
                "would make them findable by topic")
    except Exception:  # noqa: BLE001
        pass
    rep.passes.append("knowledge-upkeep")


_PASSES = (
    ("knowledge-upkeep", _pass_knowledge_upkeep),
    ("memory-dedup", _pass_duplicate_memories),
    ("daily-summary", _pass_daily_summary),
    ("unfinished-work", _pass_unfinished),
    ("tomorrow-agenda", _pass_tomorrow_agenda),
)


def run(force: bool = False) -> DreamReport:
    """Run maintenance. Re-checks idle between passes unless forced."""
    rep = DreamReport(started=datetime.now().strftime("%Y-%m-%d %H:%M"))
    t0 = time.time()
    for name, fn in _PASSES:
        if not force and not _user_is_away():
            rep.skipped.append(f"{name} (user active)")
            continue
        try:
            fn(rep)
        except Exception as exc:  # noqa: BLE001 -- one pass must not abort the rest
            rep.skipped.append(f"{name} ({type(exc).__name__})")
    rep.duration_s = time.time() - t0
    try:
        from reyes_agent import event_bus

        event_bus.publish("dream.completed", {
            "passes": rep.passes, "actions": rep.actions,
            "findings": len(rep.findings), "duration_s": round(rep.duration_s, 1),
        }, source="dream_mode")
    except Exception:  # noqa: BLE001
        pass
    return rep
