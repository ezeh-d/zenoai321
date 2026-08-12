"""Select exactly one turn detector and publish its real decision."""

from __future__ import annotations

import os
import time

from reyes_agent.voice.turn.heuristic import FINISHED, UNFINISHED, WAIT
from reyes_agent.voice.turn.heuristic import detect as heuristic_detect


def detect(text: str) -> dict:
    started = time.perf_counter()
    # TEN's available detector is 7B and remains disabled on this 8 GB,
    # dual-core Windows host. The flag is reported but never silently loads it.
    ten_requested = os.environ.get("ZENO_TEN_TURN_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
    result = heuristic_detect(text)
    result["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    result["ten_requested_but_unavailable"] = ten_requested
    try:
        from reyes_agent import event_bus

        event_bus.publish("voice.turn_boundary", {**result, "text_length": len(str(text or ""))}, source="turn_detector")
    except Exception:
        pass
    return result


def status() -> dict:
    return {
        "state": "READY",
        "primary": "heuristic-v1",
        "states": [FINISHED, UNFINISHED, WAIT],
        "runs": "only after stable STT at a VAD boundary",
        "ten_turn": "REJECTED_REALTIME_7B_MODEL",
    }

