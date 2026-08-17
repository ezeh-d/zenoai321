"""Measure an already-running ZENO process without changing its state.

Examples:
    python scripts/validate_phase22_idle.py --duration 3600 --url http://127.0.0.1:8768
    python scripts/validate_phase22_idle.py --duration 60 --interval 5

The report is written only to the requested path (or stdout).  This script
never starts/stops ZENO and never scans unrelated application details.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

import psutil


def _get_json(url: str, timeout: float = 5.0) -> tuple[dict, float]:
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response), (time.perf_counter() - started) * 1000


def _sample_process(process: psutil.Process, url: str) -> dict:
    performance, request_ms = _get_json(url.rstrip("/") + "/api/performance")
    memory = process.memory_info()
    io = process.io_counters()
    virtual_memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "timestamp": time.time(), "rss_mb": memory.rss / 1024 / 1024,
        "cpu_percent": process.cpu_percent(interval=None),
        "system_cpu_percent": psutil.cpu_percent(interval=None),
        "system_ram_percent": virtual_memory.percent,
        "swap_used_mb": swap.used / 1024 / 1024,
        "threads": process.num_threads(), "handles": process.num_handles(),
        "read_bytes": io.read_bytes, "write_bytes": io.write_bytes,
        "request_ms": request_ms, "performance": performance,
    }


def run(url: str, duration: float, interval: float, warmup: float = 0.0) -> dict:
    initial, _ = _get_json(url.rstrip("/") + "/api/performance")
    pid = int(initial.get("pid") or 0)
    if not pid:
        # Older running builds did not expose pid; match the one listener's
        # RSS/thread telemetry to the current process through its endpoint.
        pid = next((p.pid for p in psutil.process_iter(["pid", "cmdline"])
                    if "reyes_agent.web" in " ".join(p.info.get("cmdline") or [])), 0)
    if not pid:
        raise RuntimeError("Could not identify the running ZENO backend.")
    process = psutil.Process(pid)
    process.cpu_percent(interval=None)
    cold = {
        "rss_mb": round(process.memory_info().rss / 1024 / 1024, 1),
        "threads": process.num_threads(),
        "handles": process.num_handles(),
    }
    if warmup > 0:
        time.sleep(warmup)
        # Prime the non-blocking CPU counter after the warm-up window; the
        # reported mean then describes only the steady-state interval.
        process.cpu_percent(interval=None)
    started = time.monotonic()
    samples: list[dict] = []
    while True:
        samples.append(_sample_process(process, url))
        elapsed = time.monotonic() - started
        if elapsed >= duration:
            break
        time.sleep(min(interval, max(0.0, duration - elapsed)))
    rss = [row["rss_mb"] for row in samples]
    cpus = [row["cpu_percent"] for row in samples[1:]] or [samples[0]["cpu_percent"]]
    system_cpus = [row["system_cpu_percent"] for row in samples[1:]] or [samples[0]["system_cpu_percent"]]
    system_ram = [row["system_ram_percent"] for row in samples]
    swap = [row["swap_used_mb"] for row in samples]
    threads = [row["threads"] for row in samples]
    handles = [row["handles"] for row in samples]
    requests = [row["request_ms"] for row in samples]
    first_perf = samples[0]["performance"]
    last_perf = samples[-1]["performance"]
    freeze_start = int(first_perf.get("freeze_count") or 0)
    freeze_end = int(last_perf.get("freeze_count") or 0)
    return {
        "url": url, "pid": pid, "warmup_s": round(warmup, 1),
        "cold_process": cold,
        "duration_s": round(time.monotonic() - started, 1),
        "sample_count": len(samples),
        "rss_mb": {"start": round(rss[0], 1), "end": round(rss[-1], 1),
                   "growth": round(rss[-1] - rss[0], 2), "max": round(max(rss), 1)},
        "cpu_percent": {"mean": round(statistics.fmean(cpus), 2), "max": round(max(cpus), 2)},
        "system_cpu_percent": {"mean": round(statistics.fmean(system_cpus), 2),
                               "max": round(max(system_cpus), 2)},
        "system_ram_percent": {"start": round(system_ram[0], 1),
                               "end": round(system_ram[-1], 1),
                               "max": round(max(system_ram), 1)},
        "swap_used_mb": {"start": round(swap[0], 1), "end": round(swap[-1], 1),
                         "growth": round(swap[-1] - swap[0], 1), "max": round(max(swap), 1)},
        "threads": {"start": threads[0], "end": threads[-1], "max": max(threads)},
        "handles": {"start": handles[0], "end": handles[-1], "max": max(handles)},
        "io_growth_bytes": {"read": samples[-1]["read_bytes"] - samples[0]["read_bytes"],
                            "write": samples[-1]["write_bytes"] - samples[0]["write_bytes"]},
        "performance_request_ms": {"mean": round(statistics.fmean(requests), 2),
                                   "max": round(max(requests), 2)},
        "worker_queue_depth": last_perf.get("workers", {}).get("queue_depth"),
        "event_queue_depth": last_perf.get("events", {}).get("persistence_queue_depth"),
        "freeze_count": {"start": freeze_start, "end": freeze_end,
                         "growth": max(0, freeze_end - freeze_start)},
        "memory_trend": last_perf.get("memory_trend", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8768")
    parser.add_argument("--duration", type=float, default=3600)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--warmup", type=float, default=0,
                        help="Wait before the measured interval so delayed Windows/ETW startup is excluded.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.url, max(1.0, args.duration), max(1.0, args.interval), max(0.0, args.warmup))
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
