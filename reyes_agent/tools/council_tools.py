"""Agent-facing tools for the Advisory Council (reyes_agent/council.py)
and the live System Monitor.

Kept together because both are read-only reporting surfaces over
subsystems that live outside tools/.
"""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="convene_council",
    description=(
        "Convene the Advisory Council on an important decision: several "
        "independent advisors analyse it in isolation from their own "
        "sourced doctrine, a skeptic attacks the result, and citations are "
        "verified. Use for genuinely consequential choices (strategy, "
        "architecture, business direction, big commitments) -- NOT for "
        "ordinary questions, it costs several model calls."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The decision to put to the council."},
            "context": {"type": "string", "description": "Relevant facts: constraints, numbers, current situation."},
        },
        "required": ["question"],
    },
)
def convene_council(question: str, context: str = "") -> str:
    from reyes_agent import council

    m = council.hold_meeting(question, context)
    if m.get("error"):
        return f"Council unavailable: {m['error']}"

    out = [f"ADVISORY COUNCIL -- {m['question']}", ""]
    for o in m["opinions"]:
        if o.get("error"):
            out.append(f"## {o['name']}: unavailable ({o['error']})\n")
            continue
        out.append(f"## {o['name']}")
        out.append(o["opinion"])
        if o["fabricated"]:
            out.append(f"  !! stripped fabricated citation(s): {', '.join(o['fabricated'])}")
        out.append("")

    out.append("## ULTRON (independent skeptic)")
    out.append(m["skeptic"])
    out.append("")

    a = m["analysis"]
    out.append("## Meeting quality")
    out.append(f"  advisors responded: {a['advisors_responded']} (failed: {a['advisors_failed']})")
    out.append(f"  evidence: {a['evidence_quality']}")
    if a["fabricated_citations"]:
        out.append(f"  FABRICATED CITATIONS CAUGHT: {a['fabricated_citations']}")
    for w in m.get("warnings", []):
        out.append(f"  warning: {w}")
    out.append("")
    out.append(
        "Synthesise these into ONE recommendation in your own voice for the "
        "user: where advisors agree, where they genuinely conflict and why, "
        "what the skeptic exposed, what you'd do, and what would change that. "
        "Do not just repeat each advisor in turn."
    )
    return "\n".join(out)


@register(
    name="list_council_advisors",
    description="List the installed Advisory Council advisors, their domains, and how many sourced doctrine entries each holds.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def list_council_advisors() -> str:
    from reyes_agent import council

    dossiers, warnings = council.load_dossiers()
    if not dossiers and not warnings:
        return "No advisor dossiers installed."
    lines = []
    for d in dossiers.values():
        lines.append(f"- {d.name} ({d.advisor_id}): {d.role}")
        lines.append(f"    domains: {', '.join(d.domains[:8])}")
        lines.append(f"    doctrine entries: {len(d.doctrine)}")
    for w in warnings:
        lines.append(f"  DISABLED -- {w}")
    return "\n".join(lines)


@register(
    name="list_council_meetings",
    description="List past Advisory Council meetings, including any real-world outcome recorded against them.",
    input_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "How many. Default 10."}},
    },
    light=True,
)
def list_council_meetings(limit: int = 10) -> str:
    from reyes_agent import council

    rows = council.list_meetings(limit)
    if not rows:
        return "No council meetings yet."
    return "\n".join(
        f"#{r['id']} ({r['created']}) {r['question'][:80]}"
        + (f"\n    outcome: {r['outcome']}" if r["outcome"] else "")
        for r in rows
    )


@register(
    name="record_council_outcome",
    description=(
        "Record what actually happened after a council meeting, so its "
        "advice can later be compared against reality."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "meeting_id": {"type": "integer"},
            "outcome": {"type": "string", "description": "What actually happened."},
        },
        "required": ["meeting_id", "outcome"],
    },
    light=True,
)
def record_council_outcome(meeting_id: int, outcome: str) -> str:
    from reyes_agent import council

    ok = council.record_outcome(meeting_id, outcome)
    return f"Outcome recorded on meeting #{meeting_id}." if ok else f"No meeting #{meeting_id}."


