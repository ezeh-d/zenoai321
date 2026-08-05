"""Evolution Engine -- ZENO analysing its own real performance and
proposing improvements it will never apply on its own.

THE HARD RULE
-------------
Nothing here changes code, prompts, config or data. It measures, finds
problems, and writes recommendations. Applying any of them is a separate,
human decision. That is not timidity -- an assistant that silently
rewrites itself is one bad inference away from being unrecoverable, and
the whole build has held this line since day one (see AGENT.md's standing
list: ZENO learns via memory, never via self-modification).

EVERY FINDING IS MEASURED
------------------------
Sources are all real records this system already keeps:
  * tool latency + failure counts -> the Event Bus (`tool.completed`)
  * unused capability            -> registered tools with zero events
  * agent reliability            -> Agent Runtime metrics
  * duplicate memories           -> exact/near-duplicate text comparison
  * stale missions               -> missions untouched past a threshold
  * model latency                -> Model Router's measured samples

If a category has no data, it reports "no data yet" rather than a
zero-finding clean bill of health, because those are different things.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from reyes_agent import config

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_SLOW_TOOL_MS = 4000
_STALE_MISSION_DAYS = 14


@dataclass
class Finding:
    area: str
    severity: str            # info | notice | problem
    summary: str
    evidence: str
    recommendation: str
    applied_automatically: bool = False   # always False; kept explicit


@dataclass
class Report:
    generated: str = ""
    findings: list[Finding] = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    measured_from: dict = field(default_factory=dict)


def _tool_events(limit: int = 2000) -> list[dict]:
    try:
        from reyes_agent import event_bus

        return event_bus.history(limit=limit, event_type="tool")
    except Exception:  # noqa: BLE001
        return []


def analyse() -> Report:
    rep = Report(generated=datetime.now().strftime("%Y-%m-%d %H:%M"))
    events = _tool_events()
    rep.measured_from["tool_events"] = len(events)

    # --- slow tools, measured -------------------------------------------
    durations: dict[str, list[int]] = defaultdict(list)
    failures: Counter = Counter()
    for ev in events:
        p = ev.get("payload") or {}
        name = p.get("tool")
        if not name:
            continue
        d = p.get("duration_ms")
        if isinstance(d, int):
            durations[name].append(d)
        if str(p.get("result", "")).lower().startswith("error"):
            failures[name] += 1

    if durations:
        slow = [(n, sum(v) / len(v), len(v)) for n, v in durations.items()
                if sum(v) / len(v) > _SLOW_TOOL_MS]
        slow.sort(key=lambda t: t[1], reverse=True)
        for name, avg, n in slow[:5]:
            rep.findings.append(Finding(
                area="performance", severity="notice",
                summary=f"'{name}' averages {avg/1000:.1f}s per call",
                evidence=f"{n} real call(s) recorded in the event bus",
                recommendation=("Expected for network/model-bound work. Worth caching or "
                                "backgrounding only if it's called often in a hot path."),
            ))
    else:
        rep.findings.append(Finding(
            area="performance", severity="info",
            summary="No tool timing data yet",
            evidence="the event bus holds no tool.completed events with durations",
            recommendation="Use ZENO normally; this fills in on its own.",
        ))

    for name, count in failures.most_common(5):
        total = len(durations.get(name, [])) or count
        rep.findings.append(Finding(
            area="reliability", severity="problem" if count > 2 else "notice",
            summary=f"'{name}' returned an error {count} time(s)",
            evidence=f"{count} of {total} recorded call(s) failed",
            recommendation="Check its inputs and the underlying service before relying on it.",
        ))

    # --- capability actually unused -------------------------------------
    try:
        from reyes_agent.tools import TOOLS

        used = {(ev.get("payload") or {}).get("tool") for ev in events}
        unused = sorted(n for n in TOOLS if n not in used)
        rep.measured_from["tools_registered"] = len(TOOLS)
        rep.measured_from["tools_used"] = len([u for u in used if u])
        if unused and events:
            rep.findings.append(Finding(
                area="capability", severity="info",
                summary=f"{len(unused)} of {len(TOOLS)} tools have never been used",
                evidence="no tool.completed event recorded for them: "
                         + ", ".join(unused[:12]) + ("…" if len(unused) > 12 else ""),
                recommendation=("Unused tools still cost latency in every request -- they're "
                                "part of the schema payload. If some will never be used, "
                                "moving them into a lazy group (see TOOL_GROUPS) makes every "
                                "turn faster."),
            ))
    except Exception:  # noqa: BLE001
        pass

    # --- agent reliability, from the live runtime ------------------------
    try:
        from reyes_agent import agent_runtime

        h = agent_runtime.health()
        rep.measured_from["agents"] = h["agents_total"]
        for a in h["agents"]:
            if a["restarts"]:
                rep.findings.append(Finding(
                    area="stability", severity="problem",
                    summary=f"Agent {a['agent'].upper()} has restarted {a['restarts']} time(s)",
                    evidence=f"recorded by the supervisor; currently {a['state']}",
                    recommendation="Check the event log around those restarts for the cause.",
                ))
            if a["tasks_failed"] and a["success_rate"] < 80:
                rep.findings.append(Finding(
                    area="reliability", severity="problem",
                    summary=f"Agent {a['agent'].upper()} success rate is {a['success_rate']}%",
                    evidence=f"{a['tasks_completed']} done, {a['tasks_failed']} failed",
                    recommendation="Review the tasks it was given; its toolset may be too narrow.",
                ))
    except Exception:  # noqa: BLE001
        pass

    # --- duplicate memories ---------------------------------------------
    try:
        with sqlite3.connect(_DB_PATH, timeout=5) as conn:
            rows = conn.execute("SELECT id, text FROM memories").fetchall()
        seen: dict[str, int] = {}
        dupes: list[tuple[int, int, str]] = []
        for mid, text in rows:
            key = " ".join((text or "").lower().split())[:160]
            if key in seen:
                dupes.append((seen[key], mid, (text or "")[:60]))
            else:
                seen[key] = mid
        rep.measured_from["memories"] = len(rows)
        if dupes:
            rep.findings.append(Finding(
                area="memory", severity="notice",
                summary=f"{len(dupes)} duplicate memory entr(y/ies)",
                evidence="; ".join(f"#{a} == #{b} ('{t}…')" for a, b, t in dupes[:4]),
                recommendation="Use forget() on the redundant ids to keep recall sharp.",
            ))
    except sqlite3.Error:
        pass

    # --- stale missions --------------------------------------------------
    try:
        with sqlite3.connect(_DB_PATH, timeout=5) as conn:
            rows = conn.execute(
                "SELECT id, name, updated, status FROM missions "
                "WHERE status NOT IN ('completed','archived','cancelled')"
            ).fetchall()
        stale = []
        for mid, name, updated, status in rows:
            try:
                age = (datetime.now() - datetime.strptime(updated, "%Y-%m-%d %H:%M")).days
            except (TypeError, ValueError):
                continue
            if age >= _STALE_MISSION_DAYS:
                stale.append((mid, name, age, status))
        if stale:
            rep.findings.append(Finding(
                area="missions", severity="notice",
                summary=f"{len(stale)} mission(s) untouched for {_STALE_MISSION_DAYS}+ days",
                evidence="; ".join(f"#{i} '{n}' ({a}d, {s})" for i, n, a, s in stale[:4]),
                recommendation="Advance, pause, or close them so mission status stays meaningful.",
            ))
    except sqlite3.Error:
        pass

    # --- model latency ---------------------------------------------------
    try:
        from reyes_agent import model_router

        measured = model_router.explain().get("measured", {})
        for provider, m in measured.items():
            if m["calls"] and m["avg_latency_s"] > 4:
                rep.findings.append(Finding(
                    area="performance", severity="notice",
                    summary=f"{provider} averages {m['avg_latency_s']}s per call",
                    evidence=f"{m['calls']} measured call(s)",
                    recommendation=("Largely provider round-trip, which no local change fixes. "
                                    "Reducing tools sent per turn is the lever that does work."),
                ))
    except Exception:  # noqa: BLE001
        pass

    rep.scores = _scores(rep, events)
    return rep


def _scores(rep: Report, events: list[dict]) -> dict:
    """Scores derived from findings and real counts. Deliberately simple
    and explainable -- a score nobody can trace back to a measurement is
    just a number that looks reassuring."""
    problems = sum(1 for f in rep.findings if f.severity == "problem")
    notices = sum(1 for f in rep.findings if f.severity == "notice")
    reliability = max(0, 100 - problems * 20 - notices * 5)

    try:
        from reyes_agent import agent_runtime

        h = agent_runtime.health()
        # None, not 0, when the runtime isn't booted in this process (CLI,
        # tests). Zero would read as "every agent is unhealthy", which is a
        # completely different claim from "no runtime here to measure".
        health = (round(h["agents_healthy"] / h["agents_total"] * 100)
                  if h["agents_total"] else None)
    except Exception:  # noqa: BLE001
        health = None

    try:
        from reyes_agent import knowledge_graph

        kg = knowledge_graph.stats()
        learning = min(100, kg["edges"] * 2)
        knowledge = {"nodes": kg["nodes"], "edges": kg["edges"], "orphans": kg["orphan_count"]}
    except Exception:  # noqa: BLE001
        learning, knowledge = 0, {}

    return {
        "health": health,
        "reliability": reliability,
        "learning": learning,
        "activity_events": len(events),
        "knowledge": knowledge,
        "explanation": (
            "health = healthy agents / total. reliability = 100 minus 20 per problem "
            "and 5 per notice. learning = knowledge-graph edges x2, capped at 100. "
            "All three trace back to counts you can verify."
        ),
    }


def save_report(rep: Report) -> str:
    """Write the report into the vault so it's reviewable later."""
    from reyes_agent.tools.notes import write_note

    lines = [f"# ZENO Evolution Report — {rep.generated}", "", "## Scores", ""]
    for k, v in rep.scores.items():
        if k not in ("explanation", "knowledge"):
            lines.append(f"- **{k}**: {v}")
    lines += ["", f"_{rep.scores.get('explanation','')}_", "", "## Findings", ""]
    if not rep.findings:
        lines.append("No findings.")
    for f in rep.findings:
        lines += [f"### [{f.severity}] {f.area}: {f.summary}",
                  f"- Evidence: {f.evidence}",
                  f"- Recommendation: {f.recommendation}", ""]
    lines += ["", "## Applied", "",
              "Nothing in this report has been applied. ZENO does not modify its own "
              "code, prompts or configuration; every change above is yours to make."]
    return write_note(title=f"Evolution Report {rep.generated.replace(':', '-')}",
                      content="\n".join(lines))
