"""Ask ZENO what it actually observes and what it has learned.

Both tools exist so the owner can audit the awareness layer rather than
having to trust it. "What patterns have you learned about me?" should be
answerable with counts, and "what can't you see?" should be answerable
honestly.
"""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="current_situation_report",
    description=(
        "Report what ZENO can actually observe right now -- foreground app, how long "
        "it has been focused, idle time, running tasks, battery, next calendar event -- "
        "plus an explicit list of what it CANNOT sense. Use when the owner asks what "
        "you can see, what you know about right now, or whether you are watching him."
    ),
    input_schema={"type": "object", "properties": {}},
)
def current_situation_report() -> str:
    from reyes_agent import awareness

    situation = awareness.observe(force=True)
    lines = ["What I can observe right now:"]
    summary = situation.summary()
    lines.append(f"  {summary}" if summary else "  (nothing yet -- no samples)")

    detail = []
    if situation.app:
        detail.append(f"foreground: {situation.app}")
    if situation.focus_minutes is not None:
        detail.append(f"focused there {situation.focus_minutes:.0f}m")
    if situation.idle_seconds is not None:
        detail.append(f"idle {situation.idle_seconds:.0f}s")
    if situation.session_minutes is not None:
        detail.append(f"active stretch {situation.session_minutes:.0f}m")
    if situation.running_tasks:
        detail.append(f"{situation.running_tasks} task(s) running")
    if situation.battery_percent is not None:
        charge = "charging" if situation.battery_charging else "on battery"
        detail.append(f"battery {situation.battery_percent}% ({charge})")
    if detail:
        lines.append("  " + "; ".join(detail))

    if situation.unavailable:
        lines.append("Sensors not reporting: " + ", ".join(situation.unavailable))
    lines.append("What I cannot sense at all: " + "; ".join(awareness.cannot_sense()))
    return "\n".join(lines)


@register(
    name="learned_patterns",
    description=(
        "Report the habits ZENO has actually learned from observed activity -- which "
        "apps the owner usually uses at this hour, what typically follows what, and "
        "how much evidence each claim rests on. Use when he asks what you have learned "
        "about him, what you think he is about to do, or how well you know his routine."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hour": {"type": "integer", "description": "Hour 0-23 to ask about. Defaults to now."},
        },
    },
)
def learned_patterns(hour: int | None = None) -> str:
    from datetime import datetime

    from reyes_agent import anticipation, awareness

    ready = anticipation.readiness()
    lines = [
        f"Learned from {ready['total_samples']} real activity samples over "
        f"{ready['span_hours']:.0f} hours "
        f"({ready['slots_with_enough_evidence']} of {ready['slots_seen']} hour-slots have "
        f"enough evidence to predict from)."
    ]
    if not ready["ready"]:
        lines.append("That is not enough to claim I know your routine yet. "
                     "I will not guess from it.")
        return "\n".join(lines)

    target = datetime.now().hour if hour is None else max(0, min(23, int(hour)))
    weekday = datetime.now().weekday()
    prediction = anticipation.predict_app(weekday, target)
    if prediction:
        lines.append(f"Around {target:02d}:00 you are usually in {prediction.value} "
                     f"-- {prediction.confidence:.0%} ({prediction.basis}).")
    else:
        lines.append(f"I do not have enough samples at {target:02d}:00 to say anything useful.")

    situation = awareness.observe()
    if situation.app:
        following = anticipation.predict_next(situation.app)
        if following:
            lines.append(f"After {situation.app.replace('.exe','')} you usually move to "
                         f"{following.value} -- {following.confidence:.0%} ({following.basis}).")

    quiet = anticipation.quiet_hours()
    if quiet:
        # Group into CONTIGUOUS runs. Printing first-to-last collapsed
        # [0..8, 19..23] into "00:00-23:00", which reads as "you are never
        # active" -- the opposite of what the data says.
        runs: list[list[int]] = []
        for hour in quiet:
            if runs and hour == runs[-1][-1] + 1:
                runs[-1].append(hour)
            else:
                runs.append([hour])
        spans = ", ".join(f"{r[0]:02d}:00-{r[-1] + 1:02d}:00" if len(r) > 1 else f"{r[0]:02d}:00"
                          for r in runs)
        lines.append(f"You are rarely active {spans}, so I keep quiet then.")

    lines.append("These are counts from watching your foreground window, nothing more -- "
                 "I never learn from window titles or their contents.")
    return "\n".join(lines)
