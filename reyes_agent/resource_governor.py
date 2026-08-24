"""Measured performance profiles layered over admission and idle cleanup."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

ECO, BALANCED, PERFORMANCE, MAX = "ECO", "BALANCED", "PERFORMANCE", "MAX"
_PROFILES = {
    ECO: {"heavy_model": 1, "vision": 1, "browser": 1, "background": 1, "indexing": 1},
    BALANCED: {"heavy_model": 2, "vision": 1, "browser": 2, "background": 3, "indexing": 1},
    PERFORMANCE: {"heavy_model": 2, "vision": 1, "browser": 3, "background": 4, "indexing": 2},
    MAX: {"heavy_model": 3, "vision": 2, "browser": 4, "background": 6, "indexing": 2},
}


@dataclass
class ResourceSnapshot:
    timestamp: float
    cpu_percent: float | None
    ram_percent: float | None
    available_ram_mb: float | None
    disk_percent: float | None
    battery_percent: float | None
    on_battery: bool | None
    thread_count: int
    pressure: str
    network_sent_mb: float | None = None
    network_received_mb: float | None = None
    gpu_percent: float | None = None
    vram_percent: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class ResourceMonitor:
    def sample(self) -> ResourceSnapshot:
        cpu = ram = available = disk = battery = on_battery = None
        net_sent = net_received = gpu = vram = None
        try:
            import psutil
            cpu = float(psutil.cpu_percent(interval=None))
            memory = psutil.virtual_memory()
            ram, available = float(memory.percent), round(memory.available / 1048576, 1)
            disk = float(psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").percent)
            b = psutil.sensors_battery()
            if b is not None:
                battery, on_battery = float(b.percent), not bool(b.power_plugged)
            net = psutil.net_io_counters()
            net_sent, net_received = round(net.bytes_sent / 1048576, 2), round(net.bytes_recv / 1048576, 2)
        except Exception:
            pass
        high = (cpu is not None and cpu >= 90) or (ram is not None and ram >= 90)
        critical = (ram is not None and ram >= 96) or (available is not None and available < 300)
        pressure = "CRITICAL" if critical else "HIGH" if high else "NORMAL"
        return ResourceSnapshot(time.time(), cpu, ram, available, disk, battery,
                                on_battery, _thread_count(), pressure,
                                net_sent, net_received, gpu, vram)


def _thread_count() -> int:
    try:
        import psutil
        return int(psutil.Process().num_threads())
    except Exception:
        import threading
        return threading.active_count()


class WorkloadScheduler:
    """Compatibility facade: admission remains the sole concurrency owner."""

    def admit(self, resource_class: str):
        from reyes_agent.admission import get_admission
        return get_admission().admit(resource_class)


class ResourceGovernor:
    def __init__(self, profile: str = BALANCED) -> None:
        self.monitor = ResourceMonitor()
        self.profile = BALANCED
        self.set_profile(profile)

    def set_profile(self, profile: str) -> str:
        chosen = str(profile).upper()
        if chosen not in _PROFILES:
            raise ValueError(f"unknown performance profile {profile!r}")
        from reyes_agent.admission import get_admission
        for resource, limit in _PROFILES[chosen].items():
            get_admission().configure(resource, limit)
        self.profile = chosen
        return chosen

    def evaluate(self) -> dict[str, Any]:
        sample = self.monitor.sample()
        actions: list[str] = []
        if sample.pressure in {"HIGH", "CRITICAL"}:
            actions.extend(["pause_indexing", "sleep_idle_agents", "reduce_nonessential_visuals"])
        if sample.pressure == "CRITICAL":
            actions.extend(["unload_idle_models", "reject_new_heavy_work"])
            try:
                from reyes_agent.resource_manager import sweep
                sweep()
            except Exception:
                pass
        return {"profile": self.profile, "resources": sample.as_dict(),
                "recommended_actions": actions,
                "interaction_core_reserved": ["voice", "stop", "vad", "turn_detection", "interactive"]}


_governor: ResourceGovernor | None = None


def get_resource_governor() -> ResourceGovernor:
    global _governor
    if _governor is None:
        _governor = ResourceGovernor(os.environ.get("ZENO_PERFORMANCE_PROFILE", BALANCED))
    return _governor
