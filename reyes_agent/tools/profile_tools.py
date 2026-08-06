"""Digital DNA (working-pattern profile) and Mission Simulation.

BOTH ARE COMPUTED FROM RECORDED DATA, NOT GUESSED
-------------------------------------------------
Digital DNA reads the real `activity_log` that activity_monitor has been
writing (foreground app sampled once a minute, idle samples excluded) and
the real event record. If there isn't enough data yet it says so and
reports how much it has, rather than producing a confident profile from
six samples.

Mission Simulation estimates from the user's OWN history -- how long
comparable missions actually took, how often campaigns of similar size
actually succeeded, measured agent durations. Where no comparable history
exists it says "no basis to estimate" instead of inventing a probability.
That distinction is the whole point: a made-up 87% success figure is worse
than an honest "I don't have data for this yet".
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime

from reyes_agent import config
from reyes_agent.tools import register

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_MIN_SAMPLES = 60          # ~1 hour of active samples before claiming a pattern


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=5)


@register(
    name="digital_dna",
    description=(
        "The user's real working-pattern profile, computed from recorded "
        "activity: most-used applications, most productive hours, typical "
        "session length, and what ZENO has actually been asked to do. Says "
        "plainly when there isn't enough data yet."
    ),
    input_schema={
        "type": "object",
        "properties": {"days": {"type": "integer", "description": "Look-back window. Default 14."}},
    },
    light=True,
)
def digital_dna(days: int = 14) -> str:
    days = max(1, min(365, int(days or 14)))
    # activity_log.ts is a UNIX timestamp (float), written by
    # activity_monitor as time.time(). An earlier version compared it with
    # julianday(), which silently matched nothing and made this report say
    # "not enough data" while 2000+ real samples sat in the table -- a
    # deceptive failure, because it looked like an empty profile rather
    # than a broken query. Compare timestamps directly.
    cutoff = time.time() - days * 86400
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT app, ts FROM activity_log WHERE ts >= ? AND idle = 0 ORDER BY ts",
                (cutoff,),
            ).fetchall()
    except sqlite3.Error as exc:
        return f"Activity history unavailable: {exc}"

    if len(rows) < _MIN_SAMPLES:
        return (f"Not enough activity recorded yet to describe a pattern -- {len(rows)} "
                f"sample(s) in the last {days} days, and I'd want at least {_MIN_SAMPLES} "
                "(each sample is one active minute). Leave ZENO running and this fills in. "
                "I'd rather say this than invent a profile from a handful of points.")

    apps = Counter()
    hours = Counter()
    per_day = defaultdict(int)
    for app, ts in rows:
        if not app:
            continue
        apps[app] += 1
        try:
            # ts is a float unix timestamp; accept an ISO string too in
            # case older rows were written differently.
            dt = (datetime.fromtimestamp(float(ts)) if isinstance(ts, (int, float))
                  else datetime.fromisoformat(str(ts)))
            hours[dt.hour] += 1
            per_day[dt.date().isoformat()] += 1
        except (TypeError, ValueError, OSError):
            continue

    total = sum(apps.values())
    lines = [f"DIGITAL DNA -- from {total} recorded active minutes over {len(per_day)} day(s)."]

    lines.append("\nMost-used applications:")
    for app, n in apps.most_common(6):
        lines.append(f"  {app}: {n} min ({n / total * 100:.0f}%)")

    if hours:
        peak = sorted(hours.items(), key=lambda kv: kv[1], reverse=True)[:3]
        lines.append("\nMost active hours:")
        for h, n in peak:
            lines.append(f"  {h:02d}:00-{h:02d}:59 — {n} min")

    if per_day:
        avg = total / len(per_day)
        busiest = max(per_day.items(), key=lambda kv: kv[1])
        lines.append(f"\nAverage active time per recorded day: {avg:.0f} min")
        lines.append(f"Busiest day: {busiest[0]} ({busiest[1]} min)")

    # What ZENO has actually been used for -- from the durable event record.
    try:
        from reyes_agent import event_bus

        tools_used = Counter()
        for ev in event_bus.history(limit=1000, event_type="tool"):
            t = (ev.get("payload") or {}).get("tool")
            if t:
                tools_used[t] += 1
        if tools_used:
            lines.append("\nWhat ZENO is most used for:")
            for t, n in tools_used.most_common(6):
                lines.append(f"  {t}: {n}x")
    except Exception:  # noqa: BLE001
        pass

    lines.append("\nThis is a description of recorded behaviour, not a judgement, "
                 "and nothing here changes ZENO's behaviour on its own.")
    return "\n".join(lines)


@register(
    name="evolution_report",
    description=(
        "ZENO analyses its own real performance -- slow tools, failing "
        "tools, unused capability, agent restarts, duplicate memories, "
        "stale missions, model latency -- and proposes improvements. "
        "Nothing is applied automatically. Use when the user asks how ZENO "
        "is doing, what could be faster, or for an evolution/health report."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "save": {"type": "boolean", "description": "Also save the report into the vault."},
        },
    },
)
def evolution_report(save: bool = False) -> str:
    from reyes_agent import evolution

    rep = evolution.analyse()
    s = rep.scores
    lines = [
        f"EVOLUTION REPORT — {rep.generated}",
        f"  Health {s['health']}/100" if s.get("health") is not None
        else "  Health n/a (agent runtime not running in this process)",
        f"  Reliability {s.get('reliability', 0)}/100 · Learning {s.get('learning', 0)}/100",
        f"  Measured from: " + ", ".join(f"{k}={v}" for k, v in rep.measured_from.items()),
        "",
    ]
    problems = [f for f in rep.findings if f.severity == "problem"]
    notices = [f for f in rep.findings if f.severity == "notice"]
    infos = [f for f in rep.findings if f.severity == "info"]

    for label, group in (("PROBLEMS", problems), ("WORTH ATTENTION", notices), ("NOTES", infos)):
        if not group:
            continue
        lines.append(f"{label}:")
        for f in group:
            lines.append(f"  [{f.area}] {f.summary}")
            lines.append(f"     evidence: {f.evidence}")
            lines.append(f"     suggest:  {f.recommendation}")
        lines.append("")

    if not rep.findings:
        lines.append("No findings — but that may mean not enough has been recorded yet, "
                     "not that everything is perfect.")

    if save:
        lines.append(evolution.save_report(rep))

    lines.append(f"\n{len(problems)} problem(s), {len(notices)} worth attention. "
                 "NOTHING here has been applied — ZENO does not modify its own code, "
                 "prompts or configuration. Ask if you want any of it done.")
    lines.append(f"\n({s.get('explanation','')})")
    return "\n".join(lines)


@register(
    name="digital_dna_control",
    description=(
        "View, export, reset or disable the working-pattern profile "
        "(Digital DNA). Use when the user asks what ZENO has learned about "
        "them, or wants that data removed or turned off."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "export", "reset", "disable", "enable"]},
        },
        "required": ["action"],
    },
    light=True,
)
def digital_dna_control(action: str) -> str:
    """Privacy controls. Reset genuinely deletes the recorded activity --
    it does not merely hide it, because 'delete' has to mean delete."""
    act = action.strip().lower()
    flag = config.VAULT_PATH / "07-System" / "dna_disabled.flag"

    if act == "status":
        disabled = flag.exists()
        try:
            with _connect() as conn:
                n = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
                oldest = conn.execute("SELECT MIN(ts) FROM activity_log").fetchone()[0]
        except sqlite3.Error:
            n, oldest = 0, None
        return (f"Digital DNA is {'DISABLED' if disabled else 'ENABLED'}.\n"
                f"  Recorded: {n} active-minute sample(s)"
                + (f", oldest {oldest}" if oldest else "") + "\n"
                "  Stored locally in your vault only; nothing is uploaded.\n"
                "  Actions: export (write to a note), reset (delete it all), "
                "disable (stop recording).")

    if act == "export":
        try:
            with _connect() as conn:
                rows = conn.execute(
                    "SELECT app, ts FROM activity_log ORDER BY ts").fetchall()
        except sqlite3.Error as exc:
            return f"Could not read activity: {exc}"
        if not rows:
            return "Nothing recorded to export."
        from reyes_agent.tools.obsidian import write_note

        body = ["# Digital DNA export", "", f"{len(rows)} samples", "", "| app | timestamp |", "|---|---|"]
        body += [f"| {a} | {t} |" for a, t in rows[-2000:]]
        return write_note(title="Digital DNA export", content="\n".join(body))

    if act == "reset":
        try:
            with _connect() as conn:
                n = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]
                conn.execute("DELETE FROM activity_log")
            return (f"Deleted {n} activity sample(s). The behaviour profile is now empty "
                    "and will rebuild only if recording stays enabled.")
        except sqlite3.Error as exc:
            return f"Could not reset: {exc}"

    if act in ("disable", "enable"):
        try:
            flag.parent.mkdir(parents=True, exist_ok=True)
            if act == "disable":
                flag.write_text("Digital DNA recording disabled by the user.", encoding="utf-8")
                return ("Digital DNA recording disabled. Existing samples are kept — "
                        "use reset if you want them deleted too.")
            flag.unlink(missing_ok=True)
            return "Digital DNA recording enabled."
        except OSError as exc:
            return f"Could not change the setting: {exc}"

    return "action must be status, export, reset, disable or enable."


@register(
    name="simulate_mission",
    description=(
        "Estimate what a piece of work will take BEFORE starting it, based "
        "on the user's own history: how long comparable missions actually "
        "took, real agent durations, and real campaign outcomes. States "
        "plainly when there's no comparable history to estimate from."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What the work involves."},
            "mission_type": {"type": "string", "description": "e.g. research, project, campaign, learning."},
            "steps": {"type": "integer", "description": "Rough number of discrete actions, if known."},
        },
        "required": ["description"],
    },
    light=True,
)
def simulate_mission(description: str, mission_type: str = "", steps: int = 0) -> str:
    lines = [f"SIMULATION -- {description[:100]}"]
    basis: list[str] = []

    # 1. Comparable missions the user actually completed.
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT name, status, progress, created, updated, mission_type FROM missions"
            ).fetchall()
    except sqlite3.Error:
        rows = []

    same_type = [r for r in rows if mission_type and r[5] == mission_type.strip().lower()]
    completed = [r for r in (same_type or rows) if r[1] == "completed"]
    if completed:
        durations = []
        for _, _, _, created, updated, _ in completed:
            try:
                d = (datetime.fromisoformat(updated) - datetime.fromisoformat(created)).total_seconds() / 3600
                if d >= 0:
                    durations.append(d)
            except (TypeError, ValueError):
                continue
        if durations:
            avg = sum(durations) / len(durations)
            lines.append(f"  Comparable completed missions: {len(durations)}")
            lines.append(f"  They actually took: {min(durations):.1f}h to {max(durations):.1f}h (avg {avg:.1f}h)")
            basis.append(f"{len(durations)} completed mission(s)")

    # 2. Real per-agent durations from the live runtime.
    try:
        from reyes_agent import agent_runtime

        h = agent_runtime.health()
        active = [a for a in h["agents"] if a["tasks_completed"]]
        if active:
            avg_task = sum(a["avg_duration_s"] for a in active) / len(active)
            lines.append(f"  Measured agent task time: {avg_task:.1f}s average across "
                         f"{sum(a['tasks_completed'] for a in active)} real task(s)")
            if steps:
                lines.append(f"  {steps} step(s) at that rate: roughly {steps * avg_task / 60:.1f} min of agent time")
            basis.append("measured agent durations")
    except Exception:  # noqa: BLE001
        pass

    # 3. Real campaign outcomes.
    try:
        from reyes_agent import campaigns

        camps = campaigns.list_campaigns(50)
        finished = [c for c in camps if c["total"]]
        if finished:
            done = sum(c["done"] for c in finished)
            tot = sum(c["total"] for c in finished)
            lines.append(f"  Campaign history: {done}/{tot} actions completed "
                         f"({done / tot * 100:.0f}%) across {len(finished)} campaign(s)")
            basis.append(f"{len(finished)} campaign(s)")
    except Exception:  # noqa: BLE001
        pass

    if not basis:
        lines.append("  No comparable history yet, so there is NO honest basis for a")
        lines.append("  duration or success estimate. I'm not going to invent one.")
        lines.append("  Run a few missions of this kind and this becomes real.")
    else:
        lines.append(f"\n  Estimate basis: {', '.join(basis)}.")
        lines.append("  These are extrapolations from your own history, not predictions. "
                     "Nothing here accounts for a problem neither of us has hit yet.")

    lines.append("\n  Risks worth naming before starting:")
    lines.append("    - Anything touching other people (email, messages, posts) can't be undone.")
    lines.append("    - Long batches should run as a Campaign so they can be paused mid-flight.")
    return "\n".join(lines)
