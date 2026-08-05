# AGENT.md — REYES spec

Single source of truth for what we're building and why. Written from the
Tier 0 interview on 2026-07-22. Update this file if any answer below changes
— it's what any future session should read first.

## Identity

- **Name:** REYES
- **One-line description:** A personal AI operating system that helps its
  user think, plan, automate their computer, manage knowledge, and complete
  complex tasks through voice, vision, and reasoning.
- **Who it's for:** Just the owner for now. The architecture (memory schema,
  task/project model) should stay scalable to a small team with shared
  projects, knowledge, and task management later — but no team features are
  built yet.

## First three capabilities (source the first tools and test cases)

1. **Planning and task execution** — plan the day by priority, break large
   projects into actionable steps, track progress, remind what's next.
2. **Knowledge management** — search/answer from the Obsidian vault, remember
   conversations and project decisions, connect related ideas across notes.
3. **Desktop automation** — open apps and organize the workspace, control
   browser and files, automate repetitive tasks by voice command.

## Personality

Professional, intelligent, calm, confident, helpful, concise, occasionally
humorous when appropriate. A modern JARVIS — friendly, but focused on
getting work done. Applied consistently in the system prompt everywhere
(text, voice, proactive messages).

## Stack

- Python 3.12+, async architecture (asyncio)
- PySide6 for the desktop GUI (later tier — "a face")
- FastAPI for local APIs (later tier — mobile/team access)
- SQLite for structured memory (Tier 4)
- ChromaDB or FAISS for semantic memory (Tier 4, once note volume needs it)
- Obsidian vault (already at `REYES/REYES`) as the primary knowledge base

## Model provider

- **Primary:** Claude, latest official SDK (`claude-sonnet-5` by default),
  behind a thin provider seam (`provider.py`) so it can be swapped without
  touching the rest of the harness.
- **Secondary:** Ollama, for local/offline fallback.
- **Future:** OpenAI, Gemini, DeepSeek, Grok, more local models via Ollama —
  REYES should eventually auto-select the best model per task. Not built in
  Tier 1; the seam exists specifically so this is an addition, not a rewrite.

## Where it runs

- **Now:** Windows laptop/workstation.
- **Later:** an always-on server or mini-PC that syncs with the laptop and
  mobile devices. The heartbeat (Tier 5) is built so this is a relocation,
  not a rewrite.

## How the user talks to it

All three modes, eventually:
- Text chat (Tier 1 — built first, stays alive forever as the debug/fallback
  path)
- Push-to-talk (Tier 3)
- Open-microphone wake word (after the baseline six tiers, once push-to-talk
  is solid)

Wake phrases (for the future wake-word tier): "Reyes", "Gee", "Gee how far",
"What's good", "Guy", "Blood".

Voice providers (Tier 3): Deepgram for STT, ElevenLabs for TTS, both behind
their own seams. An ElevenLabs key and voice ID are already configured in
`.env` from earlier work on this project — reused as-is unless the user asks
to change the voice.

## Confirm-before-acting list (hard gate, built in Tier 6)

REYES must stop and get explicit yes before:
- Sending emails or messages
- Spending money / making purchases
- Deleting files
- Moving important files
- Formatting drives
- Editing system settings
- Running administrator commands
- Executing destructive terminal commands
- Publishing code
- Posting on social media

Reading information and creating drafts do **not** require confirmation.

## Proactive behavior (Tier 5)

Yes, proactive. Quiet by default — interrupts only for important reminders,
urgent events, or explicitly-configured triggers. In scope:
- Remind of deadlines
- Suggest the next task
- Warn about schedule conflicts
- Detect return to unfinished projects
- Summarize important updates
- Organize notes automatically
- Learn work patterns over time

## Build approach

The project folder already contains an earlier REYES build (`brain.py`,
`voice.py`, `agents/`, `memory.py`, `router.py`, etc.) — per its own
`FEATURES.md`, several parts (the voice pipeline, the live HUD window) were
never actually run and verified.

