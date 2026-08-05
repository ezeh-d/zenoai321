"""Morning Companion, webcam presence check, and workspace resume.

All three read real state. None of them invent a number, and each says
plainly when it has nothing to report rather than filling the gap with
something plausible.
"""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta

from reyes_agent import config
from reyes_agent.tools import register

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_BRIEF_MARK = config.VAULT_PATH / "07-System" / "last_morning_brief.txt"


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=5)


# --------------------------------------------------------------------------
# Morning Companion
# --------------------------------------------------------------------------
@register(
    name="morning_brief",
    description=(
        "The morning companion briefing: what happened yesterday, what's "
        "open today (missions, calendar, approvals, unread-ish signals), "
        "and one suggested starting point. Built from real records. Use "
        "when the user says good morning, asks how today looks, or asks "
        "what they should start with."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "force": {"type": "boolean", "description": "Give it again even if already delivered today."},
        },
    },
    light=True,
)
def morning_brief(force: bool = False) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    if not force:
        try:
            if _BRIEF_MARK.read_text(encoding="utf-8").strip() == today:
                return ("Already gave the morning brief today. Say so if you want it "
                        "again -- call this with force=true.")
        except OSError:
            pass

    now = datetime.now()
    hour = now.hour
    greeting = ("Good morning" if 4 <= hour < 12 else
                "Good afternoon" if hour < 18 else "Good evening")
    lines = [f"{greeting}, {config.USER_NAME}. {now.strftime('%A %d %B')}."]

    # --- yesterday, from real activity ----------------------------------
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        cutoff = time.time() - 48 * 3600
        with _connect() as conn:
            rows = conn.execute(
                "SELECT app, ts FROM activity_log WHERE ts >= ? AND idle = 0", (cutoff,)
            ).fetchall()
        y_apps = Counter()
        y_total = 0
        for app, ts in rows:
            try:
                d = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                continue
            if d == yesterday and app:
                y_apps[app] += 1
                y_total += 1
        if y_total:
            top = ", ".join(f"{a} ({n}m)" for a, n in y_apps.most_common(3))
            lines.append(f"\nYesterday: {y_total} active minutes — mostly {top}.")
    except sqlite3.Error:
        pass

    # --- open missions ---------------------------------------------------
    try:
        from reyes_agent.tools.missions import list_missions_dicts

        missions = list_missions_dicts()
        if missions:
            lines.append(f"\nOpen missions ({len(missions)}):")
            for m in missions[:4]:
                lines.append(f"  #{m['id']} {m['name']} — {m['progress']}%, {m['status']}"
                             + (f", due {m['deadline']}" if m.get("deadline") else ""))
        else:
            lines.append("\nNo open missions.")
    except Exception:  # noqa: BLE001
        missions = []

    # --- today's calendar -------------------------------------------------
    try:
        from reyes_agent.tools.calendar import list_calendar_events

        cal = list_calendar_events()
        if cal and "no " not in cal.lower()[:20]:
            lines.append("\nCalendar:")
            lines.append("  " + cal.replace("\n", "\n  ")[:400])
    except Exception:  # noqa: BLE001
        pass

    # --- things genuinely waiting on the user ------------------------------
    waiting = []
    try:
        from reyes_agent import confirmation, heartbeat

        p = len(confirmation.list_pending())
        n = len(heartbeat.list_notices())
        if p:
            waiting.append(f"{p} action(s) awaiting your approval")
        if n:
            waiting.append(f"{n} notice(s) from while you were away")
    except Exception:  # noqa: BLE001
        pass
    if waiting:
        lines.append("\nWaiting on you: " + "; ".join(waiting) + ".")

    # --- one concrete suggestion, drawn from what's actually there ---------
    suggestion = None
    try:
        stale = [m for m in missions if m["progress"] < 100 and m["status"] in ("planning", "building", "researching")]
        if stale:
            s = sorted(stale, key=lambda m: m["progress"])[0]
            suggestion = f"pick up mission #{s['id']} '{s['name']}' — it's at {s['progress']}%"
    except Exception:  # noqa: BLE001
        pass
    if not suggestion and waiting:
        suggestion = "clear what's waiting for your approval first"
    lines.append("\nSuggested start: " + (suggestion or "nothing pressing on record — your call."))

    try:
        _BRIEF_MARK.parent.mkdir(parents=True, exist_ok=True)
        _BRIEF_MARK.write_text(today, encoding="utf-8")
    except OSError:
        pass

    lines.append("\n(Read this to the user conversationally — don't just list it back.)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Webcam presence
# --------------------------------------------------------------------------
@register(
    name="check_presence",
    description=(
        "Check whether the user seems to be at the desk right now, from "
        "keyboard/mouse idle time plus webcam MOTION (not face "
        "recognition -- it does not identify anyone). Frames are compared "
        "in memory and discarded; nothing is saved or sent anywhere. Use "
        "before a long proactive message, or when asked if ZENO can tell "
        "you're there."
    ),
    input_schema={"type": "object", "properties": {}},
)
def check_presence() -> str:
    """Presence from input idle time + webcam motion.

    NOT face detection, and the description says so. OpenCV 5 dropped
    `CascadeClassifier` from the main namespace and ships no Haar cascade
    files, and the DNN detector needs a model this install doesn't have
    (verified 2026-08-05). Rather than claim a capability that isn't
    there, this measures what genuinely can be measured: whether the
    picture changed between two frames.

    Deliberately never saves a frame. A presence check that quietly wrote
    photos of the user to disk would be a different feature from the one
    described.
    """
    idle = None
    idle_note = ""
    try:
        from reyes_agent.activity_monitor import _idle_seconds

        idle = _idle_seconds()
        idle_note = f"Input idle {int(idle)}s."
    except Exception:  # noqa: BLE001
        pass

    # Input activity alone is decisive when it's recent -- no reason to
    # power up a camera to learn something the OS already knows.
    if idle is not None and idle < 25:
        return f"You're here — active at the keyboard/mouse. {idle_note} (No camera used.)"

    motion = None
    detail = ""
    cap = None
    try:
        import cv2

        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            detail = "camera unavailable (in use by another app, or none attached)"
        else:
            cap.read()  # first frame after wake is often black; discard it
            time.sleep(0.35)
            ok1, f1 = cap.read()
            time.sleep(0.45)
            ok2, f2 = cap.read()
            if not (ok1 and ok2) or f1 is None or f2 is None:
                detail = "couldn't read frames from the camera"
            else:
                g1 = cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY)
                g2 = cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY)
                diff = cv2.absdiff(g1, g2)
                motion = float(diff.mean())
    except ImportError:
        detail = "OpenCV not installed"
    except Exception as exc:  # noqa: BLE001
        detail = f"camera check failed ({type(exc).__name__})"
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:  # noqa: BLE001
            pass

    if motion is None:
        base = f"Can't check the camera — {detail}."
        if idle is None:
            return base + " No presence signal available at all."
        return (f"{base} Going on input only: {idle_note} "
                + ("Probably away." if idle > 300 else "Probably nearby but not typing."))

    # ~1.5 mean absolute difference is well above sensor noise on a static
    # scene and below what a moving person produces.
    moving = motion > 1.5
    verdict = ("Someone's moving in front of the camera — you're there."
               if moving else
               "No movement in view — you're probably away.")
    return (f"{verdict} {idle_note} (motion index {motion:.2f}; "
            "movement only, not face recognition — frames compared in "
            "memory and discarded, nothing saved.)")


