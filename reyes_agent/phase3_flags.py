"""Feature flags and integration metadata for ZENO Phase 3.

Heavy or externally connected capabilities default off.  This module performs
no imports of optional SDKs and starts no services; it is safe on the startup
path and is the single source used by diagnostics, the service catalogue and
tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Integration:
    key: str
    label: str
    flag: str
    classification: str
    strategy: str
    heavy: bool = True
    default: bool = False

    @property
    def enabled(self) -> bool:
        return flag(self.flag, self.default)


# A direct, auditable answer to the prompt's A-F integration decision.  "F"
# here means an existing ZENO authority is stronger/safer than adding a second
# runtime, not that the requested capability disappears.
INTEGRATIONS: tuple[Integration, ...] = (
    Integration("litellm", "Unified model gateway", "ZENO_LITELLM_ENABLED", "F", "reuse ZENO's equivalent measured provider seam; do not create a second LiteLLM client", False, True),
    Integration("screenpipe", "Screenpipe episodic memory", "ZENO_SCREENPIPE_ENABLED", "B", "optional local service API"),
    Integration("openadapt", "Learn by demonstration", "ZENO_OPENADAPT_ENABLED", "F", "reuse verified ZENO workflow engine", False, True),
    Integration("graphiti", "Temporal knowledge graph", "ZENO_GRAPHITI_ENABLED", "D", "optional adapter over bounded local graph"),
    Integration("sherpa", "Sherpa local audio", "ZENO_SHERPA_ENABLED", "D", "optional local audio backend"),
    Integration("docling", "Docling documents", "ZENO_DOCLING_ENABLED", "D", "lazy document parser with existing OCR fallback"),
    Integration("openhands", "OpenHands engineering", "ZENO_OPENHANDS_ENABLED", "B", "external engineering backend"),
    Integration("agent_device", "Agent-device mobile", "ZENO_AGENT_DEVICE_ENABLED", "D", "paired optional device adapter"),
    Integration("scrcpy", "scrcpy Android bridge", "ZENO_SCRCPY_ENABLED", "B", "controlled installed binary"),
    Integration("kde_connect", "KDE Connect bridge", "ZENO_KDE_CONNECT_ENABLED", "B", "optional paired external service"),
    Integration("home_assistant", "Home Assistant", "ZENO_HOME_ASSISTANT_ENABLED", "C", "authenticated API/MCP integration"),
    Integration("local_llm", "Ollama/llama.cpp", "ZENO_LOCAL_LLM_ENABLED", "B", "lazy local model server"),
    Integration("whisper_cpp", "whisper.cpp STT", "ZENO_WHISPER_CPP_ENABLED", "B", "lazy installed binary fallback"),
    Integration("silero_vad", "Silero VAD", "ZENO_SILERO_VAD_ENABLED", "D", "optional backend under the one microphone owner"),
    Integration("e2b", "E2B sandbox", "ZENO_E2B_ENABLED", "B", "optional remote sandbox; no implicit secrets/files"),
    Integration("langfuse", "Langfuse tracing", "ZENO_LANGFUSE_ENABLED", "D", "optional exporter behind local tracer"),
    Integration("phoenix", "Phoenix tracing", "ZENO_PHOENIX_ENABLED", "D", "alternative exporter, never dual by default"),
    Integration("activitywatch", "ActivityWatch context", "ZENO_ACTIVITYWATCH_ENABLED", "B", "optional light local service"),
    Integration("scheduler", "Proactive scheduler", "ZENO_SCHEDULER_ENABLED", "F", "reuse ZENO single bounded scheduler", False, True),
    Integration("promptfoo", "AI regression datasets", "ZENO_PROMPTFOO_TESTS_ENABLED", "E", "portable local contract tests; Promptfoo optional", False, True),
    Integration("pywinauto", "Windows UI Automation", "ZENO_PYWINAUTO_ENABLED", "D", "optional fast path after native APIs"),
    Integration("opa", "Open Policy Agent", "ZENO_OPA_ENABLED", "D", "optional evaluator behind ZENO permission constitution"),
    Integration("n8n", "n8n workflows", "ZENO_N8N_ENABLED", "B", "authenticated optional external workflow API"),
    Integration("cross_device", "Cross-device notifications", "ZENO_CROSS_DEVICE_ENABLED", "D", "reuse paired notification bridge"),
    Integration("digital_dna", "Behavioral learning", "ZENO_DIGITAL_DNA_ENABLED", "F", "reuse opt-out ZENO Digital DNA with confirmed-preference boundary", False, True),
)


def catalogue() -> dict[str, Integration]:
    return {item.key: item for item in INTEGRATIONS}
