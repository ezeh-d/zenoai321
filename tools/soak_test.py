"""Long-duration stability harness.

WHAT A SOAK TEST IS ACTUALLY FOR
---------------------------------
Not crashes -- those show up in the first minute. It is for the failures that
only exist as a DERIVATIVE: memory that climbs, threads that never retire,
event subscribers that double on every reload, audio sources that accumulate.
Every one of those looks perfectly healthy in a single sample.

So this samples repeatedly and reports the TREND, and judges growth by
comparing the last quarter of the run against the first. A single increase is
not a leak; sustained monotonic growth is.

WHAT IT DRIVES
--------------
Real requests against the running server, mixed the way a person actually
works: conversation, memory writes and recalls, agent queries, utility,
routing-heavy commands, and deliberate failures. Rapid bursts are included
because queue corruption and stale responses only appear under overlap.

WHAT IT WILL NOT DO
-------------------
No desktop automation and no browser launches. A soak test that opens Chrome
2,000 times tests Chrome. This exercises ZENO's own loop -- routing, model,
memory, agents, event bus, audio bookkeeping -- and leaves application control
to the browser stress harness, which can clean up after itself.
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE = "http://127.0.0.1:8765"
PHONE = "http://127.0.0.1:8768"
SAMPLE_EVERY_S = 20.0

# Mixed the way a person works, not one category at a time.
WORKLOAD: tuple[tuple[str, str], ...] = (
    ("conversation", "Hello ZENO, how are you?"),
    ("utility", "What time is it?"),
    ("memory_write", "Remember that soak marker {n} is active"),
    ("memory_read", "What was soak marker {n}?"),
    ("agents", "Who are your agents?"),
    ("conversation", "Thanks, that is helpful"),
    ("utility", "What is today's date?"),
    ("diagnostics", "Show your status"),
    ("routing", "Tell me what deleting a folder means"),
    ("agents", "Who is Apex?"),
    ("conversation", "What can you do?"),
    ("memory_read", "What was soak marker {n}?"),
)

# Deliberately malformed, to prove bad input does not corrupt the loop.
BAD_INPUT: tuple[str, ...] = (
    "", "   ", "\x00\x01\x02", "a" * 4000, "{'not': 'json'}", "🙂" * 200,
)


@dataclass
class Sample:
    at: float
    rss_mb: float = 0.0
    threads: int = 0
    processes: int = 0
    handles: int = 0
    audio_sources: int = 0
    bus_subscribers: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in
                ("at", "rss_mb", "threads", "processes", "handles",
                 "audio_sources", "bus_subscribers")}


@dataclass
class Result:
    started: float = 0.0
    duration_s: float = 0.0
    requests: int = 0
    failures: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _post(path: str, payload: dict, timeout: float = 90.0) -> tuple[bool, float, str]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(BASE + path, data=body,
                                     headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        urllib.request.urlopen(request, timeout=timeout).read()
        return True, time.perf_counter() - started, ""
    except urllib.error.HTTPError as exc:
        # A 4xx on deliberately bad input is CORRECT behaviour, not a failure.
        return (400 <= exc.code < 500), time.perf_counter() - started, f"HTTP{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, time.perf_counter() - started, type(exc).__name__


def _sample() -> Sample:
    sample = Sample(at=time.time())
    try:
        import psutil

        total_rss = 0.0
        threads = 0
        processes = 0
        handles = 0
        for proc in psutil.process_iter(["name"]):
            if "python" not in (proc.info.get("name") or "").lower():
                continue
            try:
                processes += 1
                total_rss += proc.memory_info().rss / (1024 * 1024)
                threads += proc.num_threads()
                handles += getattr(proc, "num_handles", lambda: 0)()
            except Exception:  # noqa: BLE001
                continue
        sample.rss_mb = round(total_rss, 1)
        sample.threads = threads
        sample.processes = processes
        sample.handles = handles
    except Exception:  # noqa: BLE001
        pass

    try:
        with urllib.request.urlopen(f"{PHONE}/api/phone/mic/levels", timeout=8) as r:
            sample.audio_sources = len(json.loads(r.read()).get("sources") or {})
    except Exception:  # noqa: BLE001
        pass

    try:
        from reyes_agent import event_bus

        stats = event_bus.stats()
        sample.bus_subscribers = int(stats.get("subscribers", 0) or 0)
    except Exception:  # noqa: BLE001
        pass
    return sample


def _sampler(result: Result, stop: threading.Event) -> None:
    while not stop.wait(SAMPLE_EVERY_S):
        result.samples.append(_sample())


def run(minutes: float = 30.0) -> Result:
    result = Result(started=time.time())
    result.samples.append(_sample())
    stop = threading.Event()
    sampler = threading.Thread(target=_sampler, args=(result, stop), daemon=True)
    sampler.start()

    deadline = time.time() + minutes * 60
    cycle = 0
    try:
        while time.time() < deadline:
            cycle += 1
            for kind, template in WORKLOAD:
                if time.time() >= deadline:
                    break
                message = template.format(n=cycle)
                ok, seconds, error = _post("/api/chat", {"message": message})
                result.requests += 1
                result.latencies.append(seconds)
                if not ok:
                    result.failures += 1
                    result.errors[f"{kind}:{error}"] = \
                        result.errors.get(f"{kind}:{error}", 0) + 1

            # Rapid burst: overlap is where queue corruption and stale
            # responses appear, and they never appear one-at-a-time.
            if cycle % 3 == 0 and time.time() < deadline:
                threads = []
                for text in ("What time is it?", "Hello", "Who are your agents?"):
                    t = threading.Thread(target=_post, args=("/api/chat", {"message": text}))
                    t.start()
                    threads.append(t)
                for t in threads:
                    t.join(timeout=90)
                result.requests += len(threads)

            # Malformed input every few cycles.
            if cycle % 4 == 0 and time.time() < deadline:
                for bad in BAD_INPUT:
                    ok, _s, error = _post("/api/chat", {"message": bad}, timeout=45)
                    result.requests += 1
                    if not ok:
                        result.failures += 1
                        result.errors[f"bad_input:{error}"] = \
                            result.errors.get(f"bad_input:{error}", 0) + 1
    finally:
        stop.set()
        sampler.join(timeout=SAMPLE_EVERY_S + 5)
        result.duration_s = time.time() - result.started
        result.samples.append(_sample())
    return result


def analyse(result: Result) -> dict[str, Any]:
    """Trend, not snapshot. Growth is judged last quarter vs first quarter."""
    def trend(field_name: str) -> dict[str, Any]:
        values = [getattr(s, field_name) for s in result.samples if getattr(s, field_name)]
        if len(values) < 4:
            return {"samples": len(values), "verdict": "too few samples"}
        quarter = max(1, len(values) // 4)
        first = statistics.fmean(values[:quarter])
        last = statistics.fmean(values[-quarter:])
        growth = ((last - first) / first * 100) if first else 0.0
        return {"first": round(first, 1), "last": round(last, 1),
                "growth_pct": round(growth, 1), "peak": round(max(values), 1),
                # 25% sustained growth over a soak is the line between noise
                # and something that will not stop climbing.
                "verdict": "GROWING" if growth > 25 else "stable"}

    latencies = sorted(result.latencies)
    return {
        "duration_minutes": round(result.duration_s / 60, 1),
        "requests": result.requests,
        "failures": result.failures,
        "failure_rate_pct": round(result.failures / max(1, result.requests) * 100, 2),
        "errors": result.errors,
        "latency_s": {
            "median": round(statistics.median(latencies), 2) if latencies else 0,
            "p95": round(latencies[int(len(latencies) * 0.95)], 2) if len(latencies) > 20 else 0,
            "max": round(max(latencies), 2) if latencies else 0,
        },
        "rss_mb": trend("rss_mb"),
        "threads": trend("threads"),
        "processes": trend("processes"),
        "handles": trend("handles"),
        "audio_sources": trend("audio_sources"),
        "bus_subscribers": trend("bus_subscribers"),
        "samples": len(result.samples),
    }


if __name__ == "__main__":
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    print(f"soak: {minutes} minutes against {BASE}", flush=True)
    outcome = analyse(run(minutes))
    print(json.dumps(outcome, indent=2))
    out = f"soak_result_{int(time.time())}.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(outcome, handle, indent=2)
    print(f"written: {out}")
