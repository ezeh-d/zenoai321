# Observability candidates

## Evaluated

- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/): stable
  trace and metric APIs, Python 3.10+, vendor-neutral exporters. Selected as the
  semantic model.
- [OpenInference](https://github.com/Arize-ai/openinference): OpenTelemetry
  conventions/instrumentation for model, retrieval and tool calls. Compatible,
  but optional until ZENO needs SDK-specific automatic instrumentation.
- [Langfuse](https://langfuse.com/docs/observability/sdk/overview): current Python
  v4 tracing is OpenTelemetry-based and async. Useful for hosted/self-hosted LLM
  traces; not configured and never required for ZENO startup.
- [Arize Phoenix](https://arize.com/docs/phoenix/): strong local experiments,
  datasets and evaluation over OpenTelemetry/OpenInference. Good developer lab;
  too heavy to run permanently on the audited laptop.
- [Agent Health](https://github.com/opensearch-project/agent-health): trajectory,
  golden-path and coding-agent analytics. Its full OpenSearch/Docker deployment
  calls for roughly 4 GB allocated memory, so it is a benchmark/dev candidate,
  not an always-on dependency.

## Chosen design

ZENO emits bounded OpenTelemetry-style local spans with trace/span/parent IDs,
correlation fields and redaction. Completed spans enter the durable Event Bus.
Exactly one optional Langfuse *or* Phoenix exporter may be selected later.