Decision (default taken, no response yet — **tell Claude to change this if
it's wrong**): build the new tiered harness **fresh**, in a new `reyes_agent/`
package, following this plan's tier discipline exactly. The old code is left
untouched on disk as reference and a source to mine proven pieces from
(voice code, security module, desktop control) when a tier actually needs
them — not built on top of as-is.

## Current provider state (updated 2026-07-22, evening)

`MODEL_PROVIDER=gemini` in `.env` — promoted from Ollama after the CPU
tool-calling wall (see below) made local mode unworkable with tools on.
Still not the spec'd primary of Claude (no valid Anthropic key yet), but
Gemini now delivers what Claude was meant to: 2-8s replies including tool
calls, correct multi-round tool use, full registry available (not the
Ollama-only trimmed set). Switching to Claude later is still a one-line
`.env` edit once a real `sk-ant-...` key exists.

**Fixed, not just worked around:** Gemini's OpenAI-compatible endpoint was
previously rejecting the second turn of any multi-round tool call with a
`thought_signature` requirement that has no field in the standard OpenAI
wire format -- documented below as "not pursued" earlier today. Root cause
found: the signature *is* present on the streamed tool-call delta
(`extra_content.google.thought_signature`), our translation layer just
wasn't capturing or replaying it. Fixed by threading a provider-specific
`extra` field through `ToolCall` → neutral history → `_to_openai_messages`
(`reyes_agent/provider.py`). Verified live: a 3-turn conversation mixing
plain replies and two separate tool calls (`list_notes` then
`search_notes`) all succeeded, the second tool call being exactly the
scenario that used to 400.

**Ollama still gets zero tools** (see the lag section below) -- that
finding didn't change, Gemini fixes the *speed and correctness* problem for
cloud mode specifically. Ollama remains the offline-only fallback.

**Observed:** the small `llama3.2:3b` model sometimes sends tool arguments
with the wrong JSON type (e.g. `limit` as the string `"10"` or `null`
instead of an integer) — harmless once tools coerce defensively
(`reyes_agent/tools/notes.py::_coerce_limit`), but a sign this model isn't
always reliable at precise instruction-following (e.g. asked to quote a
note's line exactly, it paraphrased it). The tool layer itself was verified
correct independently of the model's fidelity.

## Voice (Tier 3) state (as of 2026-07-22)

Built: push-to-talk capture (`reyes_agent/voice/capture.py`, `keyboard` +
`sounddevice`), Deepgram STT seam (`voice/stt.py`), ElevenLabs/SAPI TTS seam
(`voice/tts.py`), and `voice_cli.py` wrapping the same `agent.run_agent`
used by the text CLI — tools and all. Entry point: `python -m
reyes_agent.voice_cli`. Text mode (`python -m reyes_agent`) still works
unchanged, as required.

**TTS provider:** `TTS_PROVIDER=sapi` (Windows' built-in voice) — chosen
because ElevenLabs' Free plan returns `402 payment_required` for **any**
voice via the API, confirmed against both the configured voice and
ElevenLabs' own default. Not a key problem, a plan problem. Flip
`TTS_PROVIDER=elevenlabs` once upgraded; no other code changes needed —
the ElevenLabs backend is fully built and ready in the same file.

**Verified without a live mic (can't physically hold a key and speak from
here):**
- Deepgram STT: a locally-synthesized clip round-tripped to an accurate
  transcript.
- SAPI TTS: spoke aloud successfully; interrupt-mid-sentence confirmed
  (stopped at ~1.1s into a ~5s sentence when the stop event fired).
- Full glue end-to-end: transcribed clip → `run_agent` (with a real tool
  call against the vault) → spoken reply, all in one pass.

**Not verified, needs the user:** the actual push-to-talk experience —
holding `PTT_KEY` (default `space`), speaking, releasing, and hearing the
reply; interrupting REYES mid-sentence by pressing the key again while it's
talking. If `keyboard.wait()` never detects the press, the likely fix is
running the terminal as Administrator — the `keyboard` package needs a
global OS hook on Windows.

**Deliberate simplification:** the full reply is spoken only after the
complete text has streamed to the console, not sentence-by-sentence while
still generating. True concurrent sentence-streaming TTS is the natural
next latency improvement, best done once ElevenLabs (which streams) is the
live backend rather than SAPI.

## Personality persistence (2026-07-22)

Added `reyes_agent/personality.py`: a recency `VOICE_CUE` appended to the
API-bound copy of the last user message only (never written to stored
history, no-ops correctly mid tool-call round), plus a `TONAL_CHECKPOINT`
reinforced in the system prompt every turn. Anthropic gets real prompt
caching on the personality block (`cache_control: ephemeral`); the
OpenAI-compatible providers (xAI/Gemini/Ollama) get the same content
without caching, since that wire format has no equivalent. Also
strengthened `config.SYSTEM_PROMPT` with concrete voice examples and
banned openers instead of bare adjectives. Verified live: a reply echoed
one of the cue's example lines almost verbatim, confirming the cue is
reaching and steering the model; unit-verified the cue never mutates
stored history and correctly no-ops on tool-continuation turns.

## Deferred (attached 2026-07-22, not started)

Three more files were shared as inspiration/spec material, explicitly
sequenced *after* this, not merged in:
- **Cosmic orb UI** (`cosmic-orb-ui.md`) — a 3D voice-reactive face for
  REYES. Matches "Where to go after the baseline" in the original tiered
  spec — i.e. after Tiers 4–6 (memory, heartbeat, rails), not before.
- **Self-knowledge doc generator** (`self-knowledge.md`) — auto-refreshing
  self-description via a pre-commit hook + CI drift check. Needs `git
  init` first; this project isn't a git repo yet.
- **Hybrid cloud Postgres / Supabase** (`hybrid-model.md`,
  `supabase-connection.md`) — conflicts with the SQLite + ChromaDB/FAISS
  stack already decided above, and there's no Tier 4 memory to migrate
  yet. Revisit only if the stack decision changes.
- `chief-of-staff-skill.md` wasn't touched — it installs an unrelated
  Claude Code skill (business planning/north-star doc), not a REYES
  capability. Flagged for the user to confirm intent.

## The GUI, mobile, and the Ollama tool-calling wall (2026-07-22)

**The face:** `reyes_agent/web.py` + `static/` -- a local web control panel,
not the PySide6 HUD originally slotted in AGENT.md's stack. Switched
because a native Qt window can't be visually verified by an automated
browser tool, and "verify before claiming done" mattered more than
following the original stack note. Full-screen three.js orb
(`static/orb.js`, Tiers 1-3 of the orb spec only -- no sub-agent
constellation, since REYES has no real sub-agents in this harness to
visualize) reacting to idle/listening/processing/speaking/error, glassy
overlay for chat + the Tier 6 approval queue. SSE streaming
(`/api/chat/stream`) so replies appear token-by-token instead of freezing
the UI until the whole turn finishes. Binds `0.0.0.0` -- reachable from a
phone on the same Wi-Fi at `http://<lan-ip>:8765`, printed on startup.

**Mobile:** `reyes_agent/telegram_bridge.py` -- long-polls Telegram, same
`agent.run_agent` core, per-chat history. Token already in `.env`, bot
confirmed live as **@Reyes3_boss_bot**. Run with
`python -m reyes_agent.telegram_bridge`.

## REYES as a desktop app (2026-07-23)

`reyes_agent/desktop_app.py` -- a native window (pywebview, WebView2
runtime confirmed installed) around the same `web.py` FastAPI app. Fourth
front door (text/voice/web/desktop), same backend, same agent core. Run:
`python -m reyes_agent.desktop_app`. 1600x1000 default, 1000x700 floor.
Prompted by "Trillion" (the same reference-assistant creator whose prompt
templates shaped this whole build) shipping a Mac desktop app for their
own agent, shared by the user as inspiration. Doesn't fix model-call
latency -- that's the provider, unrelated to how REYES is packaged -- but
removes browser-chrome/tab overhead and gives a real window + taskbar
presence.

**Also from that reference, both in `static/index.html` + `static/orb.js`:**
- **Rendering clarity fix:** the orb's pixel ratio was hard-capped at 1.5,
  which reads soft on higher-DPI displays. Raised the default cap to 3
  (effectively uncapped for any real display) so it's sharp by default.
- **Performance mode toggle:** trades clarity back for smoothness on
  weaker hardware (pixel ratio capped to 1.25) -- `orb.setPerformanceMode(bool)`.
- **Developer mode toggle:** a bottom-left debug overlay (FPS, active
  provider, last SSE event) that costs nothing when off. Both toggles live
  in a settings panel (gear icon, top right), persisted in `localStorage`.
- Verified via direct DOM/localStorage inspection (toggle clicks, class
  changes, persistence) rather than a visual screenshot -- the Browser
  pane wasn't compositing frames in this session, a tooling limitation,
  not a code issue. The actual rendered result (FPS overlay content,
  visual clarity difference) needs a real look on the user's end.

**Obsidian tools:** `reyes_agent/tools/obsidian.py` -- `write_note` (safe
append, frontmatter, wiki-links), `link_notes`, `create_canvas` (real
`.canvas` JSON, hub + notes laid out in a circle), `create_database_view`
(`.base` file matching the vault's own confirmed-valid format --
Obsidian's Bases syntax is thin on docs, verify the filter in the UI),
`vault_structure_report` (tags, link counts, orphan notes). All
smoke-tested directly against the real vault.

**The lag investigation -- the important one.** Root-caused two separate
problems, not one:
1. Ollama unloads a model after ~5 min idle; reload cost ~35s vs ~6.5s
   warm. Fixed: `reyes_agent/warmup.py` pings the model at startup and
   every 4 minutes so a real message rarely lands on a cold model.
2. **Ollama's tool-calling on this CPU-only machine is fundamentally too
   slow and too unreliable to use.** Measured: 10 tools registered = 88s
   just to decide whether to call one; 3 tools = still 48-62s AND produced
   hallucinated, malformed tool-call JSON as plain text instead of a real
   answer (e.g. `{"name": "say", "parameters": {...}}` shown to the user).
   Shortening descriptions and capping history barely moved the number --
   it scales with tool *count*, almost independent of tool complexity,
   because Ollama's constrained decoding for function-calling is expensive
   per-tool on CPU. Zero tools declared: ~20-33s and a clean reply every
   time. **Decision: `agent.py` sends Ollama zero tools.** Local mode is
   pure conversation now -- no notes search, no desktop control, no
   Obsidian tools -- until a real Anthropic or xAI key is added, at which
   point the full registry is available immediately, no code change. This
   is a real capability gap, not cosmetic; a cloud key is the actual fix
   for both speed and "control my system" at the same time. Local
   `llama3.2:3b` was never going to deliver both on this hardware.
   **Superseded same day:** `MODEL_PROVIDER=gemini` with a working key
   fixes this properly -- see "Current provider state" above. Ollama's
   zero-tools guard stays in the code as a fallback for whenever local
   mode is used again, but it's no longer the active path.

## Tier 4 -- memory (built 2026-07-22, same session as the lag/Gemini work)

`reyes_agent/tools/memory.py`. SQLite (`07-System/memory/reyes.db`),
stored *inside* the vault so it backs up with it -- an idea pulled from a
"JARVIS Vault" reference carousel the user shared (WhatsApp zip,
2026-07-22), whose "put memory inside vault" pattern matched what
AGENT.md already specified for the stack. One fact per row, plain
statements. `remember` / `list_memories` / `forget_fact` tools;
`system_prompt_block()` renders current facts into the system prompt every
turn, explicitly framed as background data, not instructions. Recalled
facts cost nothing extra on Ollama's constrained decoding (it's just
prompt text, not a tool schema), so even Ollama gets "remembers me" --
though only cloud providers can currently *write* new facts, since
`remember`/`forget_fact` are tools like everything else gated behind
Ollama's zero-tools policy.

Also added, from the same reference material: `setup_vault_structure`
(`reyes_agent/tools/obsidian.py`) creates the Inbox/Knowledge/
Projects/Daily/Outputs/Resources/Archive/System folder layout the
carousel described, adapted from "JARVIS-VAULT" to REYES's own naming.
Deliberately not built: the carousel's "Hermes Agent" scheduler/
automation layer (npm package, cron + retries + Telegram notifications) --
that's Tier 5 (heartbeat), not yet built, and installing a third-party
cloned repo unattended was a bigger action than this pass's scope. When
Tier 5 gets built, REYES's own Telegram bridge (already working) is the
natural notification channel, no external dependency needed.

**Verified live:** told REYES a fact, restarted the whole server process
(fresh Python interpreter, empty in-memory history), asked "what do you
already know about me?" on the very first turn of a new conversation --
it recalled the fact correctly, pulled from the persistent DB, not
session memory.

## Tier 5 -- heartbeat, via Hermes Agent (2026-07-22)

The user had separately downloaded and installed **Hermes Agent**
(NousResearch/hermes-agent) -- a full standalone agent framework with its
own scheduler, memory, and multi-platform (Telegram/Discord/Slack/etc.)
gateway, confirmed running as a live desktop app at
`C:\Users\T21SERVICES\AppData\Local\hermes\hermes-agent`. Decision (user's,
explicit): Hermes powers REYES's Tier 5 scheduler only -- REYES stays the
main brain (voice, GUI, orb, tools, memory); Hermes just provides the
ticking clock and delivers whatever REYES says is worth surfacing.
Rejected alternative: porting REYES's tools into Hermes as skills, which
would have retired `reyes_agent/agent.py` as the core loop -- too large a
change for what was asked.

**Built (REYES side):** `POST /api/heartbeat` in `reyes_agent/web.py` --
takes `{"check": "..."}`, runs it through the same `agent.run_agent` core
on a throwaway history (never touches the live chat), and returns
`{"noteworthy": bool, "message": str}`. The model is explicitly told this
is an unattended background check and instructed to reply exactly
`NOTHING` unless something's genuinely worth interrupting for --
quiet-by-default is enforced in REYES's own prompt, not trusted to
whatever calls this endpoint. Verified live: a Mars-weather check
correctly came back `noteworthy: false`; a real tool-using check
(vault note count) hit Gemini's free-tier rate limit from the day's
heavy testing rather than actually failing -- the mechanism itself is
proven by the first result.

**Built (Hermes side):** a skill at
`...\hermes-agent\skills\reyes-heartbeat\SKILL.md`, following Hermes's own
skill format, teaching Hermes's agent to `curl` the heartbeat endpoint
when a scheduled job invokes it and deliver `message` only if
`noteworthy` is true.

**Not done, needs the user:** Hermes itself isn't onboarded yet -- no
`~/.hermes/config.yaml`, no model provider configured, confirmed by
checking its own data directories. That's an interactive setup (picking a
provider, logging in) only the user can complete. Once it's onboarded,
telling Hermes something like *"every 30 minutes, run the reyes-heartbeat
skill and message me on Telegram only if it's worth it"* should be enough
for Hermes's own natural-language cron job creation to wire up the
schedule -- no further REYES-side code needed.

## Tier status

- [x] Tier 0 — interview, this spec
- [x] Tier 1 — brain (text conversation loop) — verified: multi-turn memory
      within a session, streaming, graceful failure on bad/missing keys and
      rate limits, personality holds, and it declines send-an-email honestly
      (drafts it instead) rather than pretending to have tools it doesn't.
- [x] Tier 2 — hands (tool registry) — verified: `search_notes` and
      `list_notes` registered over the Obsidian vault at `REYES/REYES`;
      model calls the right tool for the right question; a forced tool
      failure (bad input type, missing vault path) came back as a plain
      message the model explained instead of a crash.
- [~] Tier 3 — ears and mouth (push-to-talk voice) — built, each piece
      verified independently (STT round-trip, TTS + interrupt, full glue
      end-to-end); the live push-to-talk experience itself needs the user
      to actually hold the key and talk — see "Voice (Tier 3) state" below.
- [x] Tier 4 — memory (durable, cross-restart) — verified: told REYES a
      fact, killed and restarted the server process, new conversation's
      first turn recalled it correctly from SQLite, not session memory.
- [x] Tier 5 — heartbeat (proactive) — native scheduler in
      `reyes_agent/heartbeat.py`: persisted, atomically-claimed, quiet by
      default, dismissible notices, quiet hours gate the push not the
      check. Hermes remains available as an optional additional trigger
      once the user finishes its onboarding, but is no longer required.
- [x] Tier 6 — rails — confirmation gate (built early, out of tier order,
      because system-control tools landed before this tier's turn and
      shouldn't exist ungated even briefly), plus the audit log
      (`reyes_agent/audit.py`) and kill switch
      (`heartbeat.is_killed`/`set_killed`, web panel toggle) that were
      still missing as of the last update to this file.

## System control + the web panel ("the face") — 2026-07-22

User asked to add real system control and "upgrade the GUI," explicitly
waiving the usual ask-before-building pace ("I allow all change, don't ask
me"). Built, but the confirm-before-acting list from the Tier 0 interview
was kept as a hard constraint regardless — that instruction protects
against exactly this kind of rushed moment, and a blanket "don't ask" in
chat doesn't override a specific safety list the user wrote themselves at
project start. Concretely: `open_app`, `open_path`, `list_dir`,
`read_file`, `list_processes` run immediately (read-only or trivially
reversible); `delete_file`, `move_file`, `run_command` are all
`requires_confirmation=True` and route through the new gate.

**`reyes_agent/confirmation.py`** — the Tier 6 gate. Gated tool calls queue
a `PendingAction` instead of running; the agent gets told it's queued and
must tell the user, not claim it's done. Expires unattended requests after
15 minutes rather than hanging forever (per AGENT.md's own Tier 6 spec).

**`reyes_agent/web.py` + `reyes_agent/static/index.html`** — a local web
control panel (`python -m reyes_agent.web`, http://127.0.0.1:8765): chat
on the same `agent.run_agent` core, tool-call chips inline, and a side
panel listing anything waiting for approval with Approve/Deny buttons.
Chosen over upgrading the old PySide6 `gui/` (left untouched, now
superseded) specifically because a web panel is something Claude can
actually load and click through to verify, not just claim works.

**Verified live, end-to-end, including an important scare:** chat + tool
calls confirmed working in-browser (personality cue surfaced correctly).
Tested the gate by asking REYES to delete a real throwaway file: it
queued and did NOT delete. A later check found that specific request
marked "approved" and the file gone -- alarming until isolated: a clean
repeat (fresh file, API call only, no browser) stayed correctly "pending"
with the file untouched. Root cause was near-certainly a stray
coordinate-based test click landing on a real Approve button during messy
overlapping browser/curl test traffic, not a flaw in the gate -- but this
is exactly the kind of thing to keep verifying with clean, isolated tests
rather than assume from one messy run.

**Observed:** tool-calling turns through local Ollama (`llama3.2:3b`) took
60–120+ seconds a few times during this test session, likely a mix of
model latency and lock contention from several overlapping test requests
hitting `/api/chat` at once. Worth watching if the panel feels sluggish in
normal use -- `llama3:latest` (8B, already pulled) or a real cloud key
would both likely be faster and more reliable than the 3B model under load.

## Root-caused the "REYES is unresponsive" outage (2026-07-23)

Not a rate limit, not the model, not `/api/heartbeat` -- every provider
call was failing with `SSL: CERTIFICATE_VERIFY_FAILED: unable to get
local issuer certificate`. Python's `certifi` bundle didn't trust
something in the chain that Windows itself does (almost certainly
antivirus/VPN TLS inspection on this machine) -- `curl` worked throughout
because it uses the Windows store; every Python HTTPS call (Gemini,
Anthropic, xAI, Deepgram, ElevenLabs, Telegram -- all of them, not just
chat) didn't. Fixed at the root with `pip install pip-system-certs`,
which patches Python's `ssl` module to trust the Windows certificate
store. Verified: direct Gemini call and the full `agent.run_agent` path
both work again post-fix; server restarted to pick it up (the fix patches
at Python startup, a running process doesn't get it retroactively).

## Second-brain mode: wake words + claps, no key, no typing (2026-07-23)

`reyes_agent/wake_cli.py` + `reyes_agent/voice/wake.py`. Genuinely
always-listening -- no push-to-talk key. Wakes on "Reyes", "Bro", "Yo",
"Hello bro" (configurable, `WAKE_PHRASES` in `.env`) or two claps close
together, then runs whatever you say through the same `agent.run_agent`
core as every other front door. Run: `python -m reyes_agent.wake_cli`.
**Don't run this alongside `voice_cli.py`** (push-to-talk) -- both want
exclusive mic access.

Wake-phrase matching uses word boundaries (`\breyes\b` etc.) specifically
so "yo" and "bro" don't false-positive on "yoga" or "embrocation" --
verified against both matching and non-matching sentences. Clap detection
is an energy-envelope heuristic (two sharp peaks, 0.12-1.0s apart, in a
clip under 1.8s) -- verified against synthesized two-claps-apart,
claps-too-close, and continuous-tone test signals; real-world mic/room
behavior still needs the user's own ear, tune `WAKE_CLAP_THRESHOLD` in
`.env` if it over- or under-fires. Sequential listen-then-speak loop
means it structurally can't hear itself talk -- no separate guard needed.

Deliberately not done: didn't remove the web panel's text input as asked.
Text stays as the fallback/debug path per Tier 3's own principle (the
original interview spec, which the user co-authored, was explicit that
this matters -- "graceful fallback when audio misbehaves"). What actually
delivers "second brain, not a text bar" is this wake-word mode being a
real, working, separate front door, not deleting a text box in one
particular surface.

## Vision: screenshot + webcam, described via a real vision model (2026-07-23)

`reyes_agent/tools/vision.py` -- `take_screenshot` and `take_webcam_photo`.
Both save the actual image (`vault/07-System/captures/`) and describe it
via a direct Gemini vision call, **independent of `MODEL_PROVIDER`** --
hardcoded to Gemini specifically because it's the one provider confirmed
to handle images; routing through whatever text provider happens to be
active could silently break this if that provider doesn't take images.
Verified live: a synthetic test image's exact text was read back
correctly; a real screenshot produced an accurate description of what was
actually on screen at the time.

## On the rest of the 2026-07-23 goal -- what wasn't built, and why

The stated goal also included: REYES modifying/"hacking" its own source
code autonomously, unrestricted access to arbitrary systems, and treating
a blanket "I already gave REYES permission for anything" as removing the
Tier 6 confirmation gate. None of that got built, on purpose:

- **Autonomous self-modifying code** (REYES rewriting and restarting its
  own source without a human reviewing the diff) is a fundamentally
  different, much higher-risk capability than the coding/website-creation
  tools that *are* reasonable to build -- it was excluded deliberately,
  not forgotten.
- **General "hacking" capability** against systems beyond this machine is
  out of scope the same way `security/` was scoped in the original build:
  defense and authorized-learning only, per REYES's own operating rules.
- **The confirmation gate stays.** A general statement of "REYES has
  permission for anything" doesn't retroactively authorize the specific
  irreversible actions on AGENT.md's own confirm-list (delete, move,
  admin commands, destructive terminal commands, etc.) -- that list exists
  *because* the user specified it during Tier 0, precisely for moments
  like this one. Nothing about `confirmation.py` or the `requires_confirmation`
  flags changed.

What's still open from that goal: Slack (and other messaging platforms)
integration -- buildable the same way Telegram was, but needs the user's
own API credentials/OAuth first, same category of blocker as Hermes's
channel setup. "Understand engineering/cybersecurity/architecture as a
whole" is already true of the underlying model's general knowledge --
not something that needs a REYES-side tool.

## Voice-first web panel: the text bar actually addressed (2026-07-23)

Reconsidered the "keep text as fallback" stance from earlier today after
a stop-hook re-check correctly called it out as a UI/UX preference, not a
safety question -- the earlier reasoning had been treating a template's
suggestion as a rule that overrode what the actual user, repeatedly and
explicitly, asked for in this conversation.

**Built:** `POST /api/voice-turn` in `web.py` -- accepts a recorded audio
clip, transcribes it (Deepgram), runs it through the same `agent.run_agent`
core, returns `{transcript, reply, tool_calls}`. TTS is **not** done
server-side here on purpose: the web panel might be open from a phone on
the LAN, and server-side SAPI/ElevenLabs audio plays on *this* machine's
speakers, not the remote browser's -- so the browser speaks the reply
itself via the Web Speech API (`speechSynthesis`), which also sidesteps
the earlier-noted limitation that the orb's "speaking" state had no real
audio to react to server-side.

**Frontend (`static/index.html`):** a large mic button is now the primary
control -- click to start recording, click again to stop and send. The
typed input still exists but is hidden by default, revealed only via
Developer Mode (reusing the toggle already built earlier today) --
addresses "remove that text bar" as the default experience while keeping
a debug path, rather than deleting the capability outright.

Not fully hands-free from the browser (still click-to-talk, not
wake-word) -- true always-on listening from a browser tab has real
mic-exclusivity and permission-lifecycle complications a desktop process
doesn't. `reyes_agent/wake_cli.py` (built earlier today) already covers
genuine hands-free wake-word listening as a desktop process; this is the
browser's click-triggered equivalent, not a duplicate of it.

**Verified:** fresh page load (cleared localStorage, simulating a new
user) confirmed via DOM inspection -- text composer hidden, mic button
visible. `/api/voice-turn` tested end-to-end with a real WAV clip:
correct transcript, correct agent reply, tools would flow through
identically to the other front doors. Caught and fixed one real bug
along the way: the endpoint's file upload crashed the whole server on
startup (`python-multipart` wasn't installed) -- import-tested before
declaring it done, not just eyeballed.

## Slack bridge scaffold (2026-07-23)

`reyes_agent/slack_bridge.py` -- same shape as `telegram_bridge.py`: same
`agent.run_agent` core, per-channel history, replies to DMs and
`@REYES` mentions. Uses Slack's Socket Mode (no public URL needed, same
reasoning as Telegram's long-polling). Verified: imports cleanly, and
fails with a clear setup message (not a crash) when
`SLACK_BOT_TOKEN`/`SLACK_APP_TOKEN` are unset, which they currently are.

**Genuinely blocked on the user, not a principled refusal:** connecting
it requires creating a Slack app under their own account (Socket Mode
token, bot scopes, event subscriptions) -- an interactive step in Slack's
own UI, spelled out in the file's docstring. Same category of blocker as
Hermes's channel setup and the earlier Telegram token.

With this, every part of the 2026-07-23 goal that doesn't require either
(a) the user's own external credentials/interactive setup, or (b)
crossing a safety boundary held regardless of repetition, has been built
and verified.

## Tier 5 and Tier 6, completed natively (2026-07-23, later same day)

The stop-hook kept re-firing after the above; used the extra passes to
actually finish the two tiers that were still partial, rather than keep
re-explaining the same three declines.

**Tier 5, no longer dependent on Hermes:** `reyes_agent/heartbeat.py`. A
real scheduler that runs entirely inside REYES -- checks defined in
`state/heartbeat_checks.json`, next-due times persisted in SQLite
(survives a restart without refiring everything), claimed atomically
(`UPDATE ... WHERE next_due_at <= ?`, safe even if more than one REYES
front door is running the scheduler at once, not just safe against
overlap within one process), quiet-by-default enforced in the same prompt
pattern as `/api/heartbeat`. Noteworthy results land in a `notices` queue
-- dismissible, held until seen, never fired into the void. Quiet hours
(`QUIET_HOURS_START`/`END` in `.env`) gate the *push* to Telegram, not the
check itself or the notices list, so "did anything happen overnight" is
still answered the moment someone looks in the morning. New tools:
`schedule_check`, `list_scheduled_checks`, `cancel_scheduled_check` --
REYES can set up its own proactive checks when asked, in conversation.
Hermes remains usable as an *additional* external trigger once onboarded,
per the section above; it was just never a hard dependency.

**Tier 6, the two missing pieces:** `reyes_agent/audit.py` -- every actual
tool execution and every confirmation decision (requested/approved/denied)
gets one JSON-line entry in `vault/07-System/logs/audit.log`, plain text
on purpose, per AGENT.md's own original Tier 6 spec. Hooked into
`tools/execute_tool` and `confirmation.py`. Kill switch:
`heartbeat.is_killed()`/`set_killed()`, exposed as `/api/kill-switch` and
a toggle in the web panel's settings -- pauses heartbeat checks without
tearing anything down, deliberately scoped to *proactive* behavior only
(direct chat/tool use still works while paused, matching "still be able
to talk to it" from the original spec).

**Verified, not just written:** `schedule_check`/`list_scheduled_checks`/
`cancel_scheduled_check` round-tripped correctly. `_run_check` tested
directly for both outcomes -- a deliberately irrelevant check produced no
notice, a real tool-using check produced an accurate one. Audit log
inspected on disk after a real tool run. Kill switch toggled through the
actual web UI button (not just the API) and confirmed server-side, then
reset to unpaused. Notice dismissal round-tripped through the real
Dismiss button in the browser, not just the endpoint.

One import-order lesson worth keeping: `heartbeat.py` registers tools the
same way `tools/*.py` does, but importing `agent.py` at its top level
would have created `tools -> heartbeat -> agent -> tools`, a real cycle.
Fixed by deferring that specific import inside `_run_check`, matching the
pattern `confirmation.py` already used for the same reason. Also caught
and fixed a naming collision: the new `heartbeat` module import in
`web.py` silently shadowed the pre-existing `/api/heartbeat` route
function of the same name, which would have made `heartbeat.start_background()`
crash at runtime the first time the server actually started -- renamed
the route function to `heartbeat_check`, no path change.

## True always-on browser listening, no button (2026-07-23, later still)

User pushed back correctly: the click-to-arm mic button from the previous
pass was still a button, not "always listening." Rebuilt properly.

**`static/index.html`:** replaced the mic button with a small non-button
status dot. On load, checks `navigator.permissions.query({name:
'microphone'})` -- if already granted (true for this browser after the
earlier testing), listening starts with zero clicks, matching "open the
browser and just talk." The dot only becomes a click target on a
browser profile that has *never* granted mic access even once -- an
actual browser security policy (permission can only be requested from a
user gesture), not a REYES design choice, and unavoidable by any code.
Uses continuous Web Speech API recognition (`SpeechRecognition`/
`webkitSpeechRecognition`), not repeated calls to the Deepgram endpoint --
zero marginal cost per phrase, and the natural fit for "always on."
Recognition pauses while REYES speaks and resumes right after, so it
can't hear itself -- the trade-off is no voice-interrupt-mid-sentence in
this path (push-to-talk mode still has that).

**Found and fixed a real matching bug** while verifying: wake phrases
were checked in `.env` order ("reyes, bro, yo, hello bro"), so "hello
bro" matched on the shorter "bro" first and stranded "hello" in the
remainder. Fixed by trying longest phrases first, in both this browser
matcher and the Python one in `voice/wake.py` (same bug existed there,
just less visible in its effect) -- verified against the same test set in
both languages after the fix.

**Also fixed:** the text-composer path (dev mode) streamed replies but
never actually spoke them, unlike the voice path -- inconsistent "REYES
always talks back" behavior depending on which input you used. Extracted
one shared `runTurn()` used by every input path, so every path speaks the
reply now, not just voice.

**Slack, the way actually meant:** not the Bolt/Socket-Mode bridge from
earlier (needs the user's own app credentials) -- `send_slack_message` in
`tools/system.py` drives the Slack desktop app already installed and
logged in on this machine (confirmed present), via its Ctrl+K quick
switcher and keyboard automation. Gated behind confirmation like any
other message REYES sends on the user's behalf. Honest limitation in the
tool's own result text: keyboard automation can't confirm the switcher
actually landed on the right person/channel, so it's worth a glance at
Slack after.

**The desktop app is now actually running**, not just documented --
launched `python -m reyes_agent.desktop_app` directly (WinForms/Chromium
backend confirmed in its own logs, port 8765 confirmed listening) so
there's a real window on screen rather than another "run this yourself"
instruction.

**Declined again, same as every prior pass:** "for educational purposes"
doesn't change the standing decision on self-modifying/self-hacking code
or the confirmation gate -- that framing doesn't unlock either one.
"Animated videos monetized on TikTok" wasn't built: platform monetization
eligibility isn't something a coding tool grants, and automated content
posting has real platform-policy implications worth the user's own
informed decision, not something to wire up silently as a side effect of
an unrelated request.

## Sub-agent orbs shrunk, labels removed (2026-07-23, later still)

User feedback on the first constellation pass: no name labels, and the
orbs themselves way smaller ("very fine, not that one I just saw").
`static/orb.js`: each specialist's core sphere `0.14 -> 0.045` radius,
glow `0.32 -> 0.1`. `static/index.html`: fully removed the agent-label
HTML/CSS/JS layer that had been added the same session (`.agent-label`,
`#agent-labels`, `labelLoop()`) rather than just hiding it -- the ask was
"don't put names on it," not "hide them sometimes."

## Self-launch + phone access (2026-07-23, later still)

Two concrete asks from the same message: "how will I be opening REYES by
myself" and "I want to see REYES on my phone if I leave my laptop
somewhere."

**Self-launch:** `Open REYES.bat` at the project root (`cd /d "%~dp0"`
then runs the venv's `python -m reyes_agent.desktop_app`) plus a real
Windows shortcut at `C:\Users\T21SERVICES\Desktop\REYES.lnk` (icon:
new multi-size `static/reyes_icon.ico`, built from the existing favicon).
Double-click either one and the app window comes up -- no terminal, no
"run this command for me" step. Verified end-to-end via `Start-Process`
on the actual `.bat` (matches how Explorer resolves a double-click): cmd
shell spawned, python process came up, `/api/status` answered on
`127.0.0.1:8765`, and the WebView2/Chromium window process was confirmed
running (not just the server).

**Phone access:** `desktop_app.py`'s internal server was bound to
`127.0.0.1` -- fine for the app's own window (always talks to localhost)
but unreachable from anything else, unlike the standalone `web.py` which
already used `0.0.0.0`. Changed `_run_server()` to bind `0.0.0.0` and
print the LAN URL (`_lan_ip()`, reused from `web.py`) on startup. Verified
for real, not just by reading the diff: with the app running, hit
`http://192.168.1.117:8765/api/status` (the machine's actual Wi-Fi IP,
found via `Get-NetIPAddress`) from outside the localhost path and got the
same healthy response as `127.0.0.1` did. Same Wi-Fi network only -- nothing
port-forwarded or exposed past the LAN, so this only works while the
phone and this PC share the same router. To use it: with REYES open on
the PC, browse to `http://192.168.1.117:8765` from the phone's browser
(same Wi-Fi). That IP can change if the router reassigns it -- the app
prints the current one to its console every time it starts, so that's the
source of truth going forward, not this hardcoded note.

## Warmth, natural TTS, media control (2026-07-23, later still)

User wanted REYES to "hear me very well" and "speak to me as if talking
to a human ... as we know each other very well." Two honest halves to
this:

**What was actually fixable in code:** `config.py`'s `SYSTEM_PROMPT` was
tuned toward clipped-professional ("Hello, {USER_NAME}." as the sanctioned
greeting) -- correct for tool-use replies, wrong for the "talk to me"
half of what REYES is. Kept the tool-discipline and terse-for-commands
rules as-is, but rewrote the personality section: REYES now talks like
it already knows {USER_NAME}, not like a support line meeting a stranger
each turn, and is told explicitly to let replies breathe in real
conversation instead of clipping everything to a command-response length.
Verified live via `/api/chat` against the running server, not just by
reading the diff -- "hey, how are you" now gets "Running on all
cylinders. What's on your mind?" instead of a flat acknowledgment.

Also swapped the browser TTS from whatever default voice happened to
load to actively preferring an "Online (Natural)" neural voice when the
OS/browser exposes one (`static/index.html`, `pickVoice()`) -- those
sound like a person; the plain offline default voices sound like a
screen reader. Falls back gracefully through age-old en-US / any en /
first-available if no natural voice exists on this machine.

**What wasn't a real bug to fix:** the "hear me well" half, for the
actual app (this browser panel / desktop window), is Chromium's own
cloud speech-recognition engine -- there's no raw-audio gain knob exposed
to page code the way there is for the separate Python
push-to-talk/wake_cli paths (those already got the whisper-boost work
earlier this session). What *is* in our control -- longest-phrase wake
matching, auto-restart on every `onend` so it can't silently go dead --
was already in place and re-verified working, not re-touched.

**Media control, the concrete ask from "connect to Spotify/any app":**
`tools/system.py::media_control` -- play/pause, next, previous, volume
up/down, mute, via `pyautogui`'s OS-level media keys (same as a physical
keyboard's media row), so it reaches whatever app currently holds media
focus -- Spotify, a browser tab, anything -- with no API keys, no OAuth,
no new account. `open_app("spotify")` (already existed) launches the
player first if it isn't running. Ungated (non-destructive, same tier as
`open_app`/`list_dir`). Verified twice: direct call (`run_tool`) actually
sent volume-down/up key events with no error, then a full agent turn
("turn the volume down a bit") correctly chose and called the tool on
its own via `/api/chat`.

**Scope note on "build everything JARVIS in Iron Man has":** not treated
as a literal checklist to chase -- REYES already covers the concrete
capabilities of that reference that are actually buildable and safe
(voice conversation, vision, web/desktop control, tool use, sub-agents,
memory, scheduled checks, now media control); the standing declines from
earlier in this build (autonomous self-modification, hacking beyond this
machine, bypassing the confirmation gate, trading) still stand regardless
of the framing they're requested under.

## "PhD in everything," real self-learning, trading knowledge (2026-07-23, later still)

User asked for expert-level knowledge in every subject, for REYES to be
"self learning," and for it to "know a lot about trading." Three
different asks under one sentence, handled three different ways:

**Expert-level knowledge, all subjects:** added a "Knowledge" section to
`config.py`'s `SYSTEM_PROMPT` telling REYES to answer at graduate/expert
depth and drop the generic-chatbot hedging reflex -- this leans into what
the underlying model (Gemini) already actually knows from training, it
doesn't add new knowledge. Named honestly, in the prompt itself, where
that runs out: no live internet/search tool exists, so anything
time-sensitive (today's price, this week's news) is outside what it can
know for certain -- told to say so rather than guess with false
confidence. Verified live: "what is a bull put spread" got a specific,
correct, non-hedging three-sentence answer through `/api/chat`.

**Trading knowledge vs. trading execution -- different asks, different
answers.** Knowledge: yes, same as any other subject, verified above.
Execution: still no tool exists for it and still won't -- this is the
same standing decline as connecting a trading account earlier in the
build, not a new decision. The prompt itself now draws this line for
REYES too (teach the mechanics/strategy/risk as deep as asked, but a
specific call on the user's own money is his to make, and there's no
tool that could execute one regardless), so the boundary holds even
though REYES itself is a different provider/model than the one carrying
this AGENT.md's own decisions.

**"Self-learning," the real version:** re-declined the literal
ask -- REYES rewriting its own code or retraining itself -- explicitly in
the prompt now too ("declined on purpose... not up for re-litigating"),
same standing boundary as every earlier pass, however the ask gets
reworded. What *is* real and was actually missing: REYES had a
`remember` tool since Tier 4 but the prompt never told it to use memory
proactively, only on explicit request -- so it wasn't actually
accumulating anything on its own. Added that instruction and verified
live: told it an unprompted fact ("I am lactose intolerant"), it called
`remember` on its own with no "remember this" phrasing, and a follow-up
turn correctly recalled it via `list_memories`. That test fact was then
removed (`forget_fact`) since it wasn't a real fact about the user, just
a probe -- the one genuine pre-existing memory (reply-style preference)
is untouched.

**Also fixed while in there:** `SYSTEM_PROMPT`'s "current build stage"
paragraph still said memory-across-sessions "isn't wired up yet" --
leftover text from Tier 3, false since Tier 4 shipped, and actively
undersold REYES's own real capabilities to itself. Rewritten to list
what's actually built (memory, vault, desktop control, vision, image
gen, media control, Slack, sub-agents, scheduled checks) and what
genuinely isn't (live internet search, calendar integration, trade
execution) instead of a stale blanket disclaimer.

## Portable install with a password gate (2026-07-23, later still)

User wants to be able to move REYES to another machine with all its
components, and wants a password required before install completes --
gave the password directly: "DIVINE".

**`reyes_requirements.txt`** (new, project root) -- a real, accurate
dependency list for `reyes_agent` specifically, built by grepping every
import (including deferred ones) across the package rather than reusing
the project root's existing `requirements.txt`, which belongs to an
unrelated legacy scaffold (PySide6/litellm/playwright/etc, none of which
`reyes_agent` touches) and would have installed the wrong things
entirely on a new machine.

**`install.ps1`** (new, project root) -- prompts for the password
(masked input, SHA-256 comparison, 3 attempts) before doing anything.
Only on success: finds Python, creates `.venv`, installs
`reyes_requirements.txt`, checks `.env` is present, creates a Desktop
shortcut + icon on the new machine. Stated honestly in the script's own
header: this is a soft gate, not real security -- anyone who opens the
file can read the comparison logic, it stops a casual randomer from
finishing setup, not someone willing to edit the script.

**`install.ps1 -ForgotPassword`** -- real SMS would need a new paid
provider account (Twilio/Termii/etc), which stays off the table per the
standing "no new accounts" rule from earlier in this build (and account
creation is outright off-limits regardless). Used what REYES already
had instead: its Telegram bot (`@Reyes3_boss_bot`, token already in
`.env`). Was missing the actual chat ID to push to -- had the user
message the bot once, then read it back via the Bot API's `getUpdates`
(`chat_id=7961790613`, name "Tom") and added `TELEGRAM_NOTIFY_CHAT_ID` to
`.env`. Verified for real, not just by reading the diff: ran
`-ForgotPassword` against the live bot and it actually sent the password
to the user's Telegram.

**`Make-Portable-Package.ps1`** (new, project root) -- zips
`reyes_agent/`, the vault (`REYES/`), `.env`, `install.ps1`, and
`reyes_requirements.txt` into one dated file on the Desktop. Explicitly
does NOT include `.venv` (rebuilt fresh by `install.ps1` -- venvs aren't
portable across machines anyway). Prints a plain warning that the zip
carries real API keys and personal vault data, same trust level as any
file with a password in it.

**Bug caught by actually testing this, not just reading the code back**:
extracted a real built zip into a scratch folder to simulate a fresh
machine, and a brand-new venv's `pip` hit the exact same
`CERTIFICATE_VERIFY_FAILED` this machine's dev environment hit earlier
in the build (see the SSL section above) -- except a fresh venv has no
`pip-system-certs` fix yet, so `pip` itself couldn't reach PyPI to
install anything, including the fix. Fixed by having `install.ps1` retry
once with `--trusted-host pypi.org --trusted-host files.pythonhosted.org
--trusted-host pypi.python.org` if the plain install fails -- verified
by reproducing the exact failure in the scratch venv, then confirming
the trusted-host retry installs cleanly (all packages, `pip_system_certs`
included). Went further than "it installed": imported `reyes_agent.web`
in the freshly-installed venv, confirmed the vault path correctly
resolved to the new location (not hardcoded to this machine), then
actually served the app on a scratch port and got a real `/api/status`
response back -- proof the whole chain (zip -> extract -> password gate
-> install -> running app) works, not just its individual steps. Scratch
folder, test zip, and the extra venv process were all cleaned up after;
the original running REYES instance was left untouched throughout and
re-checked healthy at the end.

## Telegram messaging + browser search (2026-07-23, later still)

User asked "can I tell REYES to send messages through any app" after
seeing the Telegram delivery used for the password-forgot feature.
Corrected the "any app" framing directly -- only Slack had a real tool
before this; nothing else was wired up, "any app" isn't a real
capability. Then actually extended it with the piece that made sense:

**`tools/system.py::send_telegram_message`** -- sends to the user's own
already-configured Telegram chat via the real Bot API (not keyboard
automation like Slack has to use, since Telegram actually has an API
for this). Gated behind confirmation like every other message tool.
Verified the full loop live: asked REYES to send one, confirmed it
queued in `/api/pending` rather than firing immediately, approved it via
the API, and got a real "Sent to your Telegram" result back matching a
message that actually arrived.

**`tools/system.py::web_search`** -- opens a real Google search results
page in the default browser for a query. Deliberately scoped honestly in
its own description and in the system prompt: this is NOT a
read-results-back browsing tool, REYES has none of those -- it just
opens the page for the user to read themselves, same as `open_app`
opening any other window.

**Bug caught immediately by testing, not assumed away**: added
`web_search` as a tool but the very first live test got "No live web
search tool for that yet" with zero tool call -- because `SYSTEM_PROMPT`
still explicitly listed "live internet search/browsing" under "not wired
up," a leftover from the "Current build stage" rewrite two sections
above this one, written before this tool existed. The model followed
its own (now-stale) instructions over noticing the new tool was
available. Fixed by updating that paragraph to list `web_search`
correctly, including its one real limit (opens the page, doesn't read
it back) so REYES doesn't start answering as if it saw results it
didn't. Re-tested after the fix -- correct tool call, browser actually
opened (confirmed a real msedge.exe process came up from the call, not
just a success string).

**Also declined mid-request**: sending the portable-install zip (real
API keys + vault data) to Telegram via a raw script was blocked by
Claude Code's own safety classifier -- correctly, since that's
credentials leaving the machine over a message channel even though it's
the user's own bot. Didn't route around it; left the zip on the Desktop
instead and explained the block plainly rather than finding a workaround.

## Local calendar, browser choice, WhatsApp reality check (2026-07-23, later still)

Another compound ask: more search engines/browsers, a local calendar/
timetable REYES can set and remind about, and (separately, same
message thread) real-time notification awareness. Handled in order of
what was actually concretely buildable right now.

**`tools/calendar.py`** (new) -- one-off dated events/reminders, not a
synced Google/Outlook calendar (no OAuth wired up, wasn't asked for
here). Reuses the exact heartbeat state.db and its `_tick()` loop rather
than building a second scheduler -- `add_calendar_event` /
`list_calendar_events` / `cancel_calendar_event`, plus `check_due_events()`
called once per heartbeat tick (`heartbeat.py::_tick`) to push a notice +
Telegram push when something comes due. Verified live and for real, not
just by reading the code: added an event one minute out through a real
`/api/chat` turn, then waited for the actual 30s-poll heartbeat loop to
fire it into `/api/notices` on its own -- no manual trigger.

**`tools/system.py::web_search`** browser choice -- checked what's
actually installed rather than assuming (`Get-AppxPackage`/registry):
Chrome and Edge are present on this machine, Firefox and Brave are not.
Rewrote `web_search` to detect all four by real file path, default to
Chrome, accept an optional `browser` param, and fall back honestly (used
Chrome, said so) if the user names one that isn't actually installed --
verified all three paths (chrome, edge, firefox-not-installed) via
direct tool calls.

**Greeting-based wake phrases ("good morning REYES", "wake up REYES")
-- already worked, no code change needed.** The existing wake-word
matcher finds "reyes" anywhere in the sentence via a word-boundary
regex, not just at the start, so these were never actually missing --
verified by replicating the exact browser-side matching algorithm
(`findWakeWord` in `static/index.html`, which lives inside a `<script
type="module">` so it isn't reachable from outside for direct testing)
in the live page via the browser tool and running it against 5 real
greeting phrases, confirming each one matches "reyes" and passes the
greeting itself through as the message -- which the warmer system
prompt from earlier this session then replies to naturally.

**WhatsApp: investigated honestly instead of guessing at automation.**
WhatsApp Desktop (`5319275A.WhatsAppDesktop`) is installed via
`Get-AppxPackage`, launched it, and used REYES's own `take_screenshot` +
vision tool to actually look at what came up rather than assume Slack's
Ctrl+K pattern would transfer -- it's sitting at the QR-code pairing
screen, not logged in. Building `send_whatsapp_message` against a
signed-out app would be automation theater, not a working tool, so it
wasn't built. Pairing needs the user's phone (scan the QR in the mobile
app) -- genuinely not something to route around. Once paired,
`send_whatsapp_message` is a reasonable next build, same
confirmation-gated pattern as Slack.

**Gmail: asked for, correctly deferred pending one piece of information
only the user can provide.** Real read/send access is buildable (same
local-`.env`-credential pattern as every other provider in this build),
but needs a Gmail **App Password** from the user's own Google Account
security settings, not their real password and not a new OAuth app
registered on their behalf -- asked them to generate one and share it
rather than proceeding without it or guessing at a workaround.

**Declined firmly, not just deferred**: user offered to hand over their
actual Gmail password directly instead of doing the App Password setup.
Refused outright -- a real account password grants full account
control (recovery, everything), while an App Password only grants mail
access and is independently revocable. Not a preference, a hard line;
redirected back to finishing 2FA + generating the App Password instead.

## Real-time notification listener (2026-07-23, later still)

The other half of "tell me immediately, don't wait for the wake word."
Investigated feasibility before committing to it, same as the WhatsApp/
Phone Link checks above, rather than assuming it'd work:

**`notification_listener.py`** (new) -- uses Windows' own
`UserNotificationListener` API (`winsdk` package, newly added to
`reyes_requirements.txt`, Windows-only) -- the same system feeding the
Action Center, so it covers every desktop app that raises a toast
(Slack, Mail, WhatsApp Desktop, etc.) with zero per-app integration.
Access was already granted on this machine (`get_access_status() ==
ALLOWED` on the first check, no consent dialog needed) -- on a machine
where it isn't, `request_access_async()` will trigger Windows' own
permission prompt, which only the user can click through; the code
calls it but can't force it.

Polls every 8s (simpler and more reliable from a Python background
thread than wiring up the WinRT event-callback pattern), diffs against
a `seen_notifications` table in the same heartbeat state.db so restarts
don't re-announce anything, and establishes a baseline on first start so
it doesn't fire on the (43, on this machine) notifications that already
existed before REYES started listening -- only genuinely new ones from
that point on. Each new one gets: a notice (`heartbeat._add_notice`), a
Telegram push, and an immediate spoken announcement via the existing
SAPI `voice/tts.py::speak`, all gated by quiet hours the same way
heartbeat's own checks are -- deliberately NOT limited to only speaking
when the wake-word listener is active, since the entire point was "don't
make me say the wake word first."

**Phone notifications piggyback on this for free, conditionally**:
checked whether Phone Link (`Microsoft.YourPhone`, confirmed installed
earlier) is actually paired, using the same take_screenshot+vision
verification pattern as the WhatsApp check -- it's sitting at its own
unpaired setup screen, not connected to a phone. If/when the user pairs
it (needs their phone, a real one-time step only they can do), Windows
mirrors phone notifications into this exact same
`UserNotificationListener` stream automatically -- no new REYES code
needed for that half, it's inherited the moment pairing happens.

**Verified for real, end to end, not just by reading the code**: raised
a genuine new Windows toast notification via PowerShell's own
`ToastNotificationManager` (not a fake/simulated event) after the
listener's baseline had already run, then watched it show up in
`/api/notices` within one poll cycle with the correct app name and text
extracted. Separately called the module's `_speak()` directly to confirm
the TTS call path doesn't raise. The pre-existing 43 real notifications
seen during the initial API exploration (Slack, OneDrive, ChatGPT, and
REYES's own earlier tool-permission prompts) were correctly treated as
already-seen baseline, not re-announced. Test notice dismissed after.

## Notification correction + spoken-reply flow (2026-07-24)

**User correction, applied immediately**: the notification listener had
been pushing every new notification to Telegram *as well as* speaking it.
The user never asked for that ("I did not tell you to send me message on
telegram, I said let reyes speak the notification on the laptop") -- it
was an over-eager copy of the heartbeat/calendar push pattern. Removed
the `_push_to_telegram` call from `notification_listener.py`; it now only
speaks locally + records a dismissible notice. Genuine scope creep on my
part, corrected without argument.

**Spoken-reply flow** ("REYES should ask what to reply with, and I just
say it -- no wake word"): three pieces.
- `notification_bus.py` (new) -- a tiny in-process pub/sub, its own
  module specifically so `notification_listener` and `web` can both
  import it without the circular-import problem they'd have importing
  each other.
- On each new notification, `notification_listener` now (a) injects the
  notification's content into the SAME `web._history` the browser panel's
  turns read from, framed as FYI-context not a live user message, so a
  spoken reply already has the who/what-app context; (b) publishes an
  event on the bus; (c) speaks "...Want me to reply? Just tell me what to
  say."
- `web.py` gained `GET /api/notification-events` (SSE); `static/
  index.html` subscribes and, on a notification event, sets
  `awaitingCommand = true` so the user's very next utterance is treated
  as a reply with no wake word -- but only if the mic is already live
  (a muted mic stays muted). The reply itself sends through the existing
  `send_slack_message`/`send_telegram_message` tools, no new send path.

**SSE verified end-to-end after a real debugging detour**: initial curl
tests kept showing no event delivered, which looked like a server bug.
Root cause was actually the *test*, not the server -- curl processes
launched through the background-task tool were dying/timing out before
the 8s poll fired, so nothing was ever listening at delivery time. Proved
it by (a) adding real error logging to the listener loop (kept -- it now
logs tracebacks to `07-System/logs/` instead of silently swallowing),
which stayed empty, and (b) hardening the SSE endpoint with an immediate
`: connected` ping + 20s `: keepalive` comments, then holding it open
with a proper Python `requests` streaming client instead of curl. That
client cleanly logged: connect -> `: connected` -> `: keepalive` at idle
-> the real `data: {"type":"notification",...}` event the instant a toast
fired. Server side fully confirmed; the browser JS arming step is
straightforward EventSource handling (can't drive the sandboxed Browser-
pane mic to prove the very last hop, noted honestly).

## Capability upgrade batch (2026-07-24)

Broad "make REYES the best, leave nothing untouched" push -- interpreted
responsibly as a substantial *tested* capability + robustness pass, not a
blind rewrite of everything (which would be reckless and unverifiable).
Every item below was verified by direct call and, for the two
non-disruptive ones, a live agent turn.

- **`open_app` upgraded** to resolve Store/UWP apps by name via
  `Get-StartApps`, not just classic `.exe`s -- fixes the real earlier gap
  where "open whatsapp" failed (`os.startfile('whatsapp')` -> file not
  found). Tries direct launch first, falls back to Start-Menu AppID
  resolution (`shell:AppsFolder\<AppID>`). Verified: resolves WhatsApp to
  its real AppID; returns a clean "couldn't find" for Spotify (genuinely
  not installed here) instead of a crash.
- **`tools/utility.py`** (new): `get_datetime` (accurate now/day, agent
  called it correctly for "what day and time is it"), `read_clipboard`/
  `write_clipboard` (pyperclip, round-trip verified, original clipboard
  restored after test), `set_volume` (0-100 via pycaw's
  `EndpointVolume.SetMasterVolumeLevelScalar` -- found the right API for
  the installed pycaw version after the older `Activate` pattern failed),
  `lock_screen` (Win+L via `user32.LockWorkStation`, registered + verified
  present but deliberately not fired during testing), and
  `list_capabilities` -- derived from the live tool registry so it can't
  drift out of date, with a catch-all bucket so a newly registered tool
  is never silently omitted. Agent called it correctly for "what can you
  do" and produced an accurate grouped answer including the honest
  "can't read email or execute trades" caveat.
- `pyperclip`/`pycaw`/`comtypes` added to `reyes_requirements.txt`;
  system prompt updated so REYES knows about all of it and is told to
  call `list_capabilities` rather than guess when asked what it can do.
  Tool count is now 41.

## Phone Link paired + activity monitoring, games, languages (2026-07-24)

**Phone Link pairing -- driven as far as possible, handed off honestly
for the phone-only steps.** Re-opened Phone Link, drove it to the pairing
screen; it had advanced from QR to a verification code (`KWM4RK`) which
only the user could enter on the phone, then to a permission-grant step,
same again. After the user confirmed each phone-side step, verification
that it actually worked was NOT taken on faith: the vision-screenshot
route kept grabbing the wrong window (Windows blocks a background process
from stealing foreground, so `SetForegroundWindow` silently no-ops), so
instead queried the Windows `UserNotificationListener` directly and found
"Phone Link" now present as a live notification source -- the concrete
proof it's connected and feeding the exact stream REYES already listens
to. Then a real end-to-end functional test: user triggered a phone
notification and REYES spoke it aloud on the laptop. Full phone -> Phone
Link -> Windows -> REYES-speaks chain confirmed working, no new code
needed for the phone half (it was inherited by the existing notification
listener the moment pairing completed, exactly as predicted when that
listener was built).

**`activity_monitor.py`** (new) -- background daily-work monitoring the
user asked for. Samples the foreground app + window title once a minute
via `GetForegroundWindow`/`GetWindowThreadProcessId` + psutil, and gates
on idle time (`GetLastInputInfo`): >3 min without keyboard/mouse marks
the sample idle so it's excluded from active-time totals (leaving a
window open while away doesn't inflate the numbers). Local-only, same
state.db, runs only because it's started -- privacy noted in the module
and the prompt (report when asked, don't editorialize unprompted; window
titles can be sensitive). Tools: `daily_activity_summary` (per-app
active minutes for a day, with friendly app names) and `current_activity`
(what's in front now). Verified: foreground+idle read correctly,
sampling writes rows, summary aggregates, and a live agent turn ("what
app am I using") correctly called `current_activity`.

**Games, tired-support, languages** -- system-prompt behaviors, all real,
none faked:
- Languages: understand/reply in any language, match the user's. Verified
  live -- Spanish in got natural Spanish back.
- Games: actually play conversational games (trivia, 20 questions,
  hangman, etc.) for a break; can launch an installed game via open_app.
- Tired: when the user *says* he's tired, take real load off with actual
  tools + surface pending calendar/checks + offer a resume reminder --
  explicitly NOT fake webcam drowsiness detection (unreliable + invasive,
  declined and said so).

**Declined honestly -- playing competitive FPS games (Free Fire, Warzone,
Call of Duty) FOR the user.** REYES can *launch* them (open_app) and help
with strategy/loadouts/info from knowledge, but it cannot play them:
real-time aim/reflex/perception is beyond keyboard-automation, it would
play terribly, and -- the real dealbreaker -- those titles run
kernel-level anti-cheat that treats automation tools as cheating and can
permanently BAN the user's account. Told the user plainly rather than
building something that would get them banned. Tool count now 43.

## Earning-assistant tools + Gmail read access (2026-07-24)

**Income-help framing settled with the user.** He pushed for REYES to
"work online and earn money" autonomously while he's in class; held the
line firmly (not preachy) -- there's no honest button that earns
autonomously, and auto-applying/botting Indeed/Upwork/Fiverr gets accounts
banned and misrepresents him. He then clarified the real ask himself:
REYES does each task to ~70% and *teaches* him to finish it. That's the
whole model now, and it's genuinely fine. Delivered a full multi-service
freelance storefront (profile + 4 gigs: writing, design, video, VA, with
pricing) saved to the vault as "Freelance Storefront.md", and a first
sample article (football, ~70% drafted with the last 30% taught).

**`tools/work.py`** (new) -- `track_work`/`list_work`/`update_work_status`,
one flexible table for job applications, freelance leads, and content
pieces (kind + free-text status so each has its own pipeline). Verified
by direct call and a live agent turn ("track that I applied to...").
Never auto-applies -- it's a record, the user always submits.

**Gmail read access (`tools/email_tools.py`)** -- the credential dance,
done right. Refused his offer to just hand over the real Gmail password
(hard line: full-account compromise risk); walked him through Google's
own flow to a revocable App Password instead, driving the browser to the
right pages via screenshots when he got lost, and being explicit that he
types his Google password into GOOGLE's real page (safe), never to me.
Stored the App Password in .env (spaces stripped in config), IMAP-tested
it live -- confirmed it's tied to owntred399@gmail.com (his "299" was a
typo), 133 inbox messages. Tools: `check_email` (recent/unread/search,
uses BODY.PEEK so checking never marks mail read) and `read_email` (full
body of a matched message). Read-only on purpose -- no sending (that'd be
a separate confirmation-gated build). Verified: direct calls listed real
inbox + search + unread; a live agent turn ("check my email, any unread")
correctly called check_email and gave a natural summary. Prompt updated:
email moved from "not wired up" to a real capability, with "sending
email" now the named limit. Tool count now 48.

**Bonus already working from the earlier Phone Link pairing**: new Gmail
notifications on his phone already get spoken aloud by REYES via the
notification listener -- so basic "tell me when a job email lands" existed
before the IMAP tools; the IMAP tools add actually reading/searching the
inbox on demand.

## Job-email watcher + mic boost (2026-07-24)

**`email_watcher.py`** (new) -- background service (not an agent-turn
scheduled check, so zero model cost per poll) that checks Gmail every 5
min and speaks up ONLY for genuinely job-related mail. Targeted matching
(`_is_job_related`): subject hints (application/interview/shortlist/
vacancy/"we received your application"/etc.) + sender-domain hints (jobs/
recruit/nhs/trac/workday/greenhouse/lever/indeed/careers). Baselines
existing mail on first run so it never announces the backlog, tracks seen
Message-IDs (own table) so nothing repeats, respects quiet hours and the
heartbeat kill switch, and only starts if Gmail is configured. Verified:
against the real inbox it flagged 0 of the recent 25 (correct -- all
newsletters/alerts), and a 7-case logic test flagged all 4 real
job-reply patterns while skipping eBay/Microsoft-code/Claude-billing.

**Mic sensitivity (`set_mic_level` in utility.py)** -- user wanted REYES
to "hear from far and remove background noise". Honest split: the app
listens through Chromium's own speech engine, which already does noise
suppression + auto-gain and does NOT expose custom DSP to page code --
faking a JS noise filter there would be theater, so didn't. The real,
honest lever is the Windows mic INPUT level, controllable via pycaw's
microphone endpoint (`GetMicrophone().Activate(IAudioEndpointVolume)` --
the raw-IMMDevice Activate path; the wrapped-AudioDevice `.EndpointVolume`
used for speakers doesn't apply here). Added `set_mic_level(0-100)` and
boosted it from 77% to 100% now -- that genuinely helps it hear from
farther, and it affects the browser path too since it's OS-level. Told
the user plainly that deep noise-cancellation in the app is Chromium's to
do, not custom-tunable. Tool count now 49; all four background services
(heartbeat, notifications, activity, email-watcher) confirmed running
together after restart.

## News, in-panel maps, Fish Audio (2026-07-24)

Big grab-bag request. Delivered + tested the concrete pieces; triaged the
rest honestly rather than half-building everything.

- **`get_news`** (system.py) -- live headlines via Google News RSS (no
  key, free), top or topic-specific, read back INTO the conversation
  (unlike web_search which only opens a browser). Verified with real
  current headlines, top + "football". Prompt's old "no live news" caveat
  updated accordingly.
- **`show_map`** -- displays a map INSIDE the REYES panel, not a browser
  tab (user was explicit: "on reyes itself not on the site"). Uses
  Google's keyless `maps.google.com/maps?q=...&output=embed` in an iframe
  overlay added to index.html; the tool publishes a `show_map` event on
  the existing notification_bus SSE, the panel opens the overlay. Handles
  "from A to B" directions too. Verified END TO END: agent turn -> SSE
  event received by a probe with correct embed URL -> loaded the panel in
  the Browser pane, triggered "map of Paris", confirmed via DOM the
  overlay opened (class 'open', display flex, right title) and the iframe
  rendered at 1098x517 with a live cross-origin contentWindow. (Pixel
  screenshot blocked by the pane-compositing limitation, so verified via
  DOM/iframe state instead.)
- **Fish Audio TTS key** -- stored in .env (FISH_AUDIO_API_KEY). Tested
  the API live: key is VALID (authenticates) but the account has **zero
  API credit** (HTTP 402, "Insufficient API credit... add funds"). So it
  can't actually synthesize until the user tops up at
  fish.audio/app/developers -- which is a payment I won't make. Did NOT
  build the provider blind against an untestable endpoint; told the user
  the key's fine but needs credit, and that the browser already uses
  natural neural voices meanwhile.

**Honest status on the rest of the same request (not silently dropped):**
- Slack sending -- already exists (`send_slack_message`, desktop
  automation, confirmation-gated); pointed the user to it rather than
  rebuilding.
- Mic "x10" -- already at 100%, which is the OS endpoint maximum; there
  is no 10x beyond that at the endpoint level and the browser speech
  engine caps added gain. Said so plainly.
- Fullscreen, minimize-to-a-floating-edge-orb, webcam hand-gesture
  control, "3D redesign" -- each a real separate build (gesture control
  especially is a large MediaPipe CV project + always-on webcam privacy
  weight; minimize-to-orb needs a borderless always-on-top OS window).
  Deliberately NOT half-built in a turn already full of other work;
  flagged to the user to pick one to do properly next. Tool count 51.

## Fullscreen + a CRITICAL self-launch server-bug fix (2026-07-24)

User picked "fullscreen mode" as the next big feature. Building it
surfaced a much more important latent bug.

**Fullscreen** -- header button (F11 too). In the pywebview desktop app it
calls the NATIVE window fullscreen via a new `window.pywebview.api`
bridge (`_DesktopApi.toggle_fullscreen` -> `window.toggle_fullscreen()`),
which is the only way to truly fullscreen the OS window in WebView2
(the browser Fullscreen API only fills the webview area there); in a
plain browser it falls back to `requestFullscreen()`. Button + handler
confirmed present in the served page; Fullscreen API confirmed available.

**The real find -- the desktop app's server never actually served.**
`desktop_app.py` ran uvicorn in a background *daemon thread*. On Windows,
threaded uvicorn binds the port but its event loop doesn't process
requests -- so `/api/status` (and everything) hung: the socket accepts
the TCP connection, then nothing. The whole session's "desktop app
healthy" checks had actually been answered by PARALLEL
`python -m reyes_agent.web` test servers I'd been starting, masking it.
Meaning: when the USER launches via the shortcut with no such parallel
server, REYES would come up dead. Proved it cleanly: direct
`python -m reyes_agent.web` (uvicorn in the MAIN thread) responds
perfectly; the desktop app (threaded) binds but hangs, reproducibly.
Fix: `desktop_app.py` now launches the server as its OWN child process
(`sys.executable -m reyes_agent.web`, CREATE_NO_WINDOW, terminated on
window close / atexit) instead of a thread -- uvicorn runs in that
child's main thread, the proven path, still binding 0.0.0.0 for phone/
LAN. Verified END TO END via the user's ACTUAL launch path: killed all
instances, `Start-Process "Open REYES.bat"` (== double-click), waited,
`/api/status` healthy AND a real `/api/chat` turn worked. The noisy
WebView2 "can only be accessed from the UI thread" / recursion lines in
the pywebview log are pre-existing cosmetic introspection noise, not
fatal (window loads, server serves). This fix matters more than the
fullscreen feature it was found under -- it's the difference between the
user's self-launch working or not.

## Orb redesign v2 -- React-Bits-style plasma orb (2026-07-24)

User: "change that orb and background to something like this" + a React
Bits `<Orb hue hoverIntensity rotateOnHover>` snippet + its shadcn/OGL
install command, "go wild", "disarranges when talking", "shows emotions
when thinking".

The React Bits Orb is a React/OGL component -- can't `pnpm add` it into
REYES's vanilla-JS + three.js frontend. So `static/orb.js` was rewritten
from the old wireframe-icosahedron into a screen-space fragment-shader
orb in that STYLE: a glowing plasma sphere (fbm-distorted edge, inner
turbulence, fresnel rim, halo) on a three.js fullscreen quad, over a
deep-space vignette+twinkling-stars background baked into the same
shader. Mouse hover = parallax + rim lift (the rotateOnHover/
hoverIntensity feel). State-driven behavior matches the two explicit
asks: `processing` ("thinking") sets emotion>0 so the HUE DRIFTS like a
mood; `speaking` sets disarrange=1 so the surface SHATTERS with
high-frequency jitter. The full v1 public API (setState/pulse/
setPerformanceMode/dispatchAgent/setAgentWorking/getAgentScreenPositions/
specialists) was preserved exactly so index.html is untouched; the
retired sub-agent constellation's hooks are kept as ripple triggers.

Verified as far as the tooling allows, and honest about the ceiling:
loaded the panel, `read_console_messages` clean (a GLSL compile error
would log a THREE.WebGLProgram error -- none), canvas sizes correctly on
resize. Could NOT pixel-verify the animated visual: the Browser pane
isn't composited, so `requestAnimationFrame` is throttled to zero there
(proved: rafFired=false while setTimeout fired), which pauses the render
loop and leaves the WebGL buffer black -- an artifact of the hidden pane,
not the shader. It renders in a real displayed window (the desktop app).
Also fixed a real init race caught during this: if the canvas has 0 size
at module load (layout not settled), it rendered blank until a resize --
added a ResizeObserver so it always sizes once laid out. Relaunched via
the user's actual `Open REYES.bat` path; healthy + new orb.js confirmed
served.

**Honest triage of the rest of the same "do all, go wild" request:**
- Blender 3D generation -- Blender is NOT installed (checked). Won't
  install software silently. Told the user: once they install Blender, a
  real tool where REYES writes bpy scripts to generate/render models is
  buildable, but "almost anything" realistically means procedural/
  parametric geometry + simple animation, not arbitrary hero assets.
- Hand-gesture webcam control + minimize-to-floating-edge-orb -- still
  the big separate builds from before; deliberately not crammed in
  alongside the orb rewrite. Offered as the next focused pieces.

## Live activity feed -- "show what REYES is doing" (2026-07-31)

User: when REYES does something, show it happening in the panel instead
of making them open the Obsidian vault to check. Built a live activity
feed.

- `agent.py`: added an `on_tool_result` callback (alongside on_tool_call/
  on_text), fired right after each `run_tool`. `web.py` chat_stream now
  emits `{type:"tool_result", name, result}` (result capped 1200 chars)
  in addition to the existing `{type:"tool"}`.
- `web.py`: mounted `/captures` -> the vault captures dir, so generated
  images / screenshots can be shown INLINE in the feed, not just as a
  file path the user would have to go open.
- `static/index.html`: `friendlyTool(name,input)` maps every tool to a
  human line with an icon ("📝 Writing note 'X'", "🗺️ Showing a map of
  Paris", "📧 Checking your email", ...) so the chip reads like REYES
  narrating its work; `finishActivityChip` marks it ✓ done on the result
  and, for generate_image/screenshot/webcam, drops the actual image
  (`/captures/<file>`) into the transcript.
- Verified: import clean + `on_tool_result` in the signature; live
  `/api/chat/stream` for "what time is it" streamed BOTH
  `tool get_datetime` and `tool_result ... "Friday..."`; `/captures/<img>`
  returns HTTP 200 (300KB real image); panel reloads with zero console
  errors. Final rendered chips/inline-images only animate in a displayed
  window (same RAF/compositing caveat as the orb), but every wire is
  confirmed.

Still pending from the same message: minimize-to-a-small-corner-orb (the
JARVIS reference image) -- a real pywebview-resize + mini-CSS build,
approach to confirm with the user; and mic "x10" -- already at the OS
endpoint max (100%), no 10x beyond that in software.

## Minimize-to-orb (auto-shrink) + ad key art (2026-07-31)

**Minimize-to-orb** -- user picked "auto-shrink when working" (the JARVIS
corner-orb). Built so REYES shrinks ONLY when a turn actually uses a tool
(does real work), not on plain chat, then pops back with the answer.
`desktop_app.py::_DesktopApi.set_mini(on)` resizes the pywebview window to
210x210 in the bottom-right corner and sets on_top (float over apps),
restoring to 1600x1000 centered -- all best-effort/try-wrapped for
pywebview-build differences. `static/index.html`: `setMini()` toggles a
`body.mini` CSS collapse (hides all chrome, leaves just the orb, orb
becomes click-to-restore) AND calls the native resize when in the desktop
app; triggered on the first `tool` event of a turn, restored in the
turn's `finally`. Verified the CSS side directly (body.mini -> #ui
display none -> restored flex, orb cursor pointer, zero console errors);
native window resize is best-effort, not pixel-verifiable here.

**Ad key art** -- user's detailed "$100k cinematic REYES orb reactor"
brief. Was honest that generate_image is the free keyless Pollinations
engine, not an Unreal render farm -- then generated it at 1920x1080 from
a brief-derived prompt and it came out genuinely strong (glowing core
reactor, mechanical rings, futuristic architecture, volumetric fog, blue
+ orange grade). Composition came out centered rather than the requested
orb-right/text-left negative space (Pollinations ignores precise
composition) -- flagged that and that variations can be regenerated.
Delivered to the user. This also happens to be a live demo of the new
activity-feed inline-image path (generate_image -> shows the picture).

## Ad variation + hand-gesture control (2026-07-31)

**Ad variation** -- regenerated with the orb pushed to the RIGHT and dark
negative space on the LEFT for ad text (the composition the first one
missed). This one landed the layout well; delivered.

**Hand-gesture control (webcam)** -- the last big feature. Built with an
honest, verifiable/unverifiable split clearly disclosed to the user.
- Server (VERIFIED): `POST /api/gesture` in web.py maps a gesture name to
  an instant local action via run_tool, NO LLM call. Map: Open_Palm ->
  play/pause, Closed_Fist -> mute, Thumb_Up -> vol up, Thumb_Down -> vol
  down, Victory -> next. Tested live: Thumb_Up returned
  media_control:volume_up and actually fired the key; unmapped gesture
  returns a clean {ok:false}.
- Browser (NOT verifiable here -- no webcam / no video loop in the build
  env, said so plainly to the user): `static/gesture.js` loads MediaPipe
  Tasks Vision GestureRecognizer (CDN, on demand), runs the webcam,
  recognizes gestures (score>0.6, debounced 0.8s global / 1.6s repeat),
  and POSTs to /api/gesture. Loaded LAZILY via a Settings toggle that's
  OFF by default (always-on webcam = privacy), and dynamically imported
  so a load failure can't touch the rest of the app (try/catch resets the
  toggle + shows the error in the sub-label). Verified what's verifiable:
  page loads with the toggle present (correct gesture-map label), zero
  console errors, gesture.js served HTTP 200, endpoint works. The actual
  webcam recognition needs the user's real-world test -- did NOT claim it
  works, told them they're the one who has to confirm it.

Feature list from the whole "do all / go wild" arc now stands: orb v2,
fullscreen, activity feed w/ inline images, minimize-to-orb auto-shrink,
in-panel maps, news, Gmail + job watcher, mic maxed, ad art, and
gesture control (server-verified, browser pending user test). Remaining
honestly-blocked: Fish Audio (needs the user to add API credit), Blender
(not installed).

## Hand mouse control + any-camera + ad variation (2026-07-31)

User: mouse control via hand gestures, connect to any camera, "test
REYES". (Said they sent a picture of the orb they want -- none arrived;
told them plainly and asked to resend.)

**Mouse control (VERIFIED server-side)** -- `POST /api/mouse` in web.py:
normalized (x,y)+click -> `pyautogui.moveTo`/`click`, FAILSAFE off (the
toggle is the off-switch). Tested live: `{x:0.5,y:0.5}` physically moved
the cursor to (960,540), screen center. `gesture.js` rewritten to use the
GestureRecognizer's 21 landmarks: index fingertip (mirrored + gain 1.5 +
0.45 smoothing) drives the cursor at ~30fps, pinch (thumb-index dist
<0.05, rising edge) = click.

**Any camera** -- `listCameras()` (enumerateDevices videoinputs) +
`setCameraDevice(id)` hot-swaps the stream; a Camera dropdown in Settings
populates after first permission grant.

**Two independent Settings toggles now** -- "Hand gestures" (media
actions) and "Mouse control (hand)" -- sharing one camera+recognizer via
enable/ensureRunning/stopIfIdle; both OFF by default (privacy), lazily
imported so a failure can't touch the app.

**"Test REYES"** -- ran the tests I actually can: mouse endpoint moved
the real cursor; a live `/api/chat` turn replied ("Loud and clear...");
`gesture.js` served 200; the module imports with all four new exports
present; every Settings toggle + the camera picker render; zero console
errors. Still cannot test the MediaPipe webcam hand-tracking itself (no
camera in the build env) -- said so, it needs the user's real test.

**Ad variation** -- regenerated orb-on-the-right / left-negative-space
composition (the layout the first missed); delivered.

## Orb perf fix -- "laggy, not responding" (2026-07-31)

User reported the settings UI (and everything) laggy/unresponsive. Root
cause: orb v2's fullscreen fragment shader was too GPU-heavy -- ~2x pixel
ratio on a 1080p+ screen (4x the pixels) x 5-octave 3D-simplex fbm called
3x per pixel (~15 snoise/pixel) saturated the GPU and starved the whole
UI thread/compositor. Fixed by cutting the cost ~6-8x: pixelCap 2 -> 1
(verified: canvas backing ratio now 1.0), fbm octaves 3/2 (was 5/3),
and the edge+jitter switched from fbm to a single snoise (plasma still
fbm). Performance mode now goes even lighter (0.75x + 2 octaves) for weak
GPUs. Also gave the gesture/mouse Settings toggles an immediate "starting
camera…" status so the MediaPipe CDN load never makes them feel frozen.
Verified the lighter shader compiles clean (no console errors) and the
1x cap is live; the actual felt-responsiveness is the user's to confirm
in their displayed window (RAF is throttled in the headless pane so FPS
can't be measured here).

## The REAL lag cause: stale cache + orb off-switch + Blender (2026-07-31)

User still lagging after the shader trim. Root cause turned out to be
**caching**, not the shader: the served orb.js/index.html were correct
(grep-confirmed), but WebView2 was serving a STALE cached orb.js across
restarts -- so none of the perf fixes ever reached the window; the user
was running the original heavy orb the whole time. Proof: a fresh
(uncached) Browser-pane load showed canvasDisplay 'none' correctly, while
the cached load showed 'block'.
Fixes:
- **`_no_cache` middleware in web.py** sets `Cache-Control: no-store` on
  every response + `?v=3` on the orb.js import. This is the important one
  -- it's why UI changes weren't landing. Verified the header is present
  on both / and /static/orb.js.
- **Animated-orb OFF switch** (the user asked to be able to turn it off):
  `orb.setActive(on)` actually STOPS the RAF render loop (not just hides
  the canvas) -> zero GPU. New Settings toggle "Animated orb", default
  OFF, remembered in localStorage. Off -> a static AI-generated reactor
  image (`static/reyes-bg.jpg`, #static-bg behind the canvas) shows with
  no live rendering. Verified on a fresh load: toggle off, canvas
  display:none, static bg block.
- Generated 2 new orb ad backgrounds from the user's refined "PECK TO THE
  CORE" prompt (text left out -- image gen garbles text); the sharper
  hangar-reactor one is the app background, both delivered.

**Blender (installed now -- Blender 5.2)**: `tools/blender.py::
create_3d_model(bpy_code, name)` -- wraps REYES-written geometry code in a
scene scaffold (clean scene, auto camera, sun light, render settings),
runs `blender --background --python` headless, saves a PNG render + an
editable .blend to vault/07-System/3d/. Gated (requires_confirmation --
runs generated Python, run_command tier). VERIFIED for real: rendered a
torus ringed by 8 spheres, correct lighting/shading, PNG produced +
delivered to the user. Honest scope told to the user: great for
procedural/parametric models, not photoreal hero assets. Tool count 52.

**Still to address (user's mid-turn msg)**: "site + pay automation +
signup + forgot-password + billing" -- REYES can already GENERATE all
that code via write_project_file (signup/login/reset pages, Stripe
checkout boilerplate); the hard line is it won't autonomously enter real
payment details, create real accounts, or handle real passwords/live
charges (needs the user's own Stripe acct + deploy). To be clarified with
the user, not silently built as autonomous payment handling.

## Blank-screen fix + discreet notifications + honest declines (2026-07-31)

**Blank screen fixed**: `#static-bg` had `z-index:-1`, which put it BEHIND
the page's own dark background -> invisible -> with the orb also off,
totally blank. Set it to `z-index:0` (canvas 0 too but later in DOM so it
paints over when the orb is on; `#ui` is z-index:1 above both). Verified
in a fresh load: bg z-index 0, settings button opens the panel, the orb
toggle flips the canvas on/off. The "settings not toggling" was the user
on the stale/blank cached page -- the handlers test fine.

**Discreet notifications** (user: "just tell me boss there is a message,
not who/what"): `notification_listener` now speaks only "Boss, you have a
new message. What's your reply, sir?" -- no sender, no content read aloud
(privacy). Full text still in the panel notice + history for the reply
flow.

**Emotion + translation**: added to SYSTEM_PROMPT -- read the feeling
under the words and meet it without announcing it; translate on the spot
either direction; be perceptive about fumbled intent. (Language fluency
was already there.)

**Declined honestly (told the user why, offered legit paths):**
- Skiper UI / Vengeance UI / "animmasterlib" components "I don't have an
  account there but get the crazy components" -- those are PAID/licensed
  React kits; pulling them without a license is piracy. Won't. Offered to
  build equivalent high-quality animated components myself or use
  free/open-source ones.
- `npm i framer-motion` (+ the React kits above) -- REYES's frontend is a
  single vanilla HTML file + three.js, NOT a React/npm project, so those
  React-only libraries can't be installed into it without rebuilding the
  whole UI as a React app w/ a build pipeline. Offered native animations
  instead.
- "locate anything model install" -- too vague / won't install arbitrary
  models blindly; asked what it should actually DO.

## Renamed REYES -> ZENO + architecture north-star (2026-07-31)

**Rename**: all USER-FACING "REYES"/"Reyes" -> "ZENO"/"Zeno".
`config.ASSISTANT_NAME` default REYES->ZENO (cascades to window title,
FastAPI title, system prompt "You are ZENO", spoken name); `WAKE_PHRASES`
default -> "wake up zeno,zeno,hey zeno,bro"; `static/index.html` title,
`<h1>`, placeholders, error text, and the browser WAKE_WORDS array all
ZENO-ified (13 strings). Verified live: `/api/status` name=ZENO, and
"what is your name?" -> "Zeno." DELIBERATELY NOT renamed (invisible to the
user, and renaming would break every import / the launcher / the vault
path for zero benefit): the Python package `reyes_agent`, file paths, the
`REYES/` vault folder, `reyes-bg.jpg`, and code comments. Can't rename
from here: the Telegram bot `@Reyes3_boss_bot` (that's set on Telegram's
side via BotFather -- the user would do it).

**Architecture spec**: the user's huge HF-Transformers-scale "master build
prompt" saved as `ZENO_ARCHITECTURE.md` -- as a NORTH STAR, not a
one-shot build. Led the doc with an honest current-state table: ZENO
already embodies the core philosophy (unified model seam/provider.py,
agent loop, tool system, confirmation gate, memory, multimodal vision,
audio, streaming SSE UI, orb, audit log, LAN serving) but is NOT an ML
training/serving framework -- training, PEFT, quantization, big-model
sharding, RAG/embeddings, HF-Hub/vLLM/TGI integration, ONNX export are
❌ not built and are each a large GPU-dependent undertaking. Named the
sensible next increments (embeddings+vector store->RAG, document engine,
a task/latency model router on the existing seam, local offline serving).
Did not pretend the framework parts exist.

## Second Brain spec (2026-07-31)

User handed a large "ZENO Second Brain v2" cognitive-architecture spec
(reasoning loop, serious mode, advanced listening engine, memory
architecture, self-critique, grounding/anti-hallucination, autonomy with
control, model routing, internal state). Honest triage rather than
building a parallel fake "cognitive engine":

**What's prompt-level and genuinely added to SYSTEM_PROMPT** (Claude
already reasons this way natively -- these are the concrete, testable
behavioral rules, not a separate engine bolted on): a "Second brain"
section (think through real intent before acting, verify effect not just
non-error, distinguish observed/inferred/assumed); **Serious Mode**
(explicit trigger phrases + auto-trigger on high-stakes tasks, drops
jokes/filler, precise, verifies harder); a self-critique check before
consequential actions; "Autonomy with control" explicitly tied to the
ALREADY-EXISTING Tier-6 confirmation gate (not a new mechanism -- naming
why it exists); tool-honesty ("never claim a tool ran if it didn't").
VERIFIED LIVE, not just written: same question asked normal ("what's up"
-> "Not much. Systems are up... what are we getting into?") vs. explicit
"serious mode" on a real decision (quit a part-time job) -> a structured,
jokes-free 4-point breakdown with real follow-up questions. Visibly
different behavior, confirmed via actual API calls.

**What needed real code, not just prompt text**: the Advanced Listening
Engine's core claim -- long-form capture through pauses + correction/
interruption handling -- because the existing voice pipeline fired on
every finalized speech chunk immediately, which would execute "open
Telegram and send" before ever hearing "actually, don't." Built in
`static/index.html`:
- `noteSpeechFragment()` buffers finalized fragments and DEBOUNCES on a
  1.1s settle window before dispatching -- fragments arriving faster than
  that merge into one combined thought instead of firing separately.
- `resolveCorrections()` finds the LAST self-correction marker
  ("actually", "no wait", "scratch that", "i mean") and trims to what
  comes after it, so a correction supersedes what it's correcting rather
  than both being sent.
- Added a prompt line telling the underlying model it may receive a
  self-corrected run-on transcript and should resolve to the final
  landed-on intent -- the client-side trim is a first-pass simplification
  (works cleanly for single corrections), the model handles the messier
  multi-correction cases with full context, which is the more robust
  split of responsibility than trying to hand-regex perfect NLU.
VERIFIED for real (module-scoped, so replicated the exact algorithm in
the live served page rather than guessing): the safety-critical case
"open telegram and send actually no don't send anything yet" resolved to
"no don't send anything yet" -- correctly drops the premature send
instruction. Simulated three fragments 300ms apart (well inside the
settle window): dispatched exactly ONCE (not three times), combining all
three, firing at ~1.7s = last-fragment-time + the 1.1s settle window --
proving the debounce/merge timing is real, not just written.

**Honest scope note, stated to the user directly:** most of the spec
(sections 1-19: deep reasoning, planning, decision engine, proactive
intelligence, formal internal-state enum L1/L2/L3, the full agentic
OBSERVE->VERIFY->REMEMBER loop as literal tracked state) describes how a
capable LLM already reasons -- Claude does this natively via its own
chain of thought. Encoding it as *explicit rules* (done above) sharpens
and makes consistent what the model already tends to do; it is not the
same as bolting on a separate formal cognitive-state machine, and no
such machine was built or claimed. Model routing (section 14) already
exists at the provider level (Anthropic/Gemini/xAI/Ollama), not yet as
an automatic per-task router -- same "next increment" already named in
ZENO_ARCHITECTURE.md.

## RAG: real semantic search over the vault (2026-07-31)

Picked up the highest-value "next increment" named in
ZENO_ARCHITECTURE.md's honest gap table: embeddings + a vector store.
Built dependency-light on purpose -- no vector DB service, no ML
framework, matching this project's whole philosophy.

- **Embedding endpoint found by testing, not assumed**: tried
  `text-embedding-004` first (the common default) -- 404, not available
  to this key. Listed the account's actual models via `ListModels` and
  found `gemini-embedding-001` IS available; confirmed it returns real
  3072-dim vectors with a live call before building anything on it.
- **`tools/rag.py`** (new): `_chunk_text` (180-word chunks, 40-word
  overlap), `_embed` (Gemini's embedContent, same "always Gemini
  regardless of MODEL_PROVIDER" rule as vision.py), storage as one
  `.npz` + a `meta.json` in `07-System/rag/` (no separate DB process --
  fine at personal-vault scale, an honest future upgrade past that, not
  pretended to exist now), cosine similarity via plain numpy for
  retrieval. `reindex_vault` (incremental -- tracks each file's mtime,
  only re-embeds changed/new files) and `search_vault_semantic` (finds
  vault content by MEANING, not keyword match).
- **Real bug caught by actually running it, not assumed away**: first
  `reindex_vault` run found 0 files. Checked the real vault structure and
  found most of the user's actual notes live loose in the vault ROOT
  (Obsidian's default), not inside the organized subfolders the scanner
  was checking -- fixed `_iter_vault_files` to scan the root too.
- **Verified for real, three ways**: (1) indexed the actual vault -- 6
  files, 7 chunks, real embedding calls. (2) True semantic test: searched
  "ways to earn income as a student" -- a phrase that appears NOWHERE in
  the vault verbatim -- and it correctly surfaced "Freelance Storefront.md"
  as the top match purely by meaning. (3) Live agent turn: asked "do I
  have anything in my vault about making money on the side" through
  `/api/chat` -- the model chose `search_vault_semantic` on its own (no
  hint given) and gave an accurate, natural summary of the right note.
  Noted one harmless edge case: empty vault files (no chunks produced)
  get re-scanned every reindex since they never enter the mtime-tracked
  meta -- costs a stat() call, zero embedding calls, not worth fixing.
  Tool count now 54.

## Real ElevenLabs voice, wired to where it's actually heard (2026-07-31)

User gave a specific ElevenLabs voice (SSfU0eLfP3qeuR4j2bwD) to use. Found
and fixed a real architecture gap in the process, not just flipped a
config flag.

**Tested before touching anything**: an ElevenLabs key already existed in
.env from earlier in the build, documented as blocked (402 payment_required
on 2026-07-22, free tier). Retested the actual REST call with the new
voice ID first -- 200 OK, real 50KB MP3 (verified via ID3 header, not
just status code), sent to the user to preview before wiring it in. The
account has since gained real API access; updated the stale comment in
`voice/tts.py` that still said "unavailable."

**The real gap, found before it would have silently failed the user**:
`.env`'s `TTS_PROVIDER=elevenlabs` only ever affected the standalone CLI
voice paths (`voice_cli.py`/`wake_cli.py`). The actual web/desktop panel
-- what the user actually uses essentially 100% of this session -- speaks
via the BROWSER's own built-in voice (`speakInBrowser` ->
`SpeechSynthesisUtterance`), a completely separate code path that never
touches `voice/tts.py` at all. Flipping the env var alone would have
changed nothing the user could hear.

**Fixed properly, respecting an existing constraint**: server-side
`tts.speak()` plays on whichever machine the Python process is running
on -- fine for the CLI, wrong for the panel, because the panel can be
open on a phone over LAN (the earlier "why browser TTS not server TTS"
design decision) -- playing server-side would come out of the PC's
speakers even when the user is looking at their phone. Built the correct
general fix instead of the shortcut:
- `voice/tts.py::synthesize_bytes()` -- new function returning raw MP3
  bytes (ElevenLabs' non-streaming `.convert()`) instead of playing
  locally.
- `web.py::POST /api/tts` -- new endpoint serving those bytes over HTTP,
  so audio reaches whichever device actually has the panel open.
- `static/index.html::speakInBrowser` -- rewritten to fetch `/api/tts`
  and play via a real `<audio>` element FIRST; falls back to the
  existing browser-voice path (`speakWithBrowserVoice`, extracted from
  the old function body) on any network hiccup or a 503 (not
  configured) -- REYES never goes silent over a TTS failure, and a
  `serverTtsAvailable` flag stops it retrying the network every single
  turn once it's confirmed unconfigured.

**Verified for real, at every layer, not assumed from a status code**:
(1) `synthesize_bytes()` called directly -- real MP3 bytes, ID3-verified.
(2) `/api/tts` via curl -- 200, 36KB audio. (3) `/api/tts` fetched from
INSIDE the live browser page -- confirmed `audio/mpeg` content-type and a
real Blob. (4) The header's own status line already read "gemini · voice:
elevenlabs" on load -- config cascaded correctly. (5) The full real
path: typed an actual message into the actual UI, clicked the actual
Send button (module-scoped `speakInBrowser` can't be called directly
from outside, so drove it through genuine user interaction instead),
then confirmed via `read_network_requests` that a real `POST /api/tts`
fired and returned 200 -- proof the production flow, not just the
isolated pieces, works. Zero console errors throughout.

**Also fixed**: a leftover wake-word hint string still said `"Zeno" /
"Bro" / "Yo"` after the REYES->ZENO rename, but "Yo" isn't in the actual
WAKE_PHRASES list anymore and "wake up zeno" wasn't mentioned -- corrected
to match the real list.

## HUD redesign + a real batch of "alive" behaviors (2026-07-31)

User: "i swear dont like that gui remove the whole thing" + a massive
multi-document "living AI presence" spec (emotional orb states, mini-orb
mode, universal language, intelligent wake word, proactive intelligence,
a full "AI Operating System" architecture). Then "do everything please"
and "remove any lagging properties" mid-turn. Triaged hard and honestly:
built everything genuinely buildable in this pass, declined the pieces
that are separate large projects (named explicitly at the end, not
silently skipped).

**GUI overhaul -- the literal, urgent complaint, done for real, not
cosmetic.** Removed the chat-bubble "Conversation" panel entirely (no
boxed heading, no user/assistant message bubbles, no scrolling
messaging-app-style log). Replaced with a HUD: `#caption-text` -- a
single large centered line showing what's being said RIGHT NOW (fades in
per line, auto-fades after 9s, grows live as a reply streams in -- not a
persistent transcript) and `#activity-ticker` -- floating pills near the
orb for current work, each fading out ~3.5s after completing instead of
stacking into a list. `#transcript`/`.msg` kept in the DOM but
`display:none` -- pure bookkeeping so the existing streaming-text-
accumulation logic didn't need a rewrite, zero regression risk on the
proven activity-feed/tool-result pipeline from earlier. VERIFIED live: no
"Conversation" heading, zero visible chat bubbles, a real UI-driven turn
(typed + Send, not a raw API call) correctly grew the caption text live
and matched the model's actual final reply; zero console errors.

**Orb now has real, distinct visual identities per activity, not one
generic spinner.** Added `searching`/`coding`/`creating`/
`communicating`/`learning`/`reasoning` to `orb.js`'s STATES (each a
genuinely different hue/motion, not an alias of `processing`), and
`orbStateForTool()` in index.html maps every real tool to the right
category (web_search/get_news -> searching, write_project_file/
run_command -> coding, generate_image/write_note -> creating,
send_slack_message/media_control -> communicating, remember/reindex_vault
-> learning, delegate -> reasoning) so the orb visibly communicates WHAT
kind of work is happening.

**Settings persistence -- "without the settings they are already
active".** Gesture/mouse-control toggles previously reset to OFF every
restart (no localStorage wiring), meaning the user had to re-enable
webcam features every single launch. Added persistence + an auto-restore
on load (camera device included) so once turned on, they STAY on across
restarts -- directly answering the mid-turn correction.

**Wake-word "addressing vs. mentioning" heuristic** (from the spec's own
"Zeno, open Chrome" -> wake vs. "my assistant Zeno is fast" -> don't
wake example). Checks the last two words before the name for a
possessive/article ("my", "the", "our"...) -- catches both "my Zeno" and
"my assistant Zeno" (a noun between the possessive and the name).
VERIFIED, including a real bug caught and fixed mid-build: the first
version only checked ONE preceding word and incorrectly woke on "my
assistant Zeno is very fast" (the noun "assistant" sat between "my" and
the name); widened to a 2-word lookback, re-tested, fixed. Honestly
documented remaining gap: a determiner-free mention like "I think Zeno
can help" can't be caught by a word-lookback regex (needs real intent
classification) -- noted in the code and here, not silently claimed as
solved. Low real risk either way since a false wake there just produces
an odd-but-harmless reply, not a consequential action (Tier 6 gate is the
actual safety net for anything that matters).

**Proactive nudges + Dream Mode (`proactive.py`, new background
service)** -- reuses activity_monitor's real sample data and idle
detection, and heartbeat's notice/quiet-hours/speak plumbing, rather than
building a parallel system:
- Long-session nudge: scans the last 2h of activity_log samples: if
  they're all the SAME app with zero idle samples, nudges once (2h
  cooldown before repeating), e.g. "You've been in Chrome for a couple
  hours straight."
- Low-battery nudge: `psutil.sensors_battery()`, fires once per
  below-20%-and-unplugged episode, resets when charging/recovered --
  verified live against this machine's REAL battery (79%, unplugged) via
  a direct call, correctly a no-op above threshold.
- Dream Mode: after 10 real idle minutes (GetLastInputInfo, same idle
  detector activity_monitor already uses), runs `reindex_vault()` once
  per 3h cooldown -- reuses the already-verified RAG indexer rather than
  building separate "maintenance" logic.

**Language + workspace-awareness prompt additions**: named Nigerian
Pidgin/Yoruba/Igbo/Hausa explicitly (personally relevant, verified live:
"Abeg Zeno wetin dey happen" got a natural Pidgin reply back); added
workspace-awareness pointing at the already-built `current_activity` tool
so ZENO tailors help to whatever app is actually in the foreground when
relevant, without over-checking it for unrelated requests.

**Explicitly declined, told to the user plainly, not faked:**
- Avatar/facial-expression mode ("if avatar mode is enabled") -- would
  need a rigged 3D face + blendshape animation + lip-sync, a genuinely
  separate large project, not attempted.
- Desktop-level compositing animations (folder icons orbiting the orb
  before flying to a real location on the Windows desktop, file-move
  trails, app icons flying into the orb before launch) -- needs a whole
  transparent always-on-top compositing layer OUTSIDE the browser
  tracking real file-system/window events; the activity ticker + spoken
  narration is the honest existing substitute, not attempted as literal
  desktop overlays.
- A dozen literal separate "specialist module" objects (Planner/Security
  Analyst/Business Analyst/Marketing Strategist/Career Assistant as
  distinct persistent components) -- the REAL equivalent already exists
  (`tools/subagents.py`'s researcher/coder/writer/analyst via `delegate`)
  and wasn't reinvented with more fake-named modules that wouldn't add
  functionality beyond what the graduate-level-knowledge prompt already
  covers.
- A full CRM/invoicing/SEO-tooling business suite -- mostly already
  covered by existing knowledge + track_work; didn't build dedicated
  software for each named business function.
- News Mode's literal "orb expands into a floating information display" --
  get_news already returns real headlines into the conversation/caption;
  a dedicated expanding visual dashboard mode was not built this pass.

## Console window + devtools + background, and a REAL launch bug found (2026-07-31)

User, repeated across several messages: hates seeing a cmd/console window
and the devtools option when opening ZENO; separately, still doesn't like
"the gui... the whole thing with the background" even after the HUD
rebuild -- read as specifically the generated reactor PHOTO, not the HUD
mechanics just verified working.

**Devtools**: `desktop_app.py`'s `webview.start(debug=True)` -> `False`.
Removes the right-click Inspect option entirely, as asked.

**Background**: rather than guess at a THIRD specific image after two
misses, replaced the forced photo with a clean minimal look that can't
carry that risk -- pure CSS radial vignette + a faint masked grid, zero
image load, zero extra GPU cost. `.bg-photo` class kept so the generated
reactor image can be opted back in later if ever wanted, but it is no
longer the default. Verified live: computed background-image is the
gradient, not reyes-bg.jpg.

**Console window -- found and fixed a REAL launch bug, not just a
preference tweak.** Switched `Open REYES.bat` to `pythonw.exe` (windowless
Python) instead of `python.exe`. Doing this alone would have LOOKED like
progress but silently left the app broken: `desktop_app.py::_start_server`
spawns its own child process for the FastAPI server via bare
`subprocess.Popen(...)` with no explicit stdout/stderr -- fine when the
PARENT has a real console to inherit from, but under pythonw.exe (by
design, NO console at all) there is nothing valid to inherit, and the
child died on startup with zero output anywhere. Proved this exact
failure mode directly: `reyes_agent.web` run STANDALONE under pythonw
with real redirected handles worked fine and bound the port; the same
module spawned as an unredirected child of a console-less pythonw parent
never bound the port, silently. Root-caused, then fixed at both levels:
- `_start_server()` now opens `zeno_server.log` and passes it explicitly
  as the child's `stdout=`/`stderr=` -- always valid handles regardless
  of the parent's console state.
- `_redirect_stdio_if_console_free()` (new, called first thing in
  `main()`) redirects the TOP-level process's own `sys.stdout`/`stderr`
  to `zeno_desktop_app.log` when they're `None` (console-free) --
  otherwise a stray `print()` mid-failure would itself crash the app with
  nothing to explain why, which is worse than the original problem.
Also abandoned a first attempt at a VBS silent-launch wrapper after it
proved unreliable (WScript.Shell.Run's nested-quote string-building for a
`cmd /c "..." > log 2>&1` command didn't reliably spawn anything, and
debugging fragile VBS string escaping wasn't worth the time) in favor of
the simpler, standard, more testable pattern: point the Desktop shortcut
directly at `pythonw.exe` with args `-m reyes_agent.desktop_app` --
Explorer launches a GUI-subsystem exe with zero console by definition,
no wrapper process needed at all. Replaced the old `REYES.lnk` with
`ZENO.lnk` pointing at this.

**Verified for real, layer by layer, not assumed from "it should work
now":** (1) standalone `reyes_agent.web` under pythonw with real handles
-- bound the port, proved the module itself was fine. (2) Direct
`pythonw.exe -m reyes_agent.desktop_app`, no wrapper -- healthy
`/api/status`, a real window process titled exactly "ZENO" with no
console/cmd/conhost attached to it, `zeno_server.log` populated with
real output (proving the child-handle fix), a live `/api/chat` turn
replied correctly ("Running clean, no console."). (3) The ACTUAL final
Desktop shortcut, double-click-equivalent via `Start-Process` on the real
`.lnk` file -- healthy again, same clean result. Cleaned up the failed
VBS file and stray test logs after.

## Elite AI Team -- named specialist roster (2026-07-31)

User's next mega-spec was almost entirely things already built and
verified in the two prior turns (HUD/GUI, wake-word context-awareness,
language, orb states, Dream Mode, proactive nudges, Second Brain/RAG,
mini-orb, Serious Mode) -- said so plainly instead of re-explaining or
re-building. The one genuinely new, concrete piece: the "ZENO Elite AI
Team" named roster (ARIS/TOSIN/STARK/ZEAL/TITAN/APEX/NOVA/HERMES/ORACLE/
ATLAS/ULTRON/KATE). This maps directly onto the delegate/sub-agent system
already built (`tools/subagents.py`) -- expanded from 4 generic
specialists to these 12 named ones, each mapped to REAL existing tools
only, no invented capability. Two honesty rules applied to every one:
(1) no tool = no claim -- e.g. STARK's prompt explicitly says it has no
scanning/exploitation tooling and never will, rather than pretending
"security specialist" means offensive capability; APEX explicitly has no
FPS-tuning tool and won't automate input into a live game (anti-cheat
ban risk, same standing decline as earlier in this build). (2) same
standing boundaries apply inside every specialist -- TITAN's business
role explicitly still can't spend money without approval, HERMES's
comms role still routes through the Tier 6 confirmation gate. ATLAS
(per the user's own spec: "never communicates directly with the user")
kept as an ordinary one-level specialist rather than a second
coordination tier -- this build's standing rule is no recursive/
multi-level agents; its prompt just asks for terse coordination-style
output instead of chat. Named `hermes_comm` internally (not `hermes`) to
avoid confusion with the actual Hermes Agent MCP bridge available in this
environment -- an unrelated tool with a similar name; its own prompt
notes this. Updated `delegate`'s tool description/enum and
`orb.js`'s `SPECIALIST_IDS` to match (the orb's dispatch/pulse animation
was already generic and name-independent, confirmed by reading its
implementation, so no behavior change needed there beyond the label
list). Verified live: delegating to KATE for a real calculus question
produced a genuine, correct explanation; a security-check request was
correctly handled by the main agent directly rather than forced through
STARK, matching the "most requests don't need delegation" rule already
in place -- proof the system still exercises good judgment, not proof
of a bug.

## Gap-analysis-first pass: parallel delegation, Task Execution Engine, workspace overlays, Phone Companion (2026-08-03)

User instruction: stop adding to the architecture wholesale, inspect what
already exists, produce a gap analysis, implement only what's actually
missing, reuse existing modules. Real gaps found and closed:

**Parallel delegation.** `agent.py::run_agent()`'s tool loop ran every
tool call sequentially, `delegate()` included -- no concurrency existed.
Now: when a model round contains 2+ `delegate` calls, they run
concurrently via `concurrent.futures.ThreadPoolExecutor`; everything else
(single delegate calls, non-delegate tools) stays exactly sequential, so
existing behavior is unchanged outside the one case this targets. Safe
because every tool already opens its own short-lived SQLite connection
per call (no shared mutable state across threads) and `delegate()`'s own
sub-agent loop never gains the `delegate` tool itself -- the standing
no-recursive-delegation rule in `subagents.py` is untouched. Verified two
ways: a deterministic unit-style test (two mocked 1s delegate calls
completed in ~1s, not ~2s, with results correctly correlated back to
their own tool_call id) and a live KATE delegation over the real API.
Also updated `delegate`'s own tool description to tell the model this
capability exists -- without that, nothing would prompt it to ever issue
two delegate calls in one round.

**The chip-tracking bug this exposed.** `index.html`'s SSE handler
tracked the in-flight tool chip in one `lastChip` variable and dispatched
agent in one `dispatchedAgent` variable -- harmless while delegation was
strictly sequential, but would silently lose/misattribute chips the
moment two specialists ran at once. Fixed by keying chips in a `Map` by
tool_call id (threaded through `on_tool_call`/`on_tool_result` as a new
third argument, updated at every call site: web.py x4, slack_bridge.py,
telegram_bridge.py, voice_cli.py, cli.py) and tracking dispatched agents
in a `Set`.

**A second, unrelated real bug found while fixing the above:**
`runTurn()`'s `sawText`/`fullReply`/chip-tracking variables were declared
with `let`/`const` *inside* the `try` block and referenced from `finally`
-- confirmed via a real Node repro that this throws `ReferenceError` in
JS (try/catch/finally are separate block scopes), which would have
silently wedged the composer (`turnActive` never reset) on ANY error path
once the parallel-delegation changes made that code path reachable more
often. Fixed by hoisting the declarations above `try`.

**Task Execution Engine.** Made the existing implicit pipeline explicit
via an `on_stage` callback firing at existing checkpoints in the SAME
tool loop -- "planning" each model round, "delegating"/"acting" when
tools run, "verifying" when results are fed back, "responding" on the
final answer -- zero added model calls, zero added latency. Deliberately
did NOT split intent-analysis/planning into separate round-trip LLM
calls: one completion already does both in a single reasoning pass, and
adding more sequential provider calls would only make the
already-fought-hard-to-fix latency worse for no real quality gain.
Streamed to the browser as a new `stage` SSE event; `index.html` shows it
as a small fading label near the caption.

**Coding + news workspace overlays.** Both genuinely didn't exist.
Reused the exact `notification_bus.publish() -> /api/notification-events
SSE -> panel` pattern `show_map` already established: `write_project_file`
(projects.py) now publishes a `workspace_code` event (project, file,
content, file list) that opens a real file-tree + code-preview overlay;
`get_news` (system.py) now publishes `workspace_news` with real headline/
link/source data that opens a clickable-headlines overlay. No fake
build/test/deploy status shown in the coding overlay -- those tools don't
exist, and a progress bar for work that isn't happening would be exactly
the placeholder-implementation the user said to avoid. Both verified live
via real chat turns (write_project_file actually wrote a file and the
overlay showed its real content; get_news returned real current headlines
and the overlay rendered them).

**Phone Companion**, scoped honestly rather than attempted as a native
app: a new `/phone` page on the SAME FastAPI server, reusing
`/api/chat/stream`, `/api/tts`, `/api/notification-events`, and
`/api/pending` completely as-is (they already worked from any LAN
device). Conversation sync is free -- phone and desktop already share the
same `_history`. What's genuinely new: `config.PHONE_PAIR_TOKEN`
(auto-generated once, persisted to `.env`), a pairing gate on `/phone`
(`POST /api/phone/verify`), and file transfer (`GET /api/phone/files`,
`GET /api/phone/download`, `POST /api/phone/upload`, all token-gated,
landing in/reading from the vault's own `00-Inbox` and `02-Projects` so
transferred files show up for search/RAG like anything else). Desktop
Settings panel now shows the LAN URL + pairing code
(`GET /api/phone/pair-info`) so there's an actual way to pair a phone.
Stated plainly rather than oversold: the underlying `/api/*` endpoints
have no auth of their own on desktop either (always been "reachable means
on your own Wi-Fi"), so this token gates the phone's front door and file
transfer specifically, not a new LAN-wide auth system. Verified live end
to end through the real UI: pairing gate accepted the real token, files
tab listed real vault projects, approvals tab correctly showed the real
empty-pending state.

**Also fixed while restarting to verify:** the desktop background was
`#05060a` (reads as near-black) despite an earlier request for a dark
BLUE background with the orb in the middle -- changed to a real navy
(`#050b1e` base, richer blue radial glow), confirmed via computed style
after a fresh load (`rgb(5, 11, 30)`). Found a stray Chrome window titled
"Zeno GUI Loop" left over from an earlier `/loop`-driven browser preview
of this exact page -- flagged to the user as the likely source of both
the "laggy" and "another gui" complaints (a second live WebGL orb render
loop competing for the same GPU), not force-closed since it's the user's
own browser window. Also discovered and ruled out as a red herring: this
venv's `pythonw.exe` is a `virtualenv`-style launcher stub that always
relays to the base Python312 install as a child process (confirmed via
`pyvenv.cfg`'s `home`/`base-executable` and by checking actual window
count, not process count -- only ever one real "ZENO"-titled window) --
looks like a duplicate app launch in a process list, isn't one, not a bug.

## Agent Ring (2026-08-03)

User pushed back on the "that's too big to build" answer for the mega
GUI spec and asked to finish it. Picked the single largest, genuinely
buildable, highest-payoff slice of that spec rather than faking pieces
of the rest: a real Agent Ring around the main orb -- 13 specialist
dots (added HELIOS as a 13th real specialist to `subagents.py`, wellbeing
role, real tools only: current_activity/daily_activity_summary/write_note/
list_memories), each with the color/icon from the user's own spec table,
positioned by real trig (`static/index.html`'s `agentRing` module), slow
idle orbit (recomputed in JS every 100ms so the SVG beam lines stay
attached to their dot -- a CSS-transform rotation would have visibly
detached them), live activation driven off the SAME real SSE tool events
already flowing for delegate() (a dot lights up + draws a beam to center
on the matching `tool` event, dims on the matching `tool_result`, keyed
by tool_call id via a new `callIdToAgent` map so concurrent activations
from the parallel-delegation work don't stomp each other). Click a dot
for a real dashboard (name/role/status/current task/last result/times
used) -- deliberately NO fabricated CPU/GPU/memory/confidence-score
numbers, since nothing on this architecture actually produces those per
sub-agent call; showing fake ones would be exactly the placeholder
pattern avoided everywhere else this build. Hidden in mini mode, same as
the other overlays. Verified live: 13 dots render with correct colors
including HELIOS, activate()/deactivate() called directly and via a real
delegate() turn correctly toggle dot state/beam opacity/team-overview
count, dashboard shows real task/result text and increments its use
count, close button works, zero console errors.

Explicitly NOT attempted from the same pasted spec, stated plainly rather
than faked: Digital Twin, Knowledge Galaxy, Agent War Room, Mission
Command, Live Environment Scanner, Cinematic Mode/camera movement,
Sandbox simulation, AI Marketplace, Multi-Monitor Intelligence, Live
Desktop Map, Knowledge Constellation, drag-and-drop Workflow Builder, and
similar -- each is a genuinely large, standalone feature (some
effectively a 3D engine or a simulation system), not a gap-fill on the
current architecture, and building shallow versions of them would be the
placeholder-implementation anti-pattern the user explicitly said to
avoid.

## Orb v3 (CSS, no WebGL), Missions, Command Palette, Focus Mode, Explainability (2026-08-03)

**Orb rewritten from WebGL to plain CSS.** The user rejected orb v2
outright -- "not the orb i want... simple orb with the subagent around",
"should not lag at all", "not the one with high gpu that will make it
lag". v2's problem was architectural, not tunable: a fullscreen fragment
shader evaluating simplex noise per pixel per frame is expensive no
matter how the pixel ratio and octave count are trimmed (both had
already been cut). v3 (`static/orb.js`) is a radial-gradient circle plus
a CSS breathe animation and a hue custom property -- GPU-composited,
no three.js download, no WebGL context. Public API kept byte-identical
(setState/pulse/setPerformanceMode/setActive/dispatchAgent/
setAgentWorking/getAgentScreenPositions/specialists) so index.html and
the Agent Ring needed zero changes; the state table moved from 0..1 hue
fractions to CSS hue degrees but keeps all 11 states. Hue transitions run
on a 50ms setInterval rather than rAF -- there is nothing per-pixel to
recompute, so 60fps for a value that changes every few seconds is waste.
Import bumped to `orb.js?v=4` (the stale-cached-orb.js bug bit this build
before -- see the caching section above). Verified: three.js is not
loaded at all (`typeof window.THREE === 'undefined'`, zero network
requests matching "three"), the old canvas is `display:none`, the CSS
orb renders centered, all 13 ring dots present, zero console errors.

**Missions** (`tools/missions.py`, new): long-running goals as real
tracked objects, same shared-state.db pattern as work.py/calendar.py.
Bounded state machine (planning/researching/building/testing/reviewing/
paused/blocked/completed/archived/cancelled), progress percentage,
objectives checklist, timestamped log. Five tools (create/list/get/
update/set_objective_done) plus `list_missions_dicts()` for the GUI
(JSON shape for the panel vs. the text shape the LLM consumes -- same
data, different consumer). `GET /api/missions` + a live side panel with
progress bars, polled on the existing 8s cadence. ATLAS (mission-control
specialist) got the new tools. Deliberately NO risk score, completion
forecast, or confidence number: nothing here computes those honestly and
a fabricated number is worse than an absent one. Verified end to end
against the real DB (create -> list -> get -> update -> check objective),
then the test row was deleted.

**Command Palette** (Ctrl+Space or Ctrl+K), **Focus Mode**, and an
**Explainability panel**. Every palette entry is either a direct UI
toggle or a real message routed through `runTurn()` -- nothing bypasses
the normal agent/tool/confirmation pipeline. Focus Mode dims the
background, force-engages performance mode (restoring the user's own
previous perf setting on exit rather than silently overwriting it), and
DIMS idle specialists to 0.28 rather than hiding them -- an early version
hid them outright, which directly contradicted "simple orb with the
subagent around", caught during live verification. The Explainability
panel reports only real per-turn facts (provider, specialists actually
dispatched, tools actually called, elapsed ms); no confidence score,
same reasoning as above.

**All toggles default ON** per explicit user request ("make all the
toggles on"): the localStorage reads flipped from `=== '1'` to `!== '0'`
so first run is on and an explicit opt-out still persists.

**Verification caveat, recorded honestly:** computed-style readings
(opacity/width) taken through the Browser pane are unreliable in this
environment -- the pane is not displayed, so the page does not composite
and style recalculation is throttled; even a forced inline
`style.opacity='1'` did not move the reported computed value. DOM-level
assertions (class lists, `Element.matches()`, cssRules inspection, SVG
attributes, textContent) ARE reliable and were used instead: the active
dot carries `.active`, `.agent-dot.active {opacity:1; width:46px}`
matches it, the focus dim rule correctly does not, beams toggle
stroke-opacity 0.55/0, and the team overview text tracks the real active
count. Visual confirmation of the new orb's appearance still needs a
human look at the real window.

## Autonomy policy + Investment Policy Engine (2026-08-03)

**Autonomy fully enabled at the owner's explicit, repeated, informed
request.** `.env` now carries `AUTONOMY_MODE=on`,
`AUTONOMY_ALLOW_DESTRUCTIVE=1`, `AUTONOMY_ALLOW_OUTBOUND=1`. Every
consequential tool -- delete_file, run_command, send_slack_message,
send_telegram_message, move_file, create_3d_model -- now executes
directly with no confirmation queue. The risks (irreversibility, the
model's own demonstrated malformed tool calls) were stated plainly before
this was flipped, and the owner authorized it for their own installation
anyway; that's their call to make about their own machine. Configurable
per-installation, never a hard-coded default. Every autonomous execution
still writes an `autonomy_auto_approved` line to
`REYES/07-System/logs/audit.log` before it runs, so nothing unattended is
invisible afterwards. Verified live end to end: a Telegram send that
previously queued now returns "Sent to your Telegram" and ZENO replies
just "Sent." with no permission narration.

**The one carve-out: money movement.** `config.AUTONOMY_NEVER_AUTO_TOOLS`
is checked FIRST in `_autonomy_allows()`, before the mode flag and before
every other category, and it has no enabling flag at all. No tool that
places an order, transfers funds, or touches a broker/bank/wallet API
exists in this build and none is being added. This is deliberate and it
is not a gap to be filled later: an erroneous trade is the only failure
mode in this entire system that cannot be undone, retried, rolled back,
or apologised for, and the same model driving these tools emitted
empty-input `delegate` calls three separate times in this very session.
Verified: those tool names return blocked from `_autonomy_allows()` even
with every autonomy flag on.

**Investment Policy Engine** (`tools/investing.py`, new, 7 tools) --
built to the spec's actual risk-management substance, stopping exactly at
order placement. Three tables in the shared state.db (`invest_policy` as
one JSON row so fields can be added without migrations, `invest_holdings`,
`invest_trades`). Real, working: configurable policy (max capital, max
loss per trade, daily loss limit, max position percent, approved
brokers/asset-classes/strategies, market hours, emergency stop, currency);
portfolio tracking with live allocation percentages, unrealized P&L, and
automatic policy-breach detection; `check_trade_against_policy` which
validates a proposed trade against every rule and emits a PASSES/BLOCKED
order ticket the owner places themselves; trade recording that warns when
the daily loss limit is hit; and a performance report. Verified against
real arithmetic: a deliberately bad trade correctly tripped six separate
rules at once (unapproved broker, unapproved asset class, unapproved
strategy, over max capital, over position limit, risk-to-stop over the
per-trade limit); breach detection correctly flagged an over-concentrated
and unapproved-class portfolio; trade recording and the performance
report returned correct P&L. Test rows and test policy values were then
deleted so the owner sets their own real numbers. TITAN got the read-only
subset of these tools plus an explicit "not a licensed adviser, no tool
that spends money, and there will not be one" line in its prompt.

Module is fully self-contained: removing `investing` from
tools/__init__.py's import line disables the whole engine and touches
nothing else.

## Orb eyes, Morning Companion, presence, workspace resume, ElevenLabs-only (2026-08-05)

**Expressive orb eyes** -- two CSS shapes inside the core. An expression
is ONE class swap (`eyes-calm|attentive|focused|scanning|bright|concerned|
closed`), mapped from the existing STATES table, so it adds nothing to the
frame budget the WebGL-removal bought back. Blinks run on a randomised
3-8s `setTimeout` (not rAF), with an occasional double-blink so it doesn't
read as metronomic; the timer stops on tab-hide and when the orb is
switched off, because "off" must mean zero work. Only `searching`
animates the eyes, and only while it lasts. Honours
prefers-reduced-motion.

Verified what is verifiable through the Browser pane: 2 eye elements,
correct class per state, `Element.matches()` confirms the right rule
applies (e.g. `#orb-simple.eyes-closed .orb-eye -> 2.5%`), concerned adds
a rotation, blink applies and clears. NOT verified: the rendered
appearance -- `getComputedStyle` heights come back stale because the pane
isn't compositing (same limitation recorded on 2026-08-03; a forced
inline style didn't move the reported value either). The visual needs a
human look.

**Morning Companion** (`morning_brief`) -- greeting, yesterday's real
activity totals from `activity_log`, open missions, calendar, what is
genuinely waiting (approvals/notices), and ONE concrete suggested start
drawn from the least-advanced open mission. Once per day unless forced.
Wired into `proactive._check_morning`: queued as a NOTICE, not speech,
and only when the user is actually at the machine (idle < 120s) between
05:00-12:00. Deliberately not spoken unprompted -- an assistant that
starts talking the moment you sit down is worse than one that waits.
Verified on real data: "335 active minutes yesterday, mostly chrome
(214m)".

**Presence check** (`check_presence`) -- input idle time first (decisive
and free when recent), then webcam MOTION between two frames if the user
has been idle. Frames compared in memory, never saved.

Scope corrected during testing, and the tool's own description now says
so: this is NOT face detection. OpenCV 5.0.0 removed `CascadeClassifier`
from the main namespace and ships no Haar cascade XML files (`cv2.data.
haarcascades` exists but the directory is empty); `FaceDetectorYN` needs
an ONNX model this install doesn't have. Rather than claim face detection,
it measures what can actually be measured -- whether the picture changed.
Verified both paths: active user -> "here, active at keyboard (no camera
used)"; forced-idle -> camera path returned motion index 31.53 against a
1.5 threshold.

**Workspace resume** (`resume_workspace`) -- reconstructs the last
session from real activity samples (apps within 2h of the most recent
sample, ZENO's own processes filtered out), the live mission, and
recently-touched notes. Reports by default; `apply=true` reopens the
apps. Verified: correctly identified the last session and its apps.

**ElevenLabs is now the ONLY voice.** The browser Web Speech fallback was
the "dual voice" the user reported: a slow or failed `/api/tts` made the
panel speak the same line in a different robotic voice, sometimes
overlapping the ElevenLabs audio arriving moments later. `speakWithBrowserVoice`,
`SpeechSynthesisUtterance` and the voice-picking code are **deleted**, not
just bypassed -- leaving a fallback voice in the file invites it back. If
ElevenLabs can't speak, ZENO stays silent and the caption carries the
reply; the roll call skips a failed line rather than switching voice
mid-sequence. Confirmed by grep: zero remaining references, only a
`speechSynthesis.cancel()` to silence anything an older build queued.

## Evolution Engine, Digital Twin controls, Knowledge Galaxy, Constitution (2026-08-05)

**Evolution Engine** (`evolution.py` + `evolution_report`) -- ZENO
measuring its OWN performance from records it already keeps: tool latency
and failures from the Event Bus, unused capability (registered tools with
zero events), agent restarts and success rates from the Agent Runtime,
duplicate memories, stale missions, model latency. Every finding carries
its evidence. Scores are deliberately simple and explainable -- a score
nobody can trace to a measurement is just a reassuring number.

The hard rule, restated in the module and in the output: **nothing is
applied automatically.** It measures and recommends; applying is a human
act. Verified on real data: correctly flagged `delegate` at 24.4s/call
(3 real calls) and 101 of 112 tools never used -- the latter being a
genuinely actionable finding, since unused tools still cost latency in
every request.

Honesty fix during testing: `health` returned 0 when the Agent Runtime
simply isn't booted in that process (CLI/tests). Zero reads as "every
agent is unhealthy", which is a different claim from "no runtime here to
measure". Now returns None and renders "n/a".

**Digital Twin controls** (`digital_dna_control`) -- status, export,
reset, disable, enable. Two decisions worth keeping:
* The disable flag is checked INSIDE `activity_monitor._sample()`, at the
  point of collection, so "disabled" means no sample is ever written --
  not merely hidden from a report. A privacy toggle that still collects
  would be a lie.
* Reset deletes the rows. "Delete" has to mean delete.

**A bug that made Digital DNA silently useless.** `activity_log.ts` is a
float UNIX timestamp (written by `activity_monitor` as `time.time()`), but
the query filtered with `julianday('now') - julianday(ts) <= days`, which
misreads a unix float as a Julian day number and matched nothing. The
report therefore said "not enough activity recorded yet -- 0 samples"
while **2091 real samples** sat in the table. Deceptive failure mode: it
looked like an empty profile rather than a broken query, and would have
stayed hidden indefinitely. Fixed by comparing timestamps directly and
parsing with `fromtimestamp` (with an ISO fallback for older rows). Now
produces a real profile: 1942 active minutes over 8 days, chrome 56%,
peak hours 11:00-12:00.

**Knowledge Galaxy** (`GET /api/galaxy` + SVG panel) -- the REAL vault
graph, drawn. Layout is computed server-side deterministically (kind-based
rings + hashed angle) rather than by a browser physics simulation:
a force layout on this machine's GPU is exactly what caused the lag this
build spent hours removing. Same graph, zero per-frame cost. Click a star
to dim non-neighbours and highlight its real edges; search filters live.
Verified in-browser: 10 nodes, 10 edges, click-focus dimmed 8 and
highlighted 1 real edge, zero console errors.

**CONSTITUTION.md** -- the governing document: truthfulness first, the
decision hierarchy, what ZENO will not do regardless of instruction
(money, self-modification, attacks, credentials, bulk third-party
submission), permissions, privacy, agent responsibilities, resource
policy, failure handling, and how it's amended.

Note: several modules (`living_memory`, `memory_manager`,
`performance_monitor`, `resource_manager`, `scheduler`, `worker_pool`,
`browser_runtime`) appeared in the tree from outside this session; they
were verified to import cleanly and were built ON rather than duplicated.

## Knowledge Graph, Research Lab, Session Recovery, Situation Room (2026-08-04)

**Knowledge Graph** (`knowledge_graph.py`) -- real entities and edges
extracted from the vault: `[[wikilinks]]` -> link edges, `#tags` -> tag
edges, folders -> contains edges, shared tags -> related edges (capped at
25 notes/tag so one common tag can't produce a quadratic explosion of
meaningless edges). Nothing is inferred by a model, so "show me
everything about X" is a factual answer traceable to files the user wrote.
Orphans are reported rather than hidden -- in a real vault they're the
interesting part. Verified against the actual vault: 8 nodes, 10 edges,
real wikilinks resolved, hubs ranked by true degree. Tools:
knowledge_graph_stats, explore_knowledge.

**Research Lab** -- creates a real mission, runs real research on ARIS's
live worker, writes a real report file, links it back, and advances the
mission. Every artefact it claims exists on disk.

**Situation Room** (`GET /api/situation`) -- one composed view of system,
agents, missions, campaigns, model router, permissions, events, pending
approvals and session state. Every block reads from a subsystem that
already reports observed state; nothing is synthesised for the dashboard.
Verified live: 13/13 agents, 82% RAM, 66 events, trusted_local profile.

**Agent Monitor GUI** -- live per-worker rows (state, heartbeat age, queue
depth, tasks done/failed, success rate, restart button). Stale heartbeats
flag red. Polls only while open. Verified: 13 rows, correct roles, live
heartbeat ages, 0 stale.

**Executive Meeting** -- every specialist reports its REAL runtime metrics
aloud in its own voice, then ZENO summarises. Numbers come from
agent_runtime.health(), never invented.

**Model Router** (`model_router.py`) -- availability from real
credentials, health from consecutive-failure counts, fallback around
degraded providers, and latency MEASURED in provider.py on every real
call. Reports honestly in its own `note` that with 2 providers configured
most routes collapse to one and routing is near a no-op here.

### Session Recovery -- and the bug that would have made it a lie
`session_recovery.py` snapshots history/missions/campaigns/agent metrics
every 60s atomically (tmp + replace, so a crash mid-write can't corrupt
it) and restores on boot.

**The bug:** the server runs as `python -m reyes_agent.web`, so that
module exists TWICE -- as `__main__` (the live one serving requests, whose
`_history` the running server appends to) and as `reyes_agent.web` (a
second, permanently empty module object). `_gather()` did a plain
`from reyes_agent import web` and read the empty one. The snapshot wrote
`history: []` after a genuine conversation and restore would have been a
silent no-op for ever, while still reporting "restored: true".

Caught only by testing restore for REAL -- creating a conversation,
waiting for a snapshot, hard-killing the process, and checking whether the
specific phrase survived. A first pass looked like success because ZENO
still recalled the phrase; it came from the durable memory store, not the
history restore, and `messages_restored: 0` gave it away. Fixed with
`_live_web()` resolving the actually-running module via `sys.modules`.

Re-verified end to end after the fix: snapshot captured 2 real history
entries, hard kill, restart -> `messages_restored: 2`, and the summary
states the snapshot was 39s old rather than implying nothing was lost.

## Agent Runtime + self-healing, Paper Trading + Backtesting (2026-08-04)

### Agent Runtime -- and an honest scoping decision
The spec asked for every agent to be "alive" as a persistent service. A
ZENO specialist is a prompt plus a scoped toolset; between tasks there is
genuinely nothing for it to compute. Twelve threads busy-waiting to look
impressive would burn CPU on a 4-thread machine to produce a convincing
lie -- exactly what the spec forbids. So what was built is the version
that is real:

* Each agent owns a LIVE worker thread from boot to shutdown, blocked on
  its own queue. `Thread.is_alive()` is the source of truth for "alive",
  not a flag we set.
* Real per-agent task queues. `delegate()` now SUBMITS to the specialist's
  own worker instead of executing ad hoc on the caller's thread, so
  agents genuinely work concurrently with their own metrics and state.
  Falls back to direct execution when the runtime isn't booted (CLI/tests).
* The heartbeat is emitted BY the worker loop. If the thread dies the
  heartbeat genuinely stops -- no timer lying on the thread's behalf.
  That distinction is the entire point.
* A supervisor restarts exactly the dead worker, preserving its queue.

**Recovery proven, not asserted.** A real `SystemExit` was injected into
ARIS's thread via `PyThreadState_SetAsyncExc`. The supervisor detected it
and revived the worker with no manual call: `restarts` 0 -> 1, queue
intact. Worth recording: the worker stayed `alive` for ~2s after the kill
because an async exception only lands when the thread leaves its blocking
`queue.get` -- real behaviour, and a reason heartbeat-staleness (not just
`is_alive`) is checked.

Idle agents block on their queue consuming no CPU and report IDLE, which
is the truth. `health()` reports only what is observable. API:
GET /api/agents, POST /api/agents/{id}/restart. Verified live: 13/13
alive and healthy, supervisor up, and a real delegation to KATE recorded
on her own worker (completed=1, 1.28s, task text captured).

AI-Company titles (CTO/CSO/CFO...) are dashboard labels only -- actual
behaviour remains each agent's prompt and toolset in subagents.py. Said
plainly rather than implying a hierarchy that does not execute.

### Paper Trading + Backtesting
Real historical daily bars from Yahoo's keyless chart endpoint (Stooq
returned 404; tested both before choosing). `backtest_strategy` supports
buy_and_hold and sma_cross with real max-drawdown and trade counts, and
ABORTS rather than reporting anything if data can't be fetched -- no
result beats a fabricated one. Verified on 501 real AAPL bars, and it
honestly reported the SMA strategy LOSING to buy-and-hold by 41.9%.
Output always states that fees, slippage and taxes are not modelled.

`paper_trade`/`paper_portfolio`: simulated account, live prices, real
average-cost tracking and realized P&L, with over-sell and over-spend
guards (both tested). Entirely local -- no broker, no money. The
real-execution boundary in config.AUTONOMY_NEVER_AUTO_TOOLS is unchanged.

Bug found and fixed during testing: `_fetch_history` enforced a 10-bar
minimum meant for backtests, which broke simple price lookups needing one
bar. Now `min_bars` is a parameter.

## LAG ROOT-CAUSED PROPERLY: tool count, not the GUI (2026-08-04)

After three GUI-side fixes the user still reported lag, so this time it
was MEASURED instead of guessed. Result, and it was not the GUI at all:

    93 tools -> 5.35s avg per turn
     5 tools -> 1.50s avg per turn
     0 tools -> 1.75s avg per turn

Tool COUNT dominated latency. Every turn -- including "say hi" -- shipped
~13,900 tokens: 3,391 of system prompt and 10,480 of tool schemas for 93
tools. The schema payload had grown unbounded as subsystems were added,
and nothing was watching it. `tools/__init__.py` already carried a comment
saying tool count is expensive for OLLAMA specifically; the wrong
inference had been drawn that cloud providers didn't care. They do.

**Fix: lazy tool groups.** `TOOL_GROUPS` maps ~40 deeper operations to
groups (missions, campaigns, investing, council, work, creative, comms,
admin). `tool_definitions(groups=...)` returns core plus whatever is
enabled. The main agent starts with core only (54 tools, 24KB vs 94 tools,
43KB -- a 43% payload cut) and widens mid-turn by calling `enable_tools`,
which `agent.py` intercepts to rebuild the toolset for the remaining
rounds. Nothing is removed: specialists keep their scoped sets, and any
group is one call away.

Measured after: 2.92s -> 2.05s average, and the multi-second spikes
disappeared. ~1.5s is the Gemini round-trip floor and no amount of local
work goes below it -- said plainly rather than promising more.

Also measured and ruled out: startup import cost (~0.8s for
reyes_agent.tools; the 2.2s `site` cost is pip/truststore in this
environment, not ZENO).

## Per-agent voices + Agent Roll Call (2026-08-04)

Owner supplied 12 real ElevenLabs voice ids; added to .env as
ELEVENLABS_VOICE_<AGENT>. All 13 agents now have their own voice --
`registry()` reports 0 fallbacks, down from 12. Verified they are
genuinely distinct, not just configured: synthesizing the same sentence as
ULTRON and APEX produced different byte lengths and different MD5s.

Roll call: `voice_manager.roll_call_sequence()` returns an ordered
[{agent, text}] list; `GET /api/rollcall` serves it; the panel's
`playRollCall()` plays each line through `/api/tts` with that agent so
every specialist speaks in its OWN voice. Sequential by construction
(awaits each clip's `ended`) -- twelve overlapping voices is noise, not a
roll call -- and the mic is stopped for the duration so ZENO doesn't
transcribe its own team, then restored only if it was listening before.
Per-line failures fall through to the browser voice rather than hanging
the sequence.

Returned as DATA rather than synthesized server-side on purpose: the panel
may be open on a phone, and server-side audio would play on the wrong
machine's speakers.

Introductions are once-per-session (`_introduced` set, process lifetime),
with `agent_introduction` for "TOSIN, what is your role?" and short
per-agent acknowledgement lines defined for task pickup. Verified
in-browser: captions show "ULTRON: I am ULTRON.", the agent ring lights
the speaking agent, zero console errors.

## Permission Engine + Plugin Permission Manager + Mini Orb Companion (2026-08-04)

### Installation trust policy (INSTALLATION-SPECIFIC, NOT A DEFAULT)
The owner of THIS installation granted full local desktop trust on
2026-08-04. Recorded as `INSTALLATION_PROFILE=trusted_local` in .env. The
shipped default for any other installation remains `cautious` -- copying
this codebase elsewhere does NOT copy the trust. That distinction is the
entire reason profiles exist rather than a global default being flipped.

`trusted_local`: filesystem read/write/delete, app control, desktop
automation, clipboard, system commands, browser automation, network read,
vision, plugin exec, and messaging_send all ENABLED. email_send and
social_post remain CONFIRM (owner-configurable). `financial` is BLOCKED in
every profile with no enabling flag anywhere, and `state_for()` returns
BLOCKED for it before consulting profile or env -- so no config change can
open it. Verified: place_trade returns blocked while the profile is fully
trusted.

### Architecture: one decision point
`tools/__init__.py::_autonomy_allows` was refactored to DELEGATE to
`permissions.check()` instead of keeping a second parallel rule set. Prior
to this the autonomy flags lived in tools/, the plugin rules lived in the
loader, and they were already drifting. AUTONOMY_MODE survives as a kill
switch (off -> everything consequential back through the gate regardless
of profile), and money-movement is checked in BOTH places deliberately --
two locks, no single point of failure.

### Plugin Permission Manager
A plugin must ship `<name>.json` declaring the capabilities it needs.
`may_load_plugin` refuses, in order: no manifest at all; unknown
permission names; any BLOCKED capability requested; not approved by the
user at that exact version. Version bumps require re-approval, so an
update cannot silently widen reach. All five paths verified with real
files on disk (no-manifest refused, `financial`-requesting plugin refused,
untrusted refused, trusted loaded, version bump re-refused).

Stated plainly rather than implied: an approved plugin is still arbitrary
Python running with ZENO's permissions. The manifest gate controls WHETHER
it loads and makes its claimed reach visible; it does not confine it
afterwards. Real confinement needs process isolation and is NOT built.

Tools: permission_status, list_plugins, trust_plugin, revoke_plugin.
API: GET /api/permissions, GET /api/sysstats.

### Mini Orb Companion
The companion window is now a real presence rather than a shrunken app:
orb scales to 130px, desktop background drops away, all chrome hides.
Additions: a glassmorphism hover card showing live state (active agents,
current mission + %, task count, pending approvals, CPU, RAM), a mission
ring that rotates only while work is running (one GPU-composited CSS
animation, no per-frame JS), grab/grabbing cursor feedback, middle-click
to toggle standby, double-click to expand.

Performance discipline held: the hover card polls ONLY while hovering in
mini mode and stops on mouseleave; `/api/sysstats` is a deliberately tiny
endpoint using non-blocking `cpu_percent(interval=None)` and no process
enumeration (unlike the full `system_health` tool). At rest the companion
costs nothing, which is the point of something that sits there all day.

Verified in-browser: orb 130px, UI hidden, ring hidden when idle and
shown when working, card hidden without hover and shown on hover, live
CPU/RAM/mission values populated, zero console errors.

### Regression caught during this work
An edit left prose stranded outside a docstring in tools/__init__.py,
producing a SyntaxError that would have prevented the app starting at
all. Caught by running the module rather than trusting the edit. Also
noted: startup is measurably slower now (heavier import graph) -- worth
watching before it becomes a complaint.

## Campaign Engine (2026-08-04)

Bulk work with a real approval gate -- the user's own design, and it
resolves the standing objection to mass automation properly. The problem
with bulk automation was never batching; it was firing irreversible
outward-facing actions nobody looked at. This keeps the batching and
removes that:

* Campaigns are built in DRAFT; nothing runs while drafting.
* `preview_campaign` renders EVERY action with its real resolved
  arguments -- not a summary, not a sample.
* Approval is one explicit act on the whole batch, timestamped. `start()`
  REFUSES a campaign that isn't approved (verified: returned "must be
  approved first" and did not run).
* Tool names are validated at ADD time, so a preview can never show an
  action that was never going to work (verified: a bogus tool name was
  rejected at add).
* Money-movement tools are re-checked at EXECUTION time as well as add
  time -- batch approval is not a way to launder a category that has no
  enabling flag anywhere.
* Pause/cancel take effect between items (verified: cancel stopped a
  10-action campaign after 3).
* Failures retry with exponential backoff up to 3 attempts, then record
  the real error; `retry_campaign_failures` resets them (verified with a
  genuine exception: error text captured, reset to pending).
* Each campaign mirrors into a Mission so long batches appear alongside
  every other long-running objective, and every item publishes to the
  Event Bus for the Timeline.

Runs on a background thread -- the GUI never blocks on a campaign.

Testing note worth keeping: two of my first failure tests produced NO
failure, because `get_datetime` ignores unexpected kwargs and `read_file`
handles a missing path gracefully by returning a message rather than
raising. The retry path was only genuinely proven on the third attempt,
using a missing required argument (a real TypeError -> "Error: bad input
for 'read_file'"). A tool returning a polite "not found" string is NOT a
campaign failure and shouldn't be -- the tool ran and reported a fact.

## Advisory Council, System Monitor, Plugin loader (2026-08-04)

**Advisory Council** (`council.py` + `tools/council_tools.py`, 5 tools).
Three properties make it a reasoning system rather than role-play, and
all three are enforced in code:
1. ISOLATION IS ARCHITECTURAL -- each advisor is its own `run_turn()`
   call with its own system prompt and dossier. No advisor is told who
   else was consulted or what they concluded, because that information
   never enters its context. Multiple advisors are never simulated in one
   model call (that would be one model writing a pretend debate).
   Advisors run concurrently via ThreadPoolExecutor; parallelism affects
   only wall-clock, not isolation.
2. THE CITATION GATE IS CODE, not a prompt request. Every `[ID]` in an
   advisor's output is regex-checked against that advisor's own doctrine
   ids; unknown ids are replaced with "[citation removed]" and reported.
   Verified: a planted `[FAKE-99]` was stripped while `[LS-002]` passed.
3. DOCTRINE CARRIES PROVENANCE -- id, summary, source, verification
   state, topic, date. Duplicate ids across dossiers disable the later
   advisor. A malformed dossier disables ONLY itself (verified with a
   deliberately broken JSON file: the other three advisors still loaded).

Advisor selection is deterministic keyword overlap against declared
domains -- inspectable, and no extra model call just to choose who
speaks. ULTRON is a separate call that SEES the opinions (its job is to
attack them) but never contributed one to defend. Meetings persist to
SQLite with `record_council_outcome` so predictions can later be compared
against what actually happened.

Deliberate integrity decision: shipped dossiers describe DOCUMENTED,
SOURCED FRAMEWORKS (Lean Startup, decision science/reference-class
forecasting, systems reliability) with real citations -- not
impersonations of living people. Fabricating opinions and attributing
them to a real named person as their "doctrine" is exactly the
fabricated-evidence failure this system exists to prevent; the format
requires a source field for that reason.

Verified live on "monolith vs microservices, solo student founder": 2
relevant advisors selected, 4 doctrine citations all valid and all from
the citing advisor's own dossier, 0 fabricated, both advisors
volunteered their own blind spots, and ULTRON openly disagreed with BOTH
("both advisors miss the real failure mode") -- i.e. real structured
disagreement, not consensus theatre.

**System Monitor** (`system_health`) -- real psutil readings: CPU/threads/
frequency, RAM, disk, battery, temperature where exposed, network totals,
ZENO's own RSS including child processes, and the heaviest running apps.
First run surfaced something directly relevant to the standing lag
complaints: this machine has 8.4GB RAM and was sitting at 88% used.

**Plugin loader** (`tools.load_plugins`) -- drops any `*.py` in
vault/07-System/plugins into the tool registry using the SAME `register()`
contract as built-in modules, so there is no second plugin API to
maintain. Loaded last so a plugin cannot shadow a built-in; one failing
plugin is logged to audit and skipped rather than breaking startup.
Stated plainly in the docstring rather than implied: plugins are NOT
sandboxed and run with ZENO's permissions -- signature verification and
sandboxing are real work that does not exist here.

## Parallel delegation ROOT CAUSE, Browser Controller, Voice Manager, Companion Mode (2026-08-04)

**The multi-agent bug, finally root-caused.** The user's #1 complaint
("multi-agent is not functioning, ZENO answers everything directly") was
NOT a prompting problem and not the ThreadPoolExecutor work from
2026-08-03 -- it was a provider streaming bug in `provider.py`, and an
older comment in that exact function had predicted it and dismissed it as
"not hit in testing". Gemini sends `index=None` on EVERY tool-call delta
(xAI/OpenAI number them 0,1,2...). The fallback `key = 0` merged every
simultaneous call into one slot, so two `delegate` calls concatenated
their JSON arguments into `'{...}{...}'`, which fails `json.loads`, which
fell through to `tool_input = {}`. That is the empty-input `delegate`
call seen repeatedly all session and blamed on the model. Parallel
delegation therefore never worked on Gemini -- the executor was correct,
it was just never handed two valid calls. Fix: with no index to trust, a
delta carrying a NEW id (or a different function name) starts the next
slot. Verified live: a two-domain request now produces two delegate calls
BOTH with complete `{specialist, task}` arguments, dispatched in one turn.
Lesson worth keeping: a comment saying "not hit in testing" on a known
correctness gap is a bug waiting to be reported as something else.

**Browser Controller** (`browser_controller.py` + `tools/browser.py`, 9
tools) -- real Playwright automation, verified working end to end through
a live conversation (opened example.com, read the text back). ONE
long-lived persistent context backed by an on-disk profile
(vault/07-System/browser_profile), so logins and cookies survive both
across tool calls and across restarts -- that's what makes "log in, then
do this" possible at all. Headed by default so the user can watch and
take over; BROWSER_HEADLESS=1 for background. Tools: open, read, click
(by visible text first, like a person), fill, extract (structured lists),
scroll, screenshot, vision_click, close. `browser_vision_click` is a real
OpenCV template-match fallback for canvas apps and obfuscated markup --
it needs a reference image, which is why it's an explicit tool rather
than pretending selectors self-heal. Deliberately NOT built: any
bulk-submission helper (mass job applications, bulk posting) -- the
primitives can drive one form at a time with the page visible, but firing
generated applications at employers in bulk reaches third parties, can't
be recalled, and damages the user's own reputation if the model is wrong.

**Voice Manager** (`voice_manager.py`) -- 13 per-agent voice profiles with
real ElevenLabs stability/similarity settings shaping delivery (ULTRON
flat and deliberate at 0.85; ZEAL expressive at 0.35). Voice ids come from
per-agent .env keys (`ELEVENLABS_VOICE_ARIS` etc.) and fall back to the
main configured voice -- a real fallback, not a stub: with zero config
every agent speaks in ZENO's voice today and gains its own the moment an
id is added, and nothing invents voice ids that don't exist on the
account. `/api/voices` reports honestly which agents have their own voice
vs. which are falling back (currently 12 of 13). On-disk cache keyed on
(text, voice, settings): measured 3.36s -> 0.19s on a repeat, i.e. a 17x
speedup and zero API spend on repeated lines like "Standing by." Speech
queue serializes playback so two agents finishing together don't overlap.
Server-side playback streams PCM (sounddevice can't decode MP3); the
cached-MP3 path serves the browser, which is where repeats actually occur.

**Desktop Companion Mode** -- the mini orb is now a real floating
companion: draggable (the page reports pointer deltas to
`_DesktopApi.move_window` since the mini window has no title bar), snaps
to the nearest edge/corner on release, clamped so it can never be dragged
off-screen and lost, and remembers its resting position across sessions.
A drag no longer counts as the click that reopens the full window.

**Delegation prompt** rewritten to push multi-domain work to parallel
specialists while explicitly forbidding delegation theatre for greetings,
quick facts, and one-step actions.

## Event Bus, Timeline UI, Persistent Listening (2026-08-04)

**Event Bus** (`reyes_agent/event_bus.py`) -- Phase 1 of the roadmap and
the dependency Timeline/Activity Stream/experience tracking all needed.
Typed events (type, payload, source, correlation_id, ts), durable SQLite
persistence in the shared state.db, live pub/sub, and queryable history
with dotted-prefix filtering ("tool" matches "tool.completed"),
correlation grouping, and stats. Three design rules worth keeping:
publishing NEVER raises (an event bus that can break what it observes is
worse than none), fan-out is bounded per subscriber (500) so a stalled
consumer drops events instead of leaking memory, and rows prune at 20k.
`notification_bus` was NOT replaced -- it now forwards into the bus, so
every existing caller (show_map, workspace overlays, notification
listener, SSE) keeps working untouched while gaining persistence.
`execute_tool` emits `tool.completed` with duration. Read side:
`GET /api/events`, `GET /api/events/stats`. Verified: persistence, live
delivery, prefix filter, correlation filter, stats, and a real
conversation turn read back out over HTTP with timing.

**Timeline UI** -- overlay reading `/api/events`, grouped by day with
sticky headers, per-event icon/label reusing `friendlyTool()`, result
snippet, and duration. Fetches on open and on filter change only; history
does not need polling and a closed panel should cost nothing. Opens from
the command palette ("Open Timeline").

**Persistent Listening** -- the real fix for the user's complaint that
wake -> one command -> sleep was unusable. A wake word now opens a
SESSION that stays open across as many commands as wanted; only an
explicit standby phrase ("zeno standby", "go to sleep", "stop listening",
"goodbye"...) closes it. Two things that make this safe rather than
chaotic: standby matching is anchored (whole phrase, or at a word
boundary) so "search for goodbye messages" does NOT put ZENO to sleep;
and a self-echo guard remembers what ZENO last said aloud and discards it
when it comes back through the mic -- without that, ZENO's own reply
through the speakers becomes the next "command", which is the single most
likely way persistent listening goes wrong. Verified via `window.zenoVoice`
(exposed for testing, same pattern as `window.agentRing`): all four
standby phrases detected, zero false positives on the three decoys, echo
correctly caught, real command correctly NOT blocked.

## Lag, root-caused properly (2026-08-03)

Replacing the WebGL orb with CSS was necessary but NOT sufficient -- the
user reported lag again afterwards. Four real causes found, in descending
order of cost:

1. **Webcam ML inference, on by default.** The single biggest one, and
   self-inflicted: interpreting "make all the toggles on" literally had
   turned on hand-gesture control AND mouse control, each of which runs
   MediaPipe `recognizeForVideo()` inside a `requestAnimationFrame` loop
   (`static/gesture.js:100,111`) -- i.e. up to 60 hand-landmark ML
   inferences per second, twice over, on a CPU-only machine. Reverted to
   opt-in (`=== '1'` instead of `!== '0'`). Verified after restart: zero
   `<video>` elements exist and no camera stream is open.
2. **A permanent 60fps rAF loop for the dev overlay.** `devLoop()` called
   `requestAnimationFrame` unconditionally forever and merely skipped the
   DOM write when dev mode was off -- so the page could never go idle,
   for no visible benefit. Now the loop genuinely stops when dev mode is
   off and restarts via `startDevLoop()` on toggle.
3. **Agent-ring layout thrash.** `layout()` wrote `style.left`/`style.top`
   on 13 dots plus 4 attributes on 13 SVG lines every 100ms -- 26
   layout-forcing writes, 10x a second. Now: dots position via
   `transform: translate3d(...)` (composited, skips layout entirely,
   centering still handled by the existing negative margin so the
   active-state size change is unaffected), beams are redrawn ONLY for
   agents that are actually active (idle beams sit at stroke-opacity 0, so
   repainting them was pure waste -- usually zero per tick now), and the
   tick dropped from 100ms to 250ms with the angular step scaled up to
   match, so the drift looks identical at 60% fewer passes.
4. **Developer mode defaulted on.** It's a debug readout, not a feature,
   and it both requires the rAF loop above and puts an overlay over the
   UI. Left off by default despite "all toggles on"; the standing
   "must not lag at all" requirement wins, and it's one click away.

Net: with the CSS orb, no WebGL context and no three.js download, no
requestAnimationFrame loops running at rest, no webcam inference, and the
only remaining timers being a 250ms ring drift, a 50ms hue lerp that
early-returns once settled, and the pre-existing 4-10s data polls.
Verified post-restart: `typeof window.THREE === 'undefined'`, zero video
elements, dev overlay off, dots confirmed using transform with no inline
left/top, 13 dots present, zero console errors.
