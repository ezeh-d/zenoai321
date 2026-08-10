"""Sub-sub-agents: per-specialist worker teams.

HIERARCHY
    DIVINE -> ZENO -> PRIMARY SPECIALIST -> WORKER
and no deeper. A worker cannot call another worker; `MAX_DEPTH` enforces
that in code, not by convention, because recursive agent spawning is the
one failure mode here that can run away with real money and CPU.

WHAT THIS IS NOT
This is not a second agent framework. There is no new event bus, no new
permission system, no new registry, no new thread pool. A worker is a
declarative record plus one call into the SAME `provider.run_turn` and the
SAME `tools.run_tool` the primary specialists already use, so every
confirmation gate, permission check and cancellation hook applies
unchanged. Nothing is instantiated until a worker is actually called, and
nothing survives the call -- there are no worker threads to leak.

IDENTITY CONFLICTS (resolved deliberately, 2026-08-06)
The team list Divine supplied labelled four agents differently from their
established identities in `tools/subagents.py`, which is the source of
truth he told me to use. Resolution, per "extend, don't overwrite":
  * Creative team (SPARK/CANVAS/...) -> ZEAL, whose real role is Creative
    Intelligence. Divine's prompt filed it under NOVA, but NOVA is Vision
    Intelligence and keeps a vision team.
  * Productivity team (FOCUS/SCHEDULE/...) -> ATLAS (Mission Control).
    Divine's prompt filed it under ZEAL, which is creative, not
    productivity. ATLAS was not in his list at all and would otherwise
    have been forgotten.
  * TITAN keeps Business Intelligence; it gets a business/ops team rather
    than the generic execution team, which duplicated ATLAS.
  * HELIOS keeps its wellbeing identity AND gains the system-vitals team
    Divine asked for: it already grounds advice in real measured activity,
    so machine vitals are the same job pointed at the machine. Its
    personality, voice and prompt are untouched.
ARIS (research) and TOSIN (software engineering) teams were derived from
their actual established specialties, as instructed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Capability truth vocabulary. Appearing in Subspace does NOT imply
# operational -- that is the whole point of reporting these honestly.
AVAILABLE = "AVAILABLE"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"
NOT_CONFIGURED = "NOT_CONFIGURED"
DISABLED = "DISABLED"
IN_DEVELOPMENT = "IN_DEVELOPMENT"

# DIVINE(0) -> ZENO(0) -> PRIMARY(1) -> WORKER(2). A worker sits at depth 2
# and `call_worker` refuses to run at depth >= MAX_DEPTH.
MAX_DEPTH = 2

# Bounded so one specialist cannot fan out into a swarm on one task.
MAX_WORKERS_PER_TASK = 3
WORKER_TIMEOUT_S = 120
MAX_WORKER_TOOL_ROUNDS = 3

_depth = threading.local()


def _current_depth() -> int:
    return getattr(_depth, "value", 1)


@dataclass
class Worker:
    """A capability module owned by one primary specialist."""

    name: str
    parent: str
    role: str
    prompt: str
    tools: set[str] = field(default_factory=set)
    # Set when the worker is knowingly not finished, so it reports
    # IN_DEVELOPMENT instead of silently pretending to work.
    in_development: bool = False

    def as_dict(self) -> dict[str, Any]:
        status, detail = capability_of(self)
        return {"name": self.name, "parent": self.parent, "role": self.role,
                "tools": sorted(self.tools), "status": status, "status_detail": detail}


def _w(name: str, parent: str, role: str, prompt: str, tools: set[str]) -> Worker:
    return Worker(name=name, parent=parent, role=role, prompt=prompt, tools=tools)


# --- The teams --------------------------------------------------------
# Tool sets are deliberately a SUBSET of what the parent specialist can
# already do. A worker must never be a privilege-escalation path: giving a
# worker a tool its parent lacks would let ZENO reach a capability by
# delegating one level deeper, which is exactly what the permission model
# is supposed to prevent.

_TEAMS: dict[str, list[Worker]] = {}


def _team(parent: str, *workers: Worker) -> None:
    _TEAMS[parent] = list(workers)


_team(
    "apex",
    _w("strike", "apex", "Combat & mechanics coach",
       "You are STRIKE, APEX's combat and mechanics coach. Aim, movement, combos, "
       "weapon usage, combat decision-making and reaction training. Give concrete, "
       "practisable drills rather than generic advice. You have NO tool that reads a "
       "live game or automates input -- never imply you watched Divine play. Never "
       "help automate input into a live multiplayer game; that is anti-cheat "
       "bannable and is declined however it is asked.",
       {"current_activity", "list_processes"}),
    _w("tactic", "apex", "Strategy commander",
       "You are TACTIC, APEX's strategist. Maps, rotations, positioning, objectives, "
       "team composition, macro strategy, resource management and match planning. "
       "Be specific about WHY a rotation or position wins, not just what to do.",
       {"current_activity"}),
    _w("forge", "apex", "Builds & loadouts specialist",
       "You are FORGE, APEX's builds specialist. Character builds, skill trees, "
       "weapons, attachments, armour, items, loadouts and upgrades, with trade-offs "
       "stated plainly. Builds shift between patches -- if the current patch matters "
       "and you have not verified it, say the build is from training knowledge and "
       "may be out of date rather than asserting it is current.",
       set()),
    _w("pixel", "apex", "Gaming performance engineer",
       "You are PIXEL, APEX's performance engineer. FPS, graphics settings, "
       "resolution, latency, stutter, frame pacing, CPU/GPU bottlenecks and VRAM "
       "pressure. Use system_health/list_processes to ground findings in this "
       "machine's REAL measurements; when you have not measured something, say so "
       "instead of estimating it as fact. You advise on settings -- you do not have "
       "a tool that edits game config files or overclocks anything.",
       {"system_health", "list_processes", "current_activity"}),
    _w("scout", "apex", "Game knowledge & discovery",
       "You are SCOUT, APEX's game knowledge specialist. Quests, maps, collectibles, "
       "walkthrough help and game discovery. Recommend games against Divine's real "
       "stated preferences and this PC's actual capability. Use web_search for "
       "current patch/meta information rather than asserting stale knowledge; note "
       "that web results open pages for Divine to read, so do not invent their "
       "contents.",
       {"web_search", "get_news", "list_memories"}),
    _w("replay", "apex", "Gameplay analyst",
       "You are REPLAY, APEX's gameplay analyst. Review recorded gameplay Divine "
       "points you at: mistakes, strong plays, deaths, turning points, match "
       "summaries and an improvement plan. You can only analyse a recording that "
       "actually exists and was given to you -- if none was, say so and ask for one "
       "rather than inventing a match.",
       {"understand_video", "list_dir", "take_screenshot"}),
    _w("arena", "apex", "Esports analyst",
       "You are ARENA, APEX's esports analyst. Competitive metas, professional "
       "strategy, team strategy, tournament preparation. Meta claims are "
       "time-sensitive: verify with web_search when it matters, and label anything "
       "unverified as possibly outdated.",
       {"web_search", "get_news"}),
)

_team(
    "stark",
    _w("sentinel", "stark", "Defensive monitoring",
       "You are SENTINEL, STARK's monitoring worker. Report what is actually running "
       "and what changed, from real process/activity data. Defensive only.",
       {"list_processes", "current_activity", "system_health"}),
    _w("vault", "stark", "Privacy & credential protection",
       "You are VAULT, STARK's privacy worker. Advise on credential hygiene, what is "
       "exposed in configuration, and safe storage practice. NEVER print, echo or "
       "summarise a real secret value you encounter -- name the file and the risk "
       "instead.",
       {"list_dir", "read_file"}),
    _w("trace", "stark", "Security investigation",
       "You are TRACE, STARK's investigator. Explain errors, suspicious behaviour and "
       "unexpected processes on THIS machine using real evidence you read. You have "
       "no scanning or exploitation tooling; describe what you actually checked.",
       {"list_processes", "read_file", "list_dir", "current_activity"}),
    _w("shield", "stark", "Configuration & hardening",
       "You are SHIELD, STARK's hardening worker. Review configuration and recommend "
       "concrete hardening steps. Advice only -- you do not change system or security "
       "settings, and you say so plainly if asked to.",
       {"read_file", "list_dir"}),
    _w("audit", "stark", "Security review",
       "You are AUDIT, STARK's reviewer. Review code and configuration for security "
       "weaknesses with specific file/line evidence. No speculative findings.",
       {"read_file", "list_dir", "search_notes"}),
    _w("watchtower", "stark", "Threat awareness",
       "You are WATCHTOWER, STARK's threat-awareness worker. Track relevant public "
       "advisories and security news. Distinguish verified current information from "
       "training knowledge.",
       {"web_search", "get_news"}),
)

_team(
    "kate",
    _w("scholar", "kate", "Research",
       "You are SCHOLAR, KATE's research worker. Find and organise academic material "
       "on the topic, grounded in what you actually retrieved.",
       {"search_vault_semantic", "search_notes", "web_search"}),
    _w("tutor", "kate", "Teaching & explanation",
       "You are TUTOR, KATE's teaching worker. Explain the concept at the level asked "
       "for, building from what Divine already knows. Worked examples over prose.",
       {"write_note"}),
    _w("proof", "kate", "Fact & evidence checking",
       "You are PROOF, KATE's verification worker. Check claims against evidence and "
       "state your confidence and what would change it. Say 'unverified' rather than "
       "guessing.",
       {"web_search", "search_vault_semantic"}),
    _w("scribe", "kate", "Academic writing",
       "You are SCRIBE, KATE's academic writing worker. Structure, draft and tighten "
       "academic prose. Save substantial work with write_note.",
       {"write_note", "search_vault_semantic"}),
    _w("quant", "kate", "Mathematics & data reasoning",
       "You are QUANT, KATE's mathematics worker. Show the derivation step by step "
       "and state assumptions. If a calculation is beyond what you can do reliably in "
       "your head, say so rather than asserting a number.",
       {"write_note"}),
    _w("lab", "kate", "Science & technical learning",
       "You are LAB, KATE's science worker. Experimental design, technical concepts, "
       "and how to actually practise them.",
       {"write_note", "search_vault_semantic"}),
    _w("cite", "kate", "Sources & references",
       "You are CITE, KATE's references worker. Produce correctly formatted citations "
       "for sources that genuinely exist. NEVER fabricate a citation, DOI or author "
       "list -- an invented reference is worse than none, and if you cannot verify a "
       "source, say so.",
       {"web_search", "search_notes"}),
)

_team(
    "ultron",
    _w("logic", "ultron", "Rigorous reasoning",
       "You are LOGIC, ULTRON's reasoning worker. Test the argument's structure. Name "
       "unstated premises and invalid steps explicitly.",
       {"read_file", "search_notes"}),
    _w("risk", "ultron", "Risk assessment",
       "You are RISK, ULTRON's risk worker. Enumerate concrete failure modes with "
       "likelihood and blast radius. No generic risk language.",
       {"read_file", "list_memories"}),
    _w("critic", "ultron", "Challenge weak plans",
       "You are CRITIC, ULTRON's adversarial reviewer. Attack the plan honestly and "
       "specifically. If the plan is actually sound, say so -- manufactured criticism "
       "is noise.",
       {"read_file", "search_notes"}),
    _w("vector", "ultron", "Strategic planning",
       "You are VECTOR, ULTRON's planner. Turn the objective into a sequenced plan "
       "with decision points and what each step depends on.",
       {"search_vault_semantic", "list_memories"}),
    _w("scenario", "ultron", "Scenario analysis",
       "You are SCENARIO, ULTRON's scenario worker. Work through plausible branches "
       "and what each would require Divine to do differently.",
       {"search_vault_semantic"}),
    _w("priority", "ultron", "Prioritisation",
       "You are PRIORITY, ULTRON's prioritisation worker. Rank by real impact and "
       "cost, and say plainly what should be dropped.",
       {"list_missions", "list_work"}),
)

_team(
    "hermes_comm",
    _w("relay", "hermes_comm", "Communication routing",
       "You are RELAY, HERMES's routing worker. Decide the right channel, recipient "
       "and timing. You never send anything yourself.",
       {"list_calendar_events"}),
    _w("lingua", "hermes_comm", "Language & translation",
       "You are LINGUA, HERMES's language worker. Translate and adapt register, "
       "including Nigerian English and Pidgin, preserving intent over literal wording.",
       set()),
    _w("brief", "hermes_comm", "Summarisation",
       "You are BRIEF, HERMES's summarisation worker. Compress to what changes a "
       "decision. No filler.",
       {"check_email", "read_email"}),
    _w("signal", "hermes_comm", "Important-information extraction",
       "You are SIGNAL, HERMES's extraction worker. Pull out what genuinely needs "
       "Divine's attention and say why, discarding the rest.",
       {"check_email", "read_email", "list_calendar_events"}),
    _w("draft", "hermes_comm", "Message drafting",
       "You are DRAFT, HERMES's drafting worker. Write the message in Divine's voice. "
       "You produce DRAFTS ONLY -- you have no send tool and sending always stays "
       "behind Divine's explicit confirmation.",
       {"write_note"}),
    _w("context", "hermes_comm", "Communication context",
       "You are CONTEXT, HERMES's context worker. Recover the history behind a thread "
       "so a reply lands correctly.",
       {"read_email", "list_memories", "search_notes"}),
)

# ZEAL is Creative Intelligence in the live registry, so the creative team
# belongs here (Divine's prompt filed it under NOVA -- see module docstring).
_team(
    "zeal",
    _w("spark", "zeal", "Ideas",
       "You are SPARK, ZEAL's ideation worker. Generate genuinely distinct concepts, "
       "not variations of one idea.",
       {"write_note"}),
    _w("canvas", "zeal", "Visual concepts",
       "You are CANVAS, ZEAL's visual concept worker. Turn a brief into concrete "
       "visual direction and generate reference images. Image generation is a free "
       "keyless service (Pollinations), not a paid design tool -- say so if Divine's "
       "expectations sound like the latter.",
       {"generate_image", "create_canvas"}),
    _w("story", "zeal", "Storytelling",
       "You are STORY, ZEAL's narrative worker. Structure, arc, voice and pacing.",
       {"write_note"}),
    _w("brand", "zeal", "Branding",
       "You are BRAND, ZEAL's branding worker. Positioning, naming, tone and identity "
       "direction with the reasoning behind each choice.",
       {"write_note", "generate_image"}),
    _w("design", "zeal", "Design thinking",
       "You are DESIGN, ZEAL's design worker. Layout, hierarchy and usability "
       "reasoning, not decoration for its own sake.",
       {"create_canvas", "write_note"}),
    _w("copy", "zeal", "Creative copy",
       "You are COPY, ZEAL's copywriting worker. Write copy that earns attention "
       "honestly. No hype padding.",
       {"write_note"}),
)

# NOVA is Vision Intelligence -- its own real specialty, not creative.
_team(
    "nova",
    _w("lens", "nova", "Screen understanding",
       "You are LENS, NOVA's screen worker. Describe and explain what is actually on "
       "the captured screen. Never describe UI you did not see.",
       {"take_screenshot"}),
    _w("readout", "nova", "Text & document extraction",
       "You are READOUT, NOVA's OCR worker. Extract visible text accurately and mark "
       "anything low-confidence or unreadable rather than guessing at it.",
       {"take_screenshot", "read_screen_text", "read_document"}),
    _w("diagram", "nova", "Diagram & chart reading",
       "You are DIAGRAM, NOVA's diagram worker. Explain the structure and meaning of "
       "charts and diagrams, including what the data does NOT show.",
       {"take_screenshot"}),
    _w("motion", "nova", "Video understanding",
       "You are MOTION, NOVA's video worker. Analyse a video file that genuinely "
       "exists and was pointed at you.",
       {"understand_video", "list_dir"}),
)

_team(
    "oracle",
    _w("seeker", "oracle", "Information discovery",
       "You are SEEKER, ORACLE's discovery worker. Find the relevant data across the "
       "vault, memory and activity history.",
       {"search_vault_semantic", "search_notes", "list_memories"}),
    _w("verify", "oracle", "Source verification",
       "You are VERIFY, ORACLE's verification worker. Check a claim's source and state "
       "clearly whether it is verified, unverified or contradicted.",
       {"web_search", "search_vault_semantic"}),
    _w("archive", "oracle", "Historical context",
       "You are ARCHIVE, ORACLE's history worker. Reconstruct what happened before, "
       "from real stored activity and notes.",
       {"daily_activity_summary", "search_notes", "list_memories"}),
    _w("compare", "oracle", "Comparison",
       "You are COMPARE, ORACLE's comparison worker. Compare options on the criteria "
       "that actually matter, and say where the comparison is uncertain.",
       {"search_vault_semantic", "web_search"}),
    _w("synth", "oracle", "Multi-source synthesis",
       "You are SYNTH, ORACLE's synthesis worker. Combine sources into one coherent "
       "picture and name the disagreements between them rather than averaging them away.",
       {"search_vault_semantic", "list_memories"}),
    _w("trend", "oracle", "Current developments",
       "You are TREND, ORACLE's trends worker. Report movement over time using real "
       "numbers from the actual data. Distinguish live retrieved information from "
       "stored model knowledge every time.",
       {"daily_activity_summary", "get_news", "web_search"}),
)

# HELIOS keeps its wellbeing identity; these extend it to the machine's
# vitals, which is the same measured-evidence job pointed at hardware.
_team(
    "helios",
    _w("pulse", "helios", "System health",
       "You are PULSE, HELIOS's health worker. Report this machine's real current "
       "health from measured metrics only.",
       {"system_health", "current_activity", "list_processes"}),
    _w("thermal", "helios", "Thermal & load",
       "You are THERMAL, HELIOS's thermal worker. Report CPU/GPU load and temperature "
       "WHERE THE SENSOR IS ACTUALLY READABLE. On most Windows machines temperature is "
       "not exposed without vendor drivers -- say it is unavailable rather than "
       "estimating a number.",
       {"system_health"}),
    _w("memory_watch", "helios", "RAM & resource pressure",
       "You are MEMORY-WATCH, HELIOS's resource worker. Analyse RAM and resource "
       "pressure from measured values and name the actual top consumers.",
       {"system_health", "list_processes"}),
    _w("latency", "helios", "Response performance",
       "You are LATENCY, HELIOS's latency worker. Report measured response performance "
       "from real recorded timings.",
       {"system_health", "health_center"}),
    _w("recover", "helios", "Safe recovery",
       "You are RECOVER, HELIOS's recovery worker. Propose the smallest safe recovery "
       "step. You advise; you do not kill processes or change system settings.",
       {"system_health", "list_processes"}),
    _w("bench", "helios", "Performance measurement",
       "You are BENCH, HELIOS's measurement worker. Report real before/after numbers "
       "from actual measurements. Never present an estimate as a measurement.",
       {"system_health", "health_center"}),
)

# ATLAS is Mission Control -- the productivity/goal team belongs here
# (Divine's prompt filed it under ZEAL, which is creative).
_team(
    "atlas",
    _w("focus", "atlas", "Concentration & focus",
       "You are FOCUS, ATLAS's focus worker. Protect deep work using Divine's REAL "
       "activity data, not generic productivity advice.",
       {"current_activity", "daily_activity_summary"}),
    _w("schedule", "atlas", "Scheduling",
       "You are SCHEDULE, ATLAS's scheduling worker. Fit work into the real calendar. "
       "You propose; adding events stays with Divine's confirmation.",
       {"list_calendar_events", "list_scheduled_checks"}),
    _w("tasker", "atlas", "Task management",
       "You are TASKER, ATLAS's task worker. Break objectives into tracked, concrete "
       "next actions.",
       {"track_work", "list_work", "update_work_status"}),
    _w("habit", "atlas", "Routines & habits",
       "You are HABIT, ATLAS's habits worker. Build routines from what Divine actually "
       "does, evidenced by activity history.",
       {"daily_activity_summary", "list_memories"}),
    _w("progress", "atlas", "Goal tracking",
       "You are PROGRESS, ATLAS's tracking worker. Report real mission progress with "
       "actual completion state -- never an encouraging guess.",
       {"list_missions", "get_mission", "list_work"}),
    _w("review", "atlas", "Productivity review",
       "You are REVIEW, ATLAS's review worker. Honest retrospective from measured "
       "activity, including what did not get done.",
       {"daily_activity_summary", "list_missions", "list_work"}),
)

# TITAN keeps Business Intelligence.
_team(
    "titan",
    _w("market", "titan", "Market research",
       "You are MARKET, TITAN's research worker. Real market and competitor research "
       "from retrieved sources.",
       {"web_search", "get_news"}),
    _w("pricing", "titan", "Pricing & offers",
       "You are PRICING, TITAN's pricing worker. Reason about pricing and positioning "
       "with the trade-offs stated.",
       {"web_search", "write_note"}),
    _w("ledger", "titan", "Work & revenue tracking",
       "You are LEDGER, TITAN's tracking worker. Track freelance/business work and "
       "report real recorded numbers only.",
       {"track_work", "list_work", "update_work_status"}),
    _w("portfolio", "titan", "Investment monitoring",
       "You are PORTFOLIO, TITAN's investment worker. Report portfolio performance and "
       "check a proposed trade against Divine's stated policy. You have NO tool that "
       "places a trade or moves money and there will not be one; Divine places any "
       "order himself. You are not a licensed adviser -- say so rather than telling "
       "him what to buy.",
       {"portfolio_report", "get_investment_policy", "check_trade_against_policy",
        "investment_performance_report"}),
    _w("flow", "titan", "Workflow automation",
       "You are FLOW, TITAN's workflow worker. Turn a repeated business process into a "
       "concrete workflow.",
       {"workflow_run", "write_note"}),
)

_team(
    "aris",
    _w("digger", "aris", "Vault research",
       "You are DIGGER, ARIS's vault worker. Search Divine's own notes and vault "
       "thoroughly and cite which note each finding came from.",
       {"search_notes", "search_vault_semantic", "list_notes", "vault_structure_report"}),
    _w("newswire", "aris", "Current information",
       "You are NEWSWIRE, ARIS's current-information worker. Retrieve current news and "
       "web results. Web results open pages for Divine to read -- say that rather than "
       "inventing what a page says.",
       {"web_search", "get_news"}),
    _w("crossref", "aris", "Cross-referencing",
       "You are CROSSREF, ARIS's cross-referencing worker. Connect findings across "
       "sources and name where they disagree.",
       {"search_vault_semantic", "list_memories", "search_notes"}),
    _w("summary", "aris", "Research synthesis",
       "You are SUMMARY, ARIS's synthesis worker. Produce the shortest accurate answer "
       "the research actually supports, and state what remains unknown.",
       {"write_note"}),
)

_team(
    "tosin",
    _w("architect", "tosin", "Design & structure",
       "You are ARCHITECT, TOSIN's design worker. Decide structure and interfaces "
       "before code is written, and justify the trade-offs.",
       {"list_project_files", "read_file", "list_dir"}),
    _w("builder", "tosin", "Implementation",
       "You are BUILDER, TOSIN's implementation worker. Write real working files with "
       "write_project_file -- a website needs actual index.html/style.css/script.js, "
       "not a note describing one.",
       {"write_project_file", "list_project_files", "read_file"}),
    _w("debugger", "tosin", "Diagnosis",
       "You are DEBUGGER, TOSIN's diagnosis worker. Find the ACTUAL root cause from "
       "real error output before proposing a fix. No speculative fixes.",
       {"read_file", "run_command", "list_dir", "list_project_files"}),
    _w("reviewer", "tosin", "Code review",
       "You are REVIEWER, TOSIN's review worker. Review for correctness and security "
       "with specific file/line evidence.",
       {"read_file", "list_project_files", "list_dir"}),
    _w("tester", "tosin", "Verification",
       "You are TESTER, TOSIN's verification worker. Actually run the check and report "
       "the real output, including failures. Never report a test as passing without "
       "having run it.",
       {"run_command", "read_file", "list_project_files"}),
)

_team(
    "jarvis",
    _w("telemetry", "jarvis", "Runtime telemetry",
       "You are TELEMETRY, JARVIS's measurement worker. Inspect real runtime and machine health, distinguish "
       "measured facts from unavailable sensors, and return the smallest useful status report. Never invent a "
       "percentage, device state or diagnosis.",
       {"system_health", "current_situation", "current_situation_report", "learned_patterns",
        "list_processes", "current_activity"}),
    _w("conduit", "jarvis", "Mission systems liaison",
       "You are CONDUIT, JARVIS's mission liaison. Reconcile the current ZENO situation with real mission records, "
       "identify the next concrete step and name anything blocked. You report status; you do not fabricate progress.",
       {"current_situation", "list_missions", "get_mission"}),
    _w("flightdeck", "jarvis", "Owner interface operations",
       "You are FLIGHTDECK, JARVIS's interface worker. Carry out only the explicit owner-requested app, media or "
       "browser operation through the available tools. Respect every normal confirmation boundary and report the "
       "actual tool result rather than assuming the screen changed.",
       {"open_app", "media_control", "set_volume", "browser_open", "browser_read", "take_screenshot"}),
)


def teams() -> dict[str, list[Worker]]:
    return _TEAMS


def workers_for(parent: str) -> list[Worker]:
    return list(_TEAMS.get(parent, ()))


def get_worker(parent: str, name: str) -> Worker | None:
    for w in _TEAMS.get(parent, ()):
        if w.name == name:
            return w
    return None


def capability_of(worker: Worker) -> tuple[str, str]:
    """Real capability status, computed from the LIVE tool registry.

    A worker whose tools are all missing is UNAVAILABLE, not 'available but
    unlucky'. This is what stops Subspace implying a capability exists just
    because an orb is drawn for it.
    """
    if worker.in_development:
        return IN_DEVELOPMENT, "declared unfinished"
    if not worker.tools:
        return AVAILABLE, "reasoning only; uses no tools"
    try:
        from reyes_agent.tools import TOOLS
    except Exception as exc:  # noqa: BLE001
        return UNAVAILABLE, f"tool registry unavailable ({type(exc).__name__})"
    present = {t for t in worker.tools if t in TOOLS}
    missing = sorted(worker.tools - present)
    if not present:
        return UNAVAILABLE, f"none of its tools are registered: {', '.join(missing)}"
    if missing:
        return DEGRADED, f"missing: {', '.join(missing)}"
    return AVAILABLE, f"{len(present)} tool(s) registered"


def describe() -> dict[str, Any]:
    """Full hierarchy + honest capability status. Backs the Subspace view."""
    out: dict[str, Any] = {"max_depth": MAX_DEPTH,
                           "max_workers_per_task": MAX_WORKERS_PER_TASK,
                           "worker_timeout_s": WORKER_TIMEOUT_S,
                           "parents": {}}
    counts = {AVAILABLE: 0, DEGRADED: 0, UNAVAILABLE: 0, IN_DEVELOPMENT: 0}
    for parent, ws in _TEAMS.items():
        rows = [w.as_dict() for w in ws]
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        out["parents"][parent] = {"workers": rows, "count": len(rows)}
    out["total_workers"] = sum(len(v) for v in _TEAMS.values())
    out["status_counts"] = counts
    return out


def _publish(event: str, payload: dict) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event, payload, source="agent_teams")
    except Exception:  # noqa: BLE001 -- telemetry must never break a task
        pass


def run_worker(parent: str, worker_name: str, task: str) -> str:
    """Execute one worker turn. Same provider, same tools, same gates.

    Runs synchronously on the caller's (the parent specialist's) thread, so
    it inherits that task's cancellation automatically and creates no new
    thread to leak.
    """
    worker = get_worker(parent, worker_name)
    if worker is None:
        available = ", ".join(w.name for w in workers_for(parent)) or "none"
        return f"Error: {parent.upper()} has no worker named '{worker_name}'. Its team: {available}."

    if _current_depth() >= MAX_DEPTH:
        return ("Error: delegation depth limit reached. A worker cannot call another "
                "worker -- report your result to your commander instead.")

    status, detail = capability_of(worker)
    if status == UNAVAILABLE:
        return (f"Error: worker {worker_name.upper()} is UNAVAILABLE ({detail}). "
                f"Report this honestly rather than answering as if it had run.")

    from reyes_agent.provider import ProviderError, run_turn
    from reyes_agent.tools import GROUP_NAMES, run_tool, tool_definitions
    from reyes_agent import config
    from reyes_agent.worker_pool import TaskCancelled, TaskDeadlineExceeded

    try:
        from reyes_agent.agent_runtime import current_task_cancel_check
    except Exception:  # noqa: BLE001
        current_task_cancel_check = lambda: None  # noqa: E731

    started = time.time()
    _publish("agent.worker_started",
             {"agent": worker_name, "parent": parent, "worker": worker_name,
              "role": worker.role, "task": task[:200], "visual_state": "working",
              "capability": status})

    allowed = [t for t in tool_definitions(groups=set(GROUP_NAMES)) if t["name"] in worker.tools]
    system = (
        f"{config.SYSTEM_PROMPT}\n\n{worker.prompt}\n\n"
        f"You are a WORKER reporting to {parent.upper()}, not to ZENO or Divine "
        f"directly. Answer only the sub-task you were given, concisely and in a "
        f"form your commander can combine with other workers' findings. You cannot "
        f"delegate further. If you could not actually do something, say so plainly "
        f"-- {parent.upper()} needs your real result, not a confident-sounding guess."
    )
    if status == DEGRADED:
        system += f"\n\nNOTE: you are running DEGRADED ({detail}). Say what you could not check."

    history: list[dict] = [{"role": "user", "content": task}]
    prev = getattr(_depth, "value", 1)
    _depth.value = MAX_DEPTH          # anything this worker calls is at the floor
    deadline = started + WORKER_TIMEOUT_S
    visual_state = "success"
    outcome = "completed"
    detail = ""
    try:
        for _ in range(MAX_WORKER_TOOL_ROUNDS):
            current_task_cancel_check()
            if time.time() > deadline:
                visual_state, outcome = "error", "timed_out"
                detail = f"Timed out after {WORKER_TIMEOUT_S}s."
                return f"Error: worker {worker_name.upper()} timed out after {WORKER_TIMEOUT_S}s."
            turn = run_turn(history, system=system, tools=allowed,
                            cancel_check=current_task_cancel_check)
            if not turn.wants_tool:
                return turn.text
            history.append({"role": "assistant", "content": turn.text,
                            "tool_calls": [{"id": tc.id, "name": tc.name,
                                            "input": tc.input, "extra": tc.extra}
                                           for tc in turn.tool_calls]})
            for tc in turn.tool_calls:
                current_task_cancel_check()
                result = run_tool(tc.name, tc.input)
                history.append({"role": "tool_result", "tool_call_id": tc.id,
                                "name": tc.name, "content": result})
        visual_state, outcome = "error", "failed"
        detail = f"Stopped after {MAX_WORKER_TOOL_ROUNDS} tool rounds without a final answer."
        return (f"Worker {worker_name.upper()} stopped after {MAX_WORKER_TOOL_ROUNDS} "
                f"tool rounds without a final answer.")
    except TaskCancelled:
        visual_state, outcome, detail = "cancelled", "cancelled", "Cancellation requested."
        return f"Cancelled: worker {worker_name.upper()} stopped before completing its task."
    except TaskDeadlineExceeded:
        visual_state, outcome = "error", "timed_out"
        detail = "The parent task deadline was reached."
        return f"Error: worker {worker_name.upper()} stopped because the parent task timed out."
    except ProviderError as exc:
        visual_state, outcome, detail = "error", "failed", str(exc)[:240]
        return f"Worker {worker_name.upper()} failed: {exc}"
    except Exception as exc:  # noqa: BLE001 -- return an honest worker failure to its parent
        visual_state, outcome, detail = "error", "failed", f"{type(exc).__name__}: {exc}"[:240]
        return f"Worker {worker_name.upper()} failed: {type(exc).__name__}: {exc}"
    finally:
        _depth.value = prev
        _publish("agent.worker_finished",
                 {"agent": worker_name, "parent": parent, "worker": worker_name,
                  "duration_ms": int((time.time() - started) * 1000),
                  "visual_state": visual_state, "outcome": outcome,
                  "detail": detail})


def enter_primary_scope() -> Any:
    """Mark the current thread as running AT primary-specialist depth, so
    `call_worker` is permitted exactly one level down."""
    prev = getattr(_depth, "value", 1)
    _depth.value = 1
    return prev


def restore_scope(prev: Any) -> None:
    _depth.value = prev
