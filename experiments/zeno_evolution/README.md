# ZENO evolution experiments

These experiments are intentionally dependency-free and were run against the
clean `fefc6eb` baseline before production integration.

## Measured baselines

| Experiment | Before | After | Interpretation |
|---|---:|---:|---|
| 32 simultaneous first OpenAI-client requests | 32 factories / 32 clients / 51.82 ms | 1 factory / 1 client / 36.99 ms | A lock removes duplicate SDK clients and their connection pools. |
| Ten simultaneous four-advisor Council calls | 37 provider worker threads / 183.31 ms | 4 shared provider workers / 530.61 ms | The global resource ceiling is now four; overload queues instead of multiplying network calls. |
| Private target probes | `172.16/12`, `100.64/10`, integer-loopback accepted | all rejected | Full resolved-address classification replaces prefix matching. |

The Council result deliberately trades burst latency for bounded resource use.
Normal one-meeting latency still runs four advisors concurrently. The stress
case no longer asks ZENO to make forty provider calls at once.

## Reproduction

The durable reproductions are in `tests/test_evolution_hardening.py`. They use
fake SDKs, deterministic DNS answers and fake HTTP responses; no provider key,
internet call or private target is required.

## Integration decision

Integrated: resolved-address SSRF checks, redirect refusal, exact response-size
cap, deterministic response/session cleanup, thread-safe provider singleton
initialization and one lazy bounded Council executor.

No third-party runtime dependency was added.
