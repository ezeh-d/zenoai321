# REYES — new capabilities

This build adds planning, a multi-agent system, long-term recall, a security
module, vision-lite, and mobile access — all wired into the same brain and
tool system, and all runnable from `python run.py` (terminal) or `main.py` (HUD).

## Install & run

```bash
pip install -r requirements.txt
# optional: playwright install chromium   (browser skill)
cp .env.example .env    # then add one model key, or run Ollama for offline

python run.py           # terminal JARVIS
python main.py          # graphical HUD
python server.py        # mobile bridge — open http://<your-ip>:8765 on your phone
python -m mobile.telegram_bridge   # control REYES from Telegram
python doctor.py        # preflight: what's installed / what each mode needs
```

---

## What was added

### 🧠 Planning & reasoning — `core/planner.py`
Turns a goal into an ordered, checkable plan. Uses the LLM when available and a
deterministic heuristic when offline, so planning never fully breaks.
Tool: **`plan`**. Verified: offline plan generation.

### 🤖 Multi-agent architecture — `agents/`
An `Orchestrator` routes a task to the right specialist — **researcher, coder,
operator, writer, analyst** — each with its own persona and tool set. For a
complex goal it drafts a plan and runs it across agents, then synthesizes.
Tools: **`delegate`** (one specialist) and **`solve_goal`** (plan + run + merge).
Verified: keyword routing to all five agents.

### 💾 Long-term memory — `memory/retrieval.py`
Dependency-free relevance search (TF cosine) over your second-brain notes and
recent conversation, so the right memory surfaces without an embedding stack.
Tool: **`deep_recall`**. Verified: correct ranking on sample notes.

### 👁️ Vision (screen reading) — wired into the brain
**`see_screen`** captures the display and OCRs its text (via the existing GUI
skill / Tesseract). Full image *understanding* needs a vision-capable model;
this gives working screen-reading today, degrading gracefully if Tesseract
isn't installed.

### 🖥️ Desktop automation & 🌐 internet + coding
Already present as skills (computer, gui, browser, coder) and now exposed to the
agents (operator drives the desktop; coder scaffolds/runs projects; researcher
uses the browser). No new bugs introduced; the agents give them structure.

### 🛡️ Security module — `security/`  (the responsible answer to "hacking")
- `security/defense.py` — password strength, file hashing, **localhost** port
  audit, and log triage. All local, non-destructive.
- `security/lab.py` — explains attack/defense concepts (XSS, SQLi, CSRF, SSRF,
  authz, recon, hardening) and points to **legal** practice labs (TryHackMe,
  Hack The Box, OWASP Juice Shop, DVWA, VulnHub).
Tools: **`sec_passcheck`, `sec_hash`, `sec_ports`, `sec_scanlog`, `sec_learn`**.
Verified: all defense functions + lab lookups.

> On purpose, this is **defense + authorized learning only** — no exploits,
> malware, or tooling aimed at systems you don't own. The port scanner refuses
> any host except your own machine. That's the line; everything else on your
> list is built.

### 📱 Mobile integration — `server.py` + `mobile/telegram_bridge.py`
- `server.py` — a zero-dependency HTTP bridge with a phone-friendly web UI at
  `/`, a `/chat` JSON endpoint, and `/status`. Open it from any phone on the
  same Wi-Fi. **Live-tested** end to end.
- `mobile/telegram_bridge.py` — long-polls Telegram (using the token already in
  your `.env`) and runs each message through the brain, so your phone's Telegram
  becomes a REYES remote.

### 🔌 Core command layer — now connected
The existing `core/` layer (capabilities, task queue, plugin discovery, model
routing, safety) is now wired into `brain.chat()`: type `capabilities`,
`list plugins`, `queue task ...`, `list tasks`, `which model for ...`.

---

## Also fixed (this version had the same issues as your earlier zip)

- **`run.py`** was `from reyes.cli import main` (broken on Linux/macOS). Rewritten.
- **Import model unified**: the clean core used package-relative imports while
  `core/`, the GUI, and `main.py` used absolute imports — they fought each other
  and broke the HUD's `import brain`. Everything is on absolute imports now.
- **`brain.think()` bridge added** so the HUD, the mobile server, and Telegram
  all reach the same brain (they look for `think`/`respond`/`ask`).
- **Persona upgraded** to the JARVIS voice, now aware of planning and delegation.

---

## Verified vs. not (being straight with you)

**Ran and verified here:**
- All Python compiles (0 syntax errors across the project).
- Full chain imports cleanly under the unified model.
- Brain registers **57 tools** including all 10 new ones; tools execute.
- Planner, multi-agent routing, retrieval, and security functions all work.
- The mobile HTTP server serves `/status`, `/chat`, and the web UI (live test).

**Could NOT run here (no display / audio / GPU / 350 MB models / network):**
- 🎤 **Advanced voice** and 🗣️ **natural speech** — the Whisper→brain→Kokoro
  pipeline. The bridge it calls is verified; the live audio I/O is not.
- The **PySide6 HUD** window itself (imports + backend wiring verified; the live
  window is not).
- Anything needing the internet at runtime (web search, browser, LLM calls) —
  those work once you install deps and add a key / run Ollama.

The voice + HUD polish is the part best finished where the real stack is
installed and you can see and hear it.

## Preflight: `python doctor.py`

Before launching the HUD or voice, run `python doctor.py`. It prints a per-feature checklist (Brain, Terminal, HUD, Voice, Extras) showing what's ready (✓) and the exact `pip install` for anything missing — so you never hit a wall of errors guessing what a mode needs.
