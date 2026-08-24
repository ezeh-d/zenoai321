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
import sys
import time
import urllib.request
from pathlib import Path

import psutil


def _get_json(url: str, timeout: float = 5.0) -> tuple[dict, float]:
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response), (time.perf_counter() - started) * 1000


def _command(process: psutil.Process) -> str:
    try:
        return " ".join(process.cmdline()).casefold()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return ""


def _is_zeno_root(process: psutil.Process) -> bool:
    command = _command(process)
    return any(marker in command for marker in (
        "reyes_agent.desktop_app", "reyes_agent.web", "zeno_desktop_bootstrap.py",
        "zeno_web_bootstrap.py", "zeno_anywhere_bootstrap.py", "uvicorn reyes_agent.web:app",
    ))


def _zeno_process_tree(backend: psutil.Process) -> list[psutil.Process]:
    """Return the owned ZENO tree, including WebView2 children, not grouped apps."""
    root = backend
    while True:
        try:
            parent = root.parent()
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            break
        if parent is None or not _is_zeno_root(parent):
            break
        root = parent
    processes = [root]
    try:
        processes.extend(root.children(recursive=True))
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        pass
    unique: dict[int, psutil.Process] = {}
    for item in processes:
        try:
            if item.is_running():
                unique[item.pid] = item
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return list(unique.values())


def _sample_group(backend: psutil.Process, tracked: dict[int, psutil.Process]) -> dict:
    processes = _zeno_process_tree(backend)
    rows: list[dict] = []
    for process in processes:
        try:
            item = tracked.setdefault(process.pid, process)
            name = item.name().casefold()
            command = _command(item)
            memory = item.memory_info().rss / 1024 / 1024
            cpu = item.cpu_percent(interval=None)
            rows.append({
                "pid": item.pid, "name": name, "command": command, "cpu": cpu,
                "rss_mb": memory, "threads": item.num_threads(),
                "handles": item.num_handles() if sys.platform == "win32" else 0,
                "webview2": name == "msedgewebview2.exe",
                "gpu": name == "msedgewebview2.exe" and "--type=gpu-process" in command,
            })
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    logical_cpus = max(1, psutil.cpu_count(logical=True) or 1)

    def total(key: str, predicate=lambda _row: True) -> float:
        return float(sum(row[key] for row in rows if predicate(row)))

    raw_cpu = total("cpu")
    webview_cpu = total("cpu", lambda row: row["webview2"])
    gpu_cpu = total("cpu", lambda row: row["gpu"])
    return {
        "processes": len(rows),
        "cpu_percent": round(raw_cpu / logical_cpus, 2),
        "cpu_percent_raw": round(raw_cpu, 2),
        "rss_mb": round(total("rss_mb"), 1),
        "threads": int(total("threads")),
        "handles": int(total("handles")),
        "webview2_cpu_percent": round(webview_cpu / logical_cpus, 2),
        "webview2_rss_mb": round(total("rss_mb", lambda row: row["webview2"]), 1),
        "webview2_gpu_cpu_percent": round(gpu_cpu / logical_cpus, 2),
        "webview2_gpu_rss_mb": round(total("rss_mb", lambda row: row["gpu"]), 1),
    }


def _sample_process(process: psutil.Process, url: str,
                    tracked: dict[int, psutil.Process]) -> dict:
    performance, request_ms = _get_json(url.rstrip("/") + "/api/performance")
    memory = process.memory_info()
    io = process.io_counters()
    virtual_memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    frontend = (performance.get("frontend_audits") or [{}])[-1]
    recent_freezes = performance.get("recent_freezes") or []
    last_freeze = recent_freezes[-1] if recent_freezes else {}
    freeze_delay = (float(last_freeze.get("duration_ms") or 0.0)
                    if time.time() - float(last_freeze.get("timestamp") or 0.0) <= 10.0 else 0.0)
    return {
        "timestamp": time.time(), "rss_mb": memory.rss / 1024 / 1024,
        "cpu_percent": process.cpu_percent(interval=None),
        "system_cpu_percent": psutil.cpu_percent(interval=None),
        "system_ram_percent": virtual_memory.percent,
        "swap_used_mb": swap.used / 1024 / 1024,
        "threads": process.num_threads(), "handles": process.num_handles(),
        "read_bytes": io.read_bytes, "write_bytes": io.write_bytes,
        "request_ms": request_ms, "performance": performance,
        "zeno_group": _sample_group(process, tracked),
        "ui_heartbeat_delay_ms": float(frontend.get("heartbeat_delay_ms") or freeze_delay),
        "frontend": {
            "avg_frame_ms": frontend.get("avg_frame_ms"),
            "worst_frame_ms": frontend.get("worst_frame_ms"),
            "messages_per_second": frontend.get("messages_per_second"),
            "active_animation_loops": frontend.get("active_animation_loops"),
            "active_timers": frontend.get("active_timers"),
        },
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
    tracked = {item.pid: item for item in _zeno_process_tree(process)}
    for item in tracked.values():
        try:
            item.cpu_percent(interval=None)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            pass
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
        samples.append(_sample_process(process, url, tracked))
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
    groups = [row["zeno_group"] for row in samples]
    heartbeats = [row["ui_heartbeat_delay_ms"] for row in samples]
    frontend_rows = [row["frontend"] for row in samples if row["frontend"].get("avg_frame_ms") is not None]
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
        "zeno_group": {
            "cpu_percent_mean": round(statistics.fmean(row["cpu_percent"] for row in groups), 2),
            "cpu_percent_max": round(max(row["cpu_percent"] for row in groups), 2),
            "rss_mb_start": groups[0]["rss_mb"], "rss_mb_end": groups[-1]["rss_mb"],
            "rss_mb_max": max(row["rss_mb"] for row in groups),
            "threads_start": groups[0]["threads"], "threads_end": groups[-1]["threads"],
            "threads_max": max(row["threads"] for row in groups),
            "handles_start": groups[0]["handles"], "handles_end": groups[-1]["handles"],
            "webview2_cpu_percent_mean": round(statistics.fmean(row["webview2_cpu_percent"] for row in groups), 2),
            "webview2_gpu_cpu_percent_mean": round(statistics.fmean(row["webview2_gpu_cpu_percent"] for row in groups), 2),
            "webview2_rss_mb_end": groups[-1]["webview2_rss_mb"],
            "webview2_gpu_rss_mb_end": groups[-1]["webview2_gpu_rss_mb"],
        },
        "ui_heartbeat_delay_ms": {"mean": round(statistics.fmean(heartbeats), 2),
                                  "max": round(max(heartbeats), 2)},
        "frontend": ({
            "samples": len(frontend_rows),
            "avg_frame_ms": round(statistics.fmean(float(row["avg_frame_ms"]) for row in frontend_rows), 2),
            "worst_frame_ms": round(max(float(row.get("worst_frame_ms") or 0) for row in frontend_rows), 2),
            "messages_per_second": round(statistics.fmean(float(row.get("messages_per_second") or 0) for row in frontend_rows), 2),
            "active_animation_loops": max(int(row.get("active_animation_loops") or 0) for row in frontend_rows),
            "active_timers": max(int(row.get("active_timers") or 0) for row in frontend_rows),
        } if frontend_rows else {"samples": 0, "status": "not measured; open the dashboard with ?audit=1"}),
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
