# ZENO Routing Baseline — 2026-09-02

## Scope

This is an in-process capability-routing measurement, not an end-to-end ZENO
turn. It excludes process startup, network, LLM/provider, speech recognition,
speech synthesis, microphone, speaker, browser, panel, and rendering time.

## Proven bottleneck

Before the routing change, an ordinary greeting had no deterministic capability
match and therefore initialized the optional sentence-transformer semantic
router. A fresh-process, 500-call measurement produced:

| Case | p50 | p90 | p95 | p99 | Maximum | Tools exposed |
|---|---:|---:|---:|---:|---:|---:|
| `Hello ZENO, how are you?` | 26.5838 ms | 42.2232 ms | 51.7992 ms | 85.9657 ms | 64,891.2985 ms | 2 |

The maximum includes the one-time optional-model load. This was a real
conversation-path regression, not normal per-turn latency after the model was
warm.

## Deterministic command reference values

The same pre-change investigation recorded these warm routing p95 values:

| Case | p95 |
|---|---:|
| `What time is it?` | 0.5302 ms |
| `Open Chrome` | 0.4071 ms |
| `Search YouTube for football highlights` | 0.9285 ms |
| `Remember that blue is my test colour` | 0.5994 ms |
| `Look at my screen` | 0.4566 ms |
| `Fix this Python traceback` | 0.5114 ms |

These measurements established that the slow path was the fallback model load,
not the deterministic capability rules. No live local server, voice device,
provider, panel, browser, or full-app startup timing was available during this
baseline.
