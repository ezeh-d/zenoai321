# github_research → ZENO: what was studied and selectively integrated

Rule followed: **no repository copied or merged.** Techniques and parameters
were studied and applied selectively to ZENO's *existing* modules. Every change
is additive and config-gated, so ZENO's architecture and tests are preserved
(EnergyVAD stays the default; faster-whisper behaviour is opt-outable).

## Repos and where they map

| repo | studied for | area |
|---|---|---|
| silero-vad | neural VAD model + `get_speech_timestamps` params (threshold 0.5, min_silence 100ms, speech_pad 30ms, 512-sample windows) | #1 STT, #2 VAD |
| pipecat | `VADParams` turn state machine (confidence / `start_secs` / `stop_secs`), smart-turn | #2 VAD, #3 streaming |
| react-grid-layout | `core/compactors.ts`, `collision.ts`, fast H/V compactors | #5 mini-panels |
| motion | (empty checkout — only `.git`, no source) | #6 animations |

---

## INTEGRATED (code, tested)

### #1 Faster speech recognition + #2 VAD + #4 faster local inference
`reyes_agent/voice/stt/faster_whisper.py`

- **Silero VAD filtering enabled** (`vad_filter=True`, was `False`). faster-whisper
  bundles Silero; trimming non-speech makes transcription both faster and
  cleaner. `vad_parameters` mirror silero-vad's API (`threshold`,
  `min_silence_duration_ms`, `speech_pad_ms`) — padding widened to 200ms so
  conversational word edges are never clipped. Off-switch: `ZENO_STT_VAD_FILTER=off`.
- **`cpu_threads` unpinned** from 1 → `min(4, cpu_count)`, override with
  `ZENO_FASTER_WHISPER_CPU_THREADS`. Direct #4 win, bounded so STT never starves
  the rest of ZENO.
- `beam_size` now `ZENO_FASTER_WHISPER_BEAM` (default 1, kept fast).

### #2 Voice activity detection (neural)
`reyes_agent/wake/silero_vad.py` (new, additive)

- `SileroVAD` with the **same `voiced(pcm16) -> (bool, level)` interface as
  EnergyVAD**, buffering audio into silero's fixed 512-sample windows and
  returning a speech *probability* instead of raw loudness. This is the real
  #2 upgrade: EnergyVAD gates on loudness (any loud non-speech reads as voice —
  why its `minimum_rms` had to be 560); Silero scores *speech-likeness*.
- `make_vad()` factory: default = EnergyVAD (unchanged). `ZENO_VAD_BACKEND=silero`
  opts in *when available*, else transparently falls back to EnergyVAD — turning
  it on can never leave ZENO without a VAD. Needs `pip install silero-vad`.

Tests: `tests/test_voice_vad_stt.py` (9) — fallback, windowing, thread bounds,
default preserved. No real model is loaded in tests.

---

## RECOMMENDED (studied, deliberately not forced into hot paths)

### #3 Low-latency conversational streaming (from pipecat)
ZENO's turn end-of-speech already lives in `remote_mic/runtime.py` as a 0.55s
silence debounce — this is exactly pipecat's `stop_secs`. Pipecat's added value
is a **confidence-gated state machine**: `start_secs` (speech must persist to
*start* a turn, killing false starts) and `confidence` (min speech prob to count
a frame as voiced). The clean next step: drive that debounce from `SileroVAD`'s
probability (not energy), and expose `start_secs`/`stop_secs`/`confidence` as
config. Not done here because `remote_mic/runtime.py` is a live path and its
second VAD return value is an RMS magnitude, not a probability — swapping it in
needs a deliberate, separately-tested change, not a drive-by.

### #5 Dynamic mini-panel system (from react-grid-layout)
ZENO's panels are vanilla JS (`reyes_agent/static/mini.html`, `visual_config.js`),
not React, so the library can't be dropped in. The reusable *idea* is its
**compaction**: after any panel moves, sweep panels toward an edge and let the
`collision.ts` test resolve overlaps (`fastVerticalCompactor.ts` is the O(n) form).
Porting that ~40-line packing loop to ZENO's panel layout gives auto-tidy,
gap-free arrangement without adopting React.

### #6 Smooth panel animations (from motion) — extracted
Re-cloned `motion` (motiondivision/motion) and read the spring source
(`packages/motion-dom/src/animation/generators/spring.ts`). Exact
`springDefaults`:

    stiffness 100 · damping 10 · mass 1.0 · velocity 0
    duration 800ms · bounce 0.3 (dampingRatio = 1 - bounce = 0.7) · visualDuration 0.3s
    restSpeed 2 (0.01 granular) · restDelta 0.5 (0.005 granular)
    minDamping 0.05 · maxDamping 1 · maxDuration 10s

The library default (100/10/1) is deliberately *bouncy*; Framer Motion's
duration/bounce API (bounce 0.3 → dampingRatio 0.7) is the smoother preset UIs
usually want. Motion always animates `transform`/`opacity` (compositor-only),
never top/left/width — and stops on the rest thresholds above, not a fixed
duration.

**Integrated as an additive helper:** `reyes_agent/static/spring.js` reproduces
these exact constants and gives ZENO's panels a `springTo()` RAF animator
(semi-implicit Euler, the same physics params) plus CSS cubic-bezier presets
approximating the springs — opt-in, wiring nothing that already exists.
