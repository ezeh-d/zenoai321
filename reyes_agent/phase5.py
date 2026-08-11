"""Phase 5 integration catalogue and truthful, on-demand health.

This module starts no service and imports no heavyweight model.  It records
the architectural decision for every repository in the Phase 5 brief and
asks the authoritative adapter for runtime truth only when ``status`` is
called.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Integration:
    key: str
    repository: str
    classification: str
    decision: str
    default_state: str = "DISABLED"


INTEGRATIONS: tuple[Integration, ...] = (
    Integration("zeroclaw", "zeroclaw-labs/zeroclaw", "ARCHITECTURAL_REFERENCE", "Reuse its service/SOP patterns through ZENO's kernel, missions and skills; never replace ZENO."),
    Integration("stagehand", "browserbase/stagehand", "OPTIONAL_PLUGIN", "Lazy adaptive browser adapter between Playwright and browser-use."),
    Integration("agent_vault", "Infisical/agent-vault", "LOCAL_SERVICE", "External credential proxy with strict egress; agents never receive raw credentials."),
    Integration("infisical", "Infisical/infisical", "REMOTE_SERVICE", "Optional production secret backend; Windows Credential Manager remains the local default."),
    Integration("aio_sandbox", "agent-infra/sandbox", "LOCAL_SERVICE", "Optional container sandbox behind ZENO's single sandbox interface."),
    Integration("tailscale", "tailscale/tailscale", "LOCAL_SERVICE", "Private device transport detected through the installed CLI.", "NOT_CONFIGURED"),
    Integration("headscale", "juanfont/headscale", "OPTIONAL_PLUGIN", "Future self-hosted control plane only; not deployed on this Windows client."),
    Integration("ntfy", "binwiederhier/ntfy", "REMOTE_SERVICE", "Optional push provider; mutually exclusive with Gotify by default."),
    Integration("gotify", "gotify/server", "REMOTE_SERVICE", "Optional push provider; mutually exclusive with ntfy by default."),
    Integration("rustdesk", "rustdesk/rustdesk", "OPTIONAL_PLUGIN", "Owner-authorized manual administration only; never an agent automation backend."),
    Integration("sensevoice", "QwenAudio/SenseVoice", "OPTIONAL_PLUGIN", "Lazy weak-signal audio understanding; no psychological diagnosis."),
    Integration("kokoro", "hexgrad/kokoro", "OPTIONAL_PLUGIN", "Preferred local TTS fallback when installed and benchmarked."),
    Integration("piper", "OHF-Voice/piper1-gpl", "OPTIONAL_PLUGIN", "Emergency local TTS only; GPL-3.0 distribution review required."),
    Integration("openvino", "openvinotoolkit/openvino", "OPTIONAL_PLUGIN", "Enable only after a real model benchmark beats ONNX CPU on this Intel host."),
    Integration("onnxruntime", "microsoft/onnxruntime", "DIRECT_DEPENDENCY", "Shared lazy inference sessions instead of one session per subsystem."),
    Integration("sqlite_vec", "asg017/sqlite-vec", "DIRECT_DEPENDENCY", "Pre-v1 adapter for small portable semantic indexes."),
    Integration("duckdb", "duckdb/duckdb", "DIRECT_DEPENDENCY", "Read-only local structured-data analysis with calculated evidence."),
    Integration("wasmtime", "bytecodealliance/wasmtime", "OPTIONAL_PLUGIN", "Future capability-scoped untrusted skill runtime."),
    Integration("ovos", "OpenVoiceOS/ovos-core", "ARCHITECTURAL_REFERENCE", "Reuse skill/fallback concepts; do not replace ZENO voice or LiveKit."),
    Integration("moshi", "kyutai-labs/moshi", "REJECTED", "Full-duplex architecture reference only; mandatory model/runtime is too heavy for this machine.", "DISABLED"),
)


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _simple(key: str) -> dict[str, Any]:
    packages = {
        "onnxruntime": "onnxruntime", "sqlite_vec": "sqlite_vec", "duckdb": "duckdb",
        "sensevoice": "funasr", "kokoro": "kokoro", "openvino": "openvino",
        "wasmtime": "wasmtime",
    }
    binaries = {"rustdesk": "rustdesk", "piper": "piper", "agent_vault": "agent-vault", "infisical": "infisical"}
    if key in packages:
        present = importlib.util.find_spec(packages[key]) is not None
        return {"state": "WORKING" if present else "DISABLED", "available": present,
                "detail": f"{packages[key]} {'installed' if present else 'not installed'}"}
    if key in binaries:
        path = shutil.which(binaries[key])
        return {"state": "STANDBY" if path else "NOT_CONFIGURED", "available": bool(path),
                "detail": path or f"{binaries[key]} not installed"}
    if key == "stagehand":
        configured = bool(os.environ.get("ZENO_STAGEHAND_URL", "").strip())
        return {"state": "STANDBY" if configured else "NOT_CONFIGURED", "available": configured,
                "detail": "endpoint configured" if configured else "ZENO_STAGEHAND_URL not configured"}
    if key == "aio_sandbox":
        ready = bool(shutil.which("docker")) and _flag("ZENO_AIO_SANDBOX_ENABLED")
        return {"state": "STANDBY" if ready else "NOT_CONFIGURED", "available": ready,
                "detail": "Docker adapter enabled" if ready else "Docker/AIO Sandbox not configured"}
    if key in {"ntfy", "gotify"}:
        provider = os.environ.get("ZENO_PUSH_PROVIDER", "").strip().casefold()
        configured = provider == key and bool(os.environ.get(f"ZENO_{key.upper()}_URL", "").strip())
        return {"state": "STANDBY" if configured else "NOT_CONFIGURED", "available": configured,
                "detail": f"{key} {'configured' if configured else 'not configured'}"}
    if key == "headscale":
        configured = bool(os.environ.get("ZENO_HEADSCALE_URL", "").strip())
        return {"state": "STANDBY" if configured else "DISABLED", "available": configured,
                "detail": "self-hosted control plane configured" if configured else "managed Tailscale mode selected"}
    return {"state": "DISABLED", "available": False, "detail": "architectural decision only"}


def status() -> dict[str, Any]:
    rows = []
    for spec in INTEGRATIONS:
        if spec.key == "tailscale":
            try:
                from reyes_agent.network.private import status as runtime_status
                runtime = runtime_status()
            except Exception as exc:  # adapter diagnostics must not break health
                runtime = {"state": "DEGRADED", "available": False, "detail": type(exc).__name__}
        else:
            runtime = _simple(spec.key)
        rows.append({**asdict(spec), **runtime})
    return {
        "state": "WORKING",
        "polling": False,
        "working": sum(1 for row in rows if row["state"] in {"WORKING", "ONLINE"}),
        "total": len(rows),
        "integrations": rows,
    }


def catalogue() -> dict[str, Integration]:
    return {item.key: item for item in INTEGRATIONS}
