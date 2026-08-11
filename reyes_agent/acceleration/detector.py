"""Measured host and inference-provider availability; no model is loaded."""
from __future__ import annotations

import importlib.util
import platform
import subprocess
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def hardware() -> dict[str, Any]:
    cpu = platform.processor() or platform.machine()
    gpus: list[str] = []
    try:
        command = ["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, shell=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode == 0:
            gpus = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    intel = "intel" in cpu.casefold() or any("intel" in gpu.casefold() for gpu in gpus)
    return {"cpu": cpu, "gpus": gpus, "intel_hardware": intel,
            "npu_detected": any("npu" in gpu.casefold() for gpu in gpus)}


def status() -> dict[str, Any]:
    installed = importlib.util.find_spec("onnxruntime") is not None
    providers: list[str] = []
    version = ""
    if installed:
        import onnxruntime
        providers = list(onnxruntime.get_available_providers())
        version = onnxruntime.__version__
    openvino = importlib.util.find_spec("openvino") is not None or "OpenVINOExecutionProvider" in providers
    return {"state": "WORKING" if installed else "NOT_CONFIGURED", "onnxruntime": installed,
            "onnxruntime_version": version, "execution_providers": providers,
            "openvino": "STANDBY" if openvino else "NOT_CONFIGURED",
            "hardware": hardware(), "enabled_backend": "onnxruntime-cpu" if installed else None,
            "openvino_enabled": False,
            "reason": "OpenVINO requires a model-specific benchmark before enablement"}
