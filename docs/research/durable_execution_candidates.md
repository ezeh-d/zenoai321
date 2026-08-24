# Durable execution candidates

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  provides checkpointed threads, human interrupts and fault-tolerant graph
  execution. It requires deterministic/idempotent handling of side effects.
- [Temporal Python SDK](https://github.com/temporalio/sdk-python) provides a
  distributed durable workflow service with deterministic workflows and
  activities for external I/O. It is excellent at larger operational scale but
  would add a service/worker architecture to a single-owner Windows assistant.

Chosen: retain ZENO's SQLite `missions/store.py` checkpointing for long jobs and
its normal worker pool for short actions. Add a general `SideEffectLedger` and
claim-before-execute contract before any resumable external action. Temporal or
LangGraph may later be an adapter for genuinely long, cross-device workflows;
Calculator, volume and standby never enter them.