@register(
    name="permission_status",
    description=(
        "Show this installation's permission policy: which capabilities "
        "run freely, which need confirmation, and which are blocked. Use "
        "when the user asks what ZENO is allowed to do."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def permission_status() -> str:
    from reyes_agent import permissions

    d = permissions.describe()
    lines = [f"Installation profile: {d['profile']}", f"  {d['profile_note']}", ""]
    for group, label in (("enabled", "Runs freely"), ("confirm", "Asks first"), ("blocked", "Never")):
        caps = [c for c in d["capabilities"] if c["state"] == group]
        if not caps:
            continue
        lines.append(f"{label}:")
        for c in caps:
            note = ""
            if c["locked"]:
                note = "  (locked -- not configurable)"
            elif c["overridden"]:
                note = "  (overridden in .env)"
            lines.append(f"  - {c['name']}: {c['description']}{note}")
        lines.append("")
    return "\n".join(lines).strip()


@register(
    name="list_plugins",
    description="List installed plugins, the permissions each declares, and whether it is approved to load.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def list_plugins() -> str:
    from reyes_agent import config as _config
    from reyes_agent import permissions

    plugin_dir = _config.VAULT_PATH / "07-System" / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(plugin_dir.glob("*.py"))
    if not files:
        return ("No plugins installed. Drop a .py file plus a matching .json manifest "
                f"into {plugin_dir} to add one.")
    lines = []
    for p in files:
        m = permissions.load_manifest(p)
        ok, reason = permissions.may_load_plugin(m, p.stem)
        status = "LOADED" if ok else "REFUSED"
        if m:
            lines.append(f"- {m.name} v{m.version} by {m.author} [{status}]")
            lines.append(f"    {m.description}")
            lines.append(f"    permissions: {', '.join(m.permissions) or 'none'}")
        else:
            lines.append(f"- {p.stem} [{status}]")
        if not ok:
            lines.append(f"    {reason}")
    return "\n".join(lines)


@register(
    name="trust_plugin",
    description=(
        "Approve a plugin to load, at its current version. Show the user "
        "the plugin's declared permissions from list_plugins and get their "
        "explicit agreement first -- an approved plugin runs arbitrary code "
        "with ZENO's permissions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Plugin name from its manifest."},
            "version": {"type": "string", "description": "Version being approved."},
        },
        "required": ["name", "version"],
    },
)
def trust_plugin(name: str, version: str) -> str:
    from reyes_agent import permissions

    permissions.trust_plugin(name.strip(), str(version).strip())
    return (f"Plugin '{name}' v{version} approved. It will load on the next restart. "
            "A version change will require approval again.")


@register(
    name="revoke_plugin",
    description="Withdraw approval from a plugin so it stops loading.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
def revoke_plugin(name: str) -> str:
    from reyes_agent import permissions

    ok = permissions.revoke_plugin(name.strip())
    return (f"Plugin '{name}' approval withdrawn; it won't load after restart."
            if ok else f"Plugin '{name}' wasn't approved anyway.")


@register(
    name="agent_roll_call",
    description=(
        "Have every specialist introduce itself out loud, each in its own "
        "voice. Use when the user asks for a roll call, team introduction, "
        "or to meet the agents. Takes about a minute of speech."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "full": {"type": "boolean", "description": "True for full role introductions, false (default) for brief name-only lines."}
        },
    },
    light=True,
)
def agent_roll_call(full: bool = False) -> str:
    from reyes_agent import notification_bus, voice_manager

    seq = voice_manager.roll_call_sequence(full=bool(full))
    # The panel plays this; server-side audio would come out of the wrong
    # machine's speakers when the panel is open on a phone.
    notification_bus.publish({"type": "roll_call", "sequence": seq})
    names = ", ".join(s["agent"].upper().replace("_COMM", "") for s in seq[1:-1])
    return (f"Roll call started -- {len(seq) - 2} specialists introducing themselves "
            f"in their own voices ({names}). Say nothing further; the panel is speaking now.")


@register(
    name="executive_meeting",
    description=(
        "Hold an executive meeting: every specialist reports its REAL "
        "runtime status out loud in its own voice (state, tasks completed, "
        "success rate, queue), then ZENO summarises. Use when the user asks "
        "for a status meeting, team report, or whether all agents are OK."
    ),
    input_schema={"type": "object", "properties": {}},
)
def executive_meeting() -> str:
    from reyes_agent import agent_runtime, notification_bus, voice_manager

    h = agent_runtime.health()
    if not h["agents"]:
        return "The Agent Runtime isn't running, so there is no live status to report."

    seq = [{"agent": "zeno", "text": "Convening the executive meeting. Status reports, please."}]
    lines = []
    for a in h["agents"]:
        aid = a["agent"]
        if aid not in voice_manager.INTRODUCTIONS:
            continue  # atlas has no voice profile; skip rather than fake one
        # Every number here is observed from the runtime, never invented.
        if not a["healthy"]:
            spoken = f"{aid.upper().replace('_COMM','')} reporting. Status degraded. Heartbeat stale."
        elif a["tasks_completed"] or a["tasks_failed"]:
            spoken = (f"{aid.upper().replace('_COMM','')} online. "
                      f"{a['tasks_completed']} task{'s' if a['tasks_completed'] != 1 else ''} completed, "
                      f"{a['success_rate']:.0f} percent success.")
        else:
            spoken = f"{aid.upper().replace('_COMM','')} online and idle. No tasks yet."
        seq.append({"agent": aid, "text": spoken})
        lines.append(f"  {aid.upper().replace('_COMM','')}: {a['state']}, "
                     f"{a['tasks_completed']} done / {a['tasks_failed']} failed, "
                     f"queue {a['queue_depth']}, heartbeat {a['heartbeat_age_s']}s ago")

    closing = (f"All {h['agents_alive']} specialists online and healthy."
               if h["all_online"] else
               f"{h['agents_healthy']} of {h['agents_total']} healthy. Attention required.")
    seq.append({"agent": "zeno", "text": closing})
    notification_bus.publish({"type": "roll_call", "sequence": seq})

    return ("EXECUTIVE MEETING -- live runtime status (each agent is speaking now "
            "in its own voice):\n" + "\n".join(lines) +
            f"\n\nRuntime: {h['agents_alive']}/{h['agents_total']} alive, "
            f"{h['agents_healthy']} healthy, supervisor "
            f"{'up' if h['supervisor_alive'] else 'DOWN'}, uptime {h['uptime_s']}s, "
            f"{h['queued_tasks']} queued.\nSummarise this for the user in one or two sentences.")


@register(
    name="agent_status",
    description=(
        "Real health check of the Agent Runtime -- which specialists are "
        "alive, healthy, working, and their metrics. Use whenever the user "
        "asks if agents are online. Reports observed state only."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def agent_status() -> str:
    from reyes_agent import agent_runtime

    h = agent_runtime.health()
    if not h["agents"]:
        return "Agent Runtime is not running -- no workers have been started."
    lines = [
        f"Agent Runtime: {h['agents_alive']}/{h['agents_total']} alive, {h['agents_healthy']} healthy, "
        f"supervisor {'up' if h['supervisor_alive'] else 'DOWN'}, uptime {h['uptime_s']}s.",
    ]
    if h["working_now"]:
        lines.append(f"Working right now: {', '.join(h['working_now'])}")
    unhealthy = [a for a in h["agents"] if not a["healthy"]]
    if unhealthy:
        lines.append("UNHEALTHY:")
        lines.extend(f"  {a['agent']}: state={a['state']} alive={a['alive']} "
                     f"heartbeat {a['heartbeat_age_s']}s ago" for a in unhealthy)
    else:
        lines.append("All workers healthy (live threads, fresh heartbeats).")
    busy = [a for a in h["agents"] if a["tasks_completed"] or a["tasks_failed"]]
    if busy:
        lines.append("Activity this session:")
        lines.extend(f"  {a['agent']}: {a['tasks_completed']} done, {a['tasks_failed']} failed, "
                     f"avg {a['avg_duration_s']}s, {a['restarts']} restart(s)" for a in busy)
    return "\n".join(lines)


@register(
    name="agent_introduction",
    description=(
        "Have ONE specialist introduce itself or state its role, in its own "
        "voice. Use when the user addresses an agent directly, e.g. 'TOSIN, "
        "what is your role?' or 'introduce STARK'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "aris|tosin|stark|zeal|titan|apex|nova|hermes_comm|oracle|atlas|ultron|kate|helios"},
        },
        "required": ["agent"],
    },
    light=True,
)
def agent_introduction(agent: str) -> str:
    from reyes_agent import notification_bus, voice_manager

    a = (agent or "").strip().lower()
    text = voice_manager.INTRODUCTIONS.get(a)
    if not text:
        return f"No specialist called '{agent}'. Available: {', '.join(voice_manager.INTRODUCTIONS)}."
    voice_manager.mark_introduced(a)
    notification_bus.publish({"type": "roll_call", "sequence": [{"agent": a, "text": text}]})
    return f"{a.upper().replace('_COMM','')} is introducing itself in its own voice: \"{text}\""


@register(
    name="enable_tools",
    description=(
        "Load an additional group of tools for this turn when the request "
        "needs them. Groups: missions (update/inspect a mission), campaigns "
        "(build/approve/run a batch), investing (portfolio policy, trades, "
        "performance), council (advisor list, past meetings), work (job/"
        "freelance/content tracker), career (verified career profile and safe "
        "platform plan), paid_work (opportunities, applications, clients, contracts, "
        "projects, delivery and payment tracking), creative (image, 3D, canvas), comms "
        "(calendar, read email), admin (plugins, permissions, voices, vault "
        "maintenance, scheduled checks), intelligence (undo history, "
        "situation, universal search, simulation, Health Center, personal "
        "relationship graph and mission-resume state), phase3 (episodic history, "
        "structured documents, temporal graph, engineering/device/sandbox status), "
        "analytics (read-only CSV/JSON/Parquet analysis), and phase5 (private "
        "network and optional integration status), or extended (less-common legacy "
        "desktop, browser, memory, media, file and diagnostics operations). Use "
        "extended only when no compact entry point covers the request. "
        "Call this FIRST when a request "
        "clearly needs one of those, then use the tools it unlocks."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "group": {
                "type": "string",
                "enum": ["missions", "campaigns", "investing", "opportunity", "council", "work", "career", "paid_work",
                          "creative", "comms", "admin", "intelligence", "phase3",
                          "analytics", "phase5", "extended"],
            }
        },
        "required": ["group"],
    },
    light=True,
)
def enable_tools(group: str) -> str:
    """Handled specially by agent.py, which widens the toolset for the rest
    of the turn. The registered function still returns a real result so any
    other caller (a sub-agent, a direct call) gets a sensible answer."""
    from reyes_agent.tools import GROUP_NAMES, TOOLS, ensure_plugins_loaded, group_of

    g = (group or "").strip().lower()
    if g not in GROUP_NAMES:
        return f"Unknown group '{group}'. Available: {', '.join(GROUP_NAMES)}."
    if g in {"admin", "extended"}:
        ensure_plugins_loaded()
    names = sorted(n for n in TOOLS if group_of(n) == g)
    return f"Loaded the '{g}' tools: {', '.join(names)}. Use them now."


@register(
    name="voice_diagnostics",
    description=(
        "Check the agent voice setup: which specialists have their own "
        "ElevenLabs voice, which fall back to ZENO's, and whether any "
        "configured voice id is missing or invalid on the account. Use "
        "when the user asks about voices or reports speech problems."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def voice_diagnostics() -> str:
    from reyes_agent import voice_manager

    d = voice_manager.diagnose()
    if not d["elevenlabs_configured"]:
        return "ElevenLabs is not configured -- speech falls back to the browser voice."
    lines = [d.get("summary", "")]
    if d.get("account_voices") is not None:
        lines.append(f"Voices on the account: {d['account_voices']}")
    lines.append("")
    for a in d["agents"]:
        mark = {"ok": "own voice", "fallback": "falls back to ZENO",
                "invalid": "INVALID ID", "missing": "NO VOICE"}[a["status"]]
        lines.append(f"  {a['agent']:<12} {mark}")
    if d["problems"]:
        lines.append("")
        lines.append("Problems:")
        lines.extend(f"  - {p}" for p in d["problems"])
        lines.append("")
        lines.append("Give an agent its own voice by adding e.g. "
                     "ELEVENLABS_VOICE_ARIS=<voice id> to .env, then restarting.")
    return "\n".join(lines)


@register(
    name="system_health",
    description=(
        "Live machine health: CPU, memory, disk, battery, network, and "
        "ZENO's own resource use. Real readings from this machine. Use when "
        "asked how the computer/system is doing, or if something feels slow."
    ),
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def system_health() -> str:
    import shutil

    import psutil

    lines = []
    cpu = psutil.cpu_percent(interval=0.4)
    freq = psutil.cpu_freq()
    lines.append(f"CPU: {cpu:.0f}% across {psutil.cpu_count(logical=True)} threads"
                 + (f" @ {freq.current/1000:.1f}GHz" if freq else ""))

    vm = psutil.virtual_memory()
    lines.append(f"RAM: {vm.percent:.0f}% used ({vm.used/1e9:.1f}GB of {vm.total/1e9:.1f}GB)")

    try:
        du = shutil.disk_usage("C:\\")
        lines.append(f"Disk C:: {du.used/1e9:.0f}GB used, {du.free/1e9:.0f}GB free")
    except Exception:  # noqa: BLE001
        pass

    try:
        bat = psutil.sensors_battery()
        if bat is not None:
            state = "charging" if bat.power_plugged else "on battery"
            lines.append(f"Battery: {bat.percent:.0f}% ({state})")
    except Exception:  # noqa: BLE001
        pass

    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in list(temps.items())[:1]:
                if entries:
                    lines.append(f"Temp ({name}): {entries[0].current:.0f}C")
    except Exception:  # noqa: BLE001
        pass  # not exposed on most Windows machines

    net = psutil.net_io_counters()
    lines.append(f"Network: {net.bytes_recv/1e9:.1f}GB in / {net.bytes_sent/1e9:.1f}GB out since boot")

    try:
        me = psutil.Process()
        rss = me.memory_info().rss / 1e6
        kids = sum(c.memory_info().rss for c in me.children(recursive=True)) / 1e6
        lines.append(f"ZENO itself: {rss:.0f}MB (+{kids:.0f}MB child processes)")
    except Exception:  # noqa: BLE001
        pass

    top = sorted(psutil.process_iter(["name", "memory_info"]),
                 key=lambda p: (p.info["memory_info"].rss if p.info.get("memory_info") else 0),
                 reverse=True)[:3]
    heavy = ", ".join(f"{p.info['name']} {p.info['memory_info'].rss/1e6:.0f}MB"
                      for p in top if p.info.get("memory_info"))
    if heavy:
        lines.append(f"Heaviest apps: {heavy}")

    return "\n".join(lines)
