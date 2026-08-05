"""Offline Phase 21 soak harness.

Examples:

    python tests/stress_phase21.py --profile smoke
    python tests/stress_phase21.py --profile 8h
    python tests/stress_phase21.py --profile 24h

The long profiles are release-gate commands, not part of the normal test run.
They exercise the managed runtime without calling a model provider, Gmail,
Playwright, or any external service. Browser automation is intentionally
reported as a separate integration gate because a reliable browser stress run
requires a controlled target site and installed Playwright browser binaries.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil

from reyes_agent import event_bus, memory_manager
from reyes_agent.scheduler import BackgroundScheduler
from reyes_agent.worker_pool import PRIORITY_BACKGROUND, PRIORITY_MISSION, ManagedWorkerPool


PROFILES = {"smoke": 20.0, "8h": 8 * 3600.0, "24h": 24 * 3600.0}


def run(duration: float, missions: int, events: int) -> int:
    process = psutil.Process()
    initial_rss = process.memory_info().rss
    pool = ManagedWorkerPool(max_workers=4, max_queue=256, thread_name_prefix="phase21-soak")
    scheduler = BackgroundScheduler()
    import reyes_agent.scheduler as scheduler_module

    original_pool = scheduler_module.get_worker_pool
    scheduler_module.get_worker_pool = lambda: pool
    original_db = event_bus._DB_PATH
    original_archive = memory_manager._ARCHIVE_PATH
    completed = 0
    completed_lock = threading.Lock()
    history: list[dict] = []
    tick_count = 0
    tick_lock = threading.Lock()

    def mission(index: int) -> None:
        nonlocal completed
        # Simulates finite mission work without external side effects.
        time.sleep(0.002)
        with completed_lock:
            completed += 1

    def tick() -> None:
        nonlocal tick_count
        with tick_lock:
            tick_count += 1

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_bus._DB_PATH = Path(temp_dir) / "state.db"
            memory_manager._ARCHIVE_PATH = Path(temp_dir) / "conversation_archive.jsonl"
            for index in range(events):
                event_bus.publish("stress.event", {"index": index}, source="phase21-soak")
            handles = [
                pool.submit(mission, index, name=f"mission:{index}", priority=PRIORITY_MISSION)
                for index in range(missions)
            ]
            scheduler.schedule("soak-tick", tick, interval=0.1, priority=PRIORITY_BACKGROUND)
            for index in range(max(160, missions * 2)):
                history.append({"role": "user" if index % 2 == 0 else "assistant", "content": f"turn {index}"})
                memory_manager.trim_history(history, max_messages=60)

            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                if any(not thread.is_alive() for thread in pool._threads):
                    raise RuntimeError("A managed worker died during the soak.")
                time.sleep(0.25)
            for handle in handles:
                handle.result(10)
            assert event_bus.flush(10), "event persistence queue did not drain"

            final_rss = process.memory_info().rss
            metrics = pool.metrics()
            print(f"duration_s={duration:.1f}")
            print(f"missions_completed={completed}/{missions}")
            print(f"events_published={event_bus.runtime_stats()['published_total_process']}")
            print(f"scheduler_ticks={tick_count}")
            print(f"active_history={len(history)}")
            print(f"rss_growth_mb={(final_rss - initial_rss) / 1024 / 1024:.2f}")
            print(f"workers_alive={metrics['workers_alive']}/{metrics['workers']}")
            print("browser_integration=skipped (requires a controlled Playwright target; run separately)")
            assert completed == missions
            assert len(history) <= 60
            assert metrics["workers_alive"] == metrics["workers"]
            assert tick_count >= max(1, int(duration / 0.2))
    finally:
        event_bus._DB_PATH = original_db
        memory_manager._ARCHIVE_PATH = original_archive
        scheduler_module.get_worker_pool = original_pool
        scheduler.shutdown()
        pool.shutdown()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline Phase 21 stability soak.")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument("--duration", type=float, help="Override profile duration in seconds.")
    parser.add_argument("--missions", type=int, default=100)
    parser.add_argument("--events", type=int, default=1000)
    args = parser.parse_args()
    return run(args.duration if args.duration is not None else PROFILES[args.profile], args.missions, args.events)


if __name__ == "__main__":
    raise SystemExit(main())
