# Keeping REYES fast (anti-lag guide)

REYES does three heavy things: **listen** (speech-to-text), **think** (the LLM),
and **speak** (text-to-speech). Lag almost always comes from one of these
running too big for your hardware. Here are the levers, biggest win first.

## 1. The wake word is the #1 CPU cost — make it cheap
While idle, the always-on assistant is constantly listening for its name. By
default that runs full speech recognition on every audio window, which is heavy.

**Best fix:** install a dedicated wake-word engine — a tiny always-on model that
sips CPU and only wakes the real recognizer when it hears the word:
- **openWakeWord** (free, open source): `pip install openwakeword`
- **Picovoice Porcupine** (free tier): `pip install pvporcupine`

REYES has a hook for these in `assistant.py`; with one installed, the idle cost
drops dramatically. Without one, it still works via the built-in recognizer.

**Also:** raise the mic energy threshold so quiet rooms don't trigger
recognition at all. In `.env`:
```
VOICE_ENERGY_THRESHOLD=250      # higher = ignores more background noise
```

## 2. Use a small speech-to-text model
Whisper size drives listening lag. Smaller = faster. In `.env`:
```
WHISPER_MODEL=tiny.en           # tiny.en (fastest) or base.en
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8       # int8 is the light setting
```
`tiny.en` is plenty for short commands and is noticeably snappier than `base`.

## 3. Pick a fast brain
A big local model on a weak CPU is the most common cause of slow replies.
- **Fastest local:** a small model — `ollama pull llama3.2:3b` or `phi3`, then
  `LLM_MODEL=ollama/llama3.2:3b`.
- **Fastest overall on weak hardware:** a fast cloud model —
  `LLM_MODEL=gemini/gemini-1.5-flash` (free key). Cloud offloads the work
  entirely, so your machine stays free for listening/speaking.
The model chain in `llm.py` means you can keep a fast cloud primary and fall
back to local Ollama automatically when offline.

## 4. Don't listen and think on the same core at once
On low-end machines, running Whisper + a large local LLM simultaneously
fights for CPU. Offloading either one (small Whisper, or cloud LLM) removes the
contention. This single change often fixes "it freezes while replying."

## 5. Speak without blocking
Use non-blocking speech so REYES starts the next listen while it's still
talking. `speech.speak_async(...)` (already in your speech.py) does this; the
voice loop uses non-blocking acknowledgements ("Yes?") for the same reason.

## 6. HUD animations
If the graphical HUD feels heavy, the animated core / monitors redraw on
timers. Lowering their refresh rate (the `QTimer` intervals in
`gui/ai_core.py` and `gui/system_monitor.py`) trades smoothness for CPU. Tell
me and I'll set sensible lighter defaults.

## 7. Load only what you use
Each skill is lazy, but the browser (Playwright/Chromium) is the heaviest. If
you don't use web automation, you don't need `playwright install chromium`.

---

### A good low-lag starting point (`.env`)
```
LLM_MODEL=gemini/gemini-1.5-flash      # fast cloud primary (free key)
OLLAMA_MODEL=ollama/llama3.2:3b        # small local fallback
WHISPER_MODEL=tiny.en
WHISPER_COMPUTE_TYPE=int8
VOICE_ENERGY_THRESHOLD=250
```
Plus `pip install openwakeword` for the cheap wake word. With this, the idle
assistant stays light and replies come back quickly.
