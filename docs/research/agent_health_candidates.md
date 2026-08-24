# Agent health and computer-use evaluation candidates

- [OpenSearch Agent Health](https://github.com/opensearch-project/agent-health):
  selected as a design reference for trajectory records, golden paths, pass
  rates, latency/cost and tool-use analysis. Its full OpenSearch/collector stack
  is rejected for always-on deployment on this constrained laptop.
- [OSWorld](https://github.com/xlang-ai/OSWorld): useful real-computer benchmark
  reference, but production ZENO must not be redesigned around a benchmark VM.
- [OSWorld V2](https://github.com/xlang-ai/OSWorld-V2): current long-horizon
  benchmark with pinned code/task/assets/image releases. It requires a dedicated
  VM/image and gated task assets, so it was not run against the owner's desktop.

Chosen: ZENO's golden corpus covers its own high-value flows: phone-to-laptop,
auth/device diagnosis, independent action verification, emergency cancellation,
idempotent side effects and restart state. Quality scoring consumes only real
test/telemetry samples and leaves unmeasured dimensions unknown.
