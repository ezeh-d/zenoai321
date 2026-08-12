"""SimulStreaming decision: rejected from this CPU realtime path."""


def status() -> dict:
    return {"state": "REJECTED_REALTIME", "reason": "Upstream recommends a high-memory GPU for useful large-model realtime performance."}