# --------------------------------------------------------------------------
# Workspace resume
# --------------------------------------------------------------------------
@register(
    name="resume_workspace",
    description=(
        "Work out what the user was last doing and offer to set it back "
        "up: the apps they had open, the mission they were on, and files "
        "recently touched. With apply=true it reopens those applications. "
        "Use for 'where was I', 'carry on from yesterday', or after a "
        "restart."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "apply": {"type": "boolean", "description": "True actually reopens the applications. Default false (just report)."},
            "max_apps": {"type": "integer", "description": "How many apps to reopen. Default 3."},
        },
    },
)
def resume_workspace(apply: bool = False, max_apps: int = 3) -> str:
    """Reconstruct the last working context from recorded activity."""
    # --- what was actually open, in the last active stretch ---------------
    apps: list[str] = []
    last_seen = None
    try:
        cutoff = time.time() - 72 * 3600
        with _connect() as conn:
            rows = conn.execute(
                "SELECT app, ts FROM activity_log WHERE ts >= ? AND idle = 0 ORDER BY ts DESC",
                (cutoff,),
            ).fetchall()
        if rows:
            last_seen = float(rows[0][1])
            # The "session" = samples within 2h of the most recent one.
            window = [a for a, t in rows if last_seen - float(t) <= 7200 and a]
            counted = Counter(window)
            # Skip ZENO's own processes -- reopening ourselves is noise.
            skip = {"pythonw.exe", "python.exe", "claude.exe", "conhost.exe", "explorer.exe"}
            apps = [a for a, _ in counted.most_common(12) if a.lower() not in skip]
    except sqlite3.Error as exc:
        return f"Activity history unavailable: {exc}"

    if not apps:
        return ("No recent desktop activity on record, so there's nothing to resume. "
                "(Activity recording may be disabled — check digital_dna_control.)")

    ago = ""
    if last_seen:
        mins = int((time.time() - last_seen) / 60)
        ago = f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago"

    lines = [f"Last working session ({ago}):", "  Apps: " + ", ".join(apps[:6])]

    # --- what mission was live ---------------------------------------------
    try:
        from reyes_agent.tools.missions import list_missions_dicts

        ms = list_missions_dicts()
        if ms:
            m = ms[0]
            lines.append(f"  Mission: #{m['id']} {m['name']} ({m['progress']}%, {m['status']})")
    except Exception:  # noqa: BLE001
        pass

    # --- files recently touched in the vault --------------------------------
    try:
        recent = sorted(
            (p for p in config.VAULT_PATH.rglob("*.md") if p.is_file()),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )[:3]
        if recent:
            lines.append("  Recent notes: " + ", ".join(p.stem for p in recent))
    except OSError:
        pass

    if not apply:
        lines.append(f"\nSay the word and I'll reopen the top {min(max_apps, len(apps))}: "
                     + ", ".join(apps[:max_apps]))
        return "\n".join(lines)

    # --- actually reopen ----------------------------------------------------
    from reyes_agent.tools.system import open_app

    opened, failed = [], []
    for app in apps[:max(1, min(8, int(max_apps or 3)))]:
        name = app[:-4] if app.lower().endswith(".exe") else app
        result = open_app(name)
        (opened if not result.lower().startswith(("error", "couldn't", "no ")) else failed).append(name)
    lines.append("")
    if opened:
        lines.append("Reopened: " + ", ".join(opened))
    if failed:
        lines.append("Couldn't open: " + ", ".join(failed) + " (not found by name)")
    return "\n".join(lines)
