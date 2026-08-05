# REYES

A personal AI assistant with a JARVIS-style personality: terminal + graphical
HUD, planning, a multi-agent system, long-term memory, desktop automation,
internet + coding skills, a defensive security toolkit, and mobile access.

## Quick start

```bash
python install.py       # installs everything needed (handles your OS)
python start.py         # friendly launcher menu (pick a mode)
```

`install.py` sets up your `.env` and runs a check at the end. Prefer to
double-click? Use `setup.bat` (Windows) or `setup.sh` (macOS/Linux).
Faster, terminal-only install: `python install.py --minimal`. Everything plus
optional extras (low-CPU wake word, OCR): `python install.py --all`.

Manual route if you prefer:
```bash
pip install -r requirements.txt
python doctor.py        # see what's installed / what each mode needs
```

Or run a mode directly:

```bash
python run.py                       # terminal assistant
python main.py                      # graphical HUD
python server.py                    # mobile bridge -> http://<your-ip>:8765
python -m mobile.telegram_bridge    # control from Telegram
```

## Give it a brain

Copy `.env.example` to `.env`, then either:
- add a free **Gemini** key (aistudio.google.com), or
- install **Ollama** (ollama.com) and run `ollama pull llama3` — free & offline.

Models are tried in order (your primary → other keys you have → Ollama), so it
always has a fallback. See `.env.example` for details.

## What it can do

Type `capabilities` inside REYES for the live list. Highlights:
- **Plan** a goal, **delegate** to specialist agents, or **solve_goal** end-to-end
- **deep_recall** relevant past notes; **remember** new ones
- Control the desktop, browse, scaffold & run code
- **see_screen** (OCR), defensive **security** tools (`sec_*`)
- Talk to it from your **phone** via the web bridge or Telegram

## Docs & tests

- `FEATURES.md` — full breakdown of every subsystem and what's verified
- `python tests/test_new_features.py` — offline test suite for the new modules

## Security note

The security module is **defense + authorized learning only** — audits, hashing,
localhost port checks, log triage, and a lab that teaches concepts and points to
legal practice ranges. No exploits or malware. Only test systems you own or are
authorized to test.
