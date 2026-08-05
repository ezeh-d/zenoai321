# REYES — What I upgraded

Your folder had two separate brains: your original (`brain.py` → `router.py` →
Ollama) that the HUD used, and my more powerful `reyes/` engine sitting unused.
This upgrade connects them so the futuristic HUD is now driven by the full
multi-skill engine.

## Changes

1. **HUD now uses the powerful engine.** `brain.think()` (what the GUI calls)
   now routes to `reyes_engine.ask()` → `reyes.brain.Brain`. So typing or
   speaking to the HUD can now: chat naturally, control files, drive a browser,
   use Slack, scaffold & run code projects, control any app via GUI automation,
   and save/recall from your second brain — all through the same interface.

2. **Classic router kept as a safety net.** If the engine can't load (missing
   key or dependency), `think()` automatically falls back to your old
   `router.route()`, so the HUD never goes dead.

3. **Obsidian added.** The `reyes/` package was from before Obsidian; it now
   includes the vault skill (`reyes/skills/obsidian.py`). Set
   `OBSIDIAN_VAULT_PATH` in `.env` and REYES writes editable markdown notes with
   tags and `[[links]]` you can see in Obsidian's graph.

4. **Your context shortcuts preserved.** "clear context", "repeat that", etc.
   still work exactly as before.

5. **Dependencies unified.** `requirements.txt` now covers the HUD (PySide6),
   the voice pipeline (SpeechRecognition, pyttsx3, pyaudio), and the engine.

## New file

- `reyes_engine.py` — the bridge between the HUD and the engine, with a
  GUI-safe permission model (below).

## Permission model (read this)

The HUD has no terminal to type y/n into. So from the GUI:

- **Safe actions run normally** — chat, read files, search, browse, remember,
  recall, scaffold projects.
- **Destructive actions are blocked by default** — delete/move/overwrite files,
  run shell commands, GUI click/type.
- **To allow them from the HUD** (at your own risk), set in `.env`:
  `REYES_GUI_AUTOAPPROVE=true`

The terminal version (`python run.py`) still asks y/n normally regardless.

## How to run

```bash
pip install -r requirements.txt
playwright install chromium          # for web automation
# fill in .env (at least one LLM key; optional: Slack, email, Obsidian path)

python main.py     # the futuristic HUD (now powered by the full engine)
# or
python run.py      # the terminal version (asks permission on destructive actions)
```

## Honest notes

- I couldn't run the HUD here (no display/PySide in my environment), so the GUI
  wiring is written correctly and syntax-checked, but its first live run is on
  your machine. The engine + memory are verified.
- Your original modules (agent, commands, desktop_control, vision, search, etc.)
  were left untouched. Over time you can retire the ones the engine now covers.
