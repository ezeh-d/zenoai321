"""Universal Capability Library: every master-catalog area, one honest state.

The source catalog contains 148 capability/architecture sections and many
alternative providers.  Alternatives are discovery candidates, not permission
to install duplicate runtimes.  This module ships the complete section index
and a curated provider matrix whose state is derived locally without importing
heavy SDKs or contacting a service.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

INSTALLED = "INSTALLED"
AVAILABLE = "AVAILABLE"
EXPERIMENTAL = "EXPERIMENTAL"
NEEDS_LOGIN = "NEEDS_LOGIN"
NEEDS_DEVICE = "NEEDS_DEVICE"
DISABLED = "DISABLED"
BROKEN = "BROKEN"
UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
STATES = (INSTALLED, AVAILABLE, EXPERIMENTAL, NEEDS_LOGIN, NEEDS_DEVICE,
          DISABLED, BROKEN, UPDATE_AVAILABLE)


_SECTION_DATA = """
1|The Rule That Makes ZENO Everywhere Work
2|Core Architecture Before Adding Hundreds of Tools
3|Agent / Orchestration Frameworks
4|Multi-Device / AgentOS
5|Browser Automation
6|Windows Desktop Automation
7|Phone / Android / Device Control
8|Live Screen Streaming / Remote Companion
9|Speech Recognition / STT
10|Wake Word
11|Voice Activity Detection / Turn Detection
12|Text-To-Speech
13|Audio Processing
14|Computer Vision
15|OCR
16|Document Intelligence
17|PDF Tools
18|Word / DOCX
19|Excel / Spreadsheet
20|PowerPoint / Presentation
21|Email
22|Slack / Teams / Discord / Telegram / Messaging
23|Calendar / Scheduling
24|Contacts
25|Notifications
26|Web Research
27|RAG / Knowledge Retrieval
28|Vector Databases
29|Graph Databases / Knowledge Graph
30|Long-Term Agent Memory
31|Local Databases
32|Data Analysis
33|SQL / Database Tools
34|ETL / Pipelines
35|Queues / Background Jobs
36|Local LLM Inference
37|Embeddings
38|Model Routing
39|Code Intelligence
40|Git / GitHub
41|IDE Integration
42|Testing
43|Defensive Security
44|Secret Management
45|Authentication / Identity
46|API Layer
47|MCP - Model Context Protocol
48|A2A / Agent Interoperability
49|Plugin / Extension System
50|GitHub Capability Discovery Engine
51|Repository Scoring
52|Licensing
53|Sandboxing Unknown Tools
54|Package Management
55|Configuration
56|Observability
57|Logging
58|Health Monitoring
59|Circuit Breakers
60|Rate Limiting
61|Caching
62|Resource Management
63|File Search
64|Filesystem Operations
65|Archive / Compression
66|Media Processing
67|Image Creation / Editing Integrations
68|Video Generation / Editing
69|Graphic Design
70|Audio Recognition
71|Translation / Language
72|Search / Command Palette
73|Clipboard Intelligence
74|Screenshots / Screen Recording
75|Screen Understanding
76|Visual Change Detection
77|Workflow Recorder / Demonstration Learning
78|Procedural Memory / Skills
79|Sub-Agent System
80|Orb Presence
81|Council Mode
82|Voice Turn Manager
83|Conversation Core
84|Context Builder
85|Knowledge Freshness
86|T21 Business Knowledge
87|CRM
88|HR / Recruitment
89|Project Management
90|Notes / Knowledge Base
91|Cloud Storage
92|Cloud Infrastructure
93|Containers
94|Kubernetes
95|Deployment
96|CI/CD
97|Error Monitoring
98|Metrics
99|Tracing
100|Reliability Patterns
101|Tool Isolation
102|Versioned Tool Contracts
103|Dependency Pinning
104|Feature Flags
105|Canary Rollout
106|Shadow Mode
107|Benchmark Harness
108|Capability Gap Analysis
109|Tool Deduplication
110|Offline Mode
111|Network-Aware Routing
112|Cross-Device State Synchronization
113|WebSockets
114|HTTP / REST
115|WebRTC
116|Local Network Discovery
117|Remote Command Envelope
118|Remote Results
119|Offline Device Behavior
120|Privacy Controls
121|Audit History
122|Kill Switch
123|Resumable Tasks
124|Human-in-the-Loop
125|Task Priorities
126|Dream / Maintenance Mode
127|Self Diagnostics
128|Startup Doctor
129|Universal Capability Library UI
130|Suggested ZENO P0 Stack
131|Suggested ZENO P1 Providers
132|Suggested ZENO P2 Advanced Capabilities
133|Suggested ZENO P3 Experimental
134|Recommended Repository Evaluation Policy
135|Stability Requirements for Every Tool Adapter
136|Structured Error Types
137|Tool Selection Algorithm
138|Agent Tool Permissions
139|Dynamic Agent Orb Behavior
140|ZENO Everywhere Definition
141|GitHub / MCP Continuous Discovery
142|Research Sources Re-Checked for This Catalog
143|Important 2026 Notes
144|What NOT to Do
145|The Final ZENO Target
146|Implementation Sequence
147|Definition of Done
148|Final Instruction to Codex / Claude
""".strip()

SECTION_TITLES = {
    int(number): title for number, title in
    (line.split("|", 1) for line in _SECTION_DATA.splitlines())
}


@dataclass(frozen=True)
class CatalogSection:
    number: int
    title: str
    state: str
    evidence: str
    provider: str = "zeno-native"
    device: str = "zeno-core"
    permission: str = "read-only inventory"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# These are the only areas where an owner account/device or an explicitly
# disabled experimental provider is the missing piece. All other architecture
# areas have a native implementation or a documented governance contract in
# the current codebase; provider alternatives are listed separately below.
_NEEDS_LOGIN = {21, 24, 40, 91, 92, 96}
_NEEDS_DEVICE = set()
_EXPERIMENTAL = {3, 34, 48, 94, 99, 106, 132, 133, 141}
_AVAILABLE = {43, 52}

_EVIDENCE: dict[int, str] = {
    2: "Kernel, bounded workers, Event Bus, permissions, verification, recovery and diagnostics",
    4: "DeviceManager with Windows, Android and web-companion boundaries",
    5: "Playwright runtime with bounded navigation/action timeouts and verification",
    6: "native API -> UIA/pywinauto -> browser DOM -> vision/coordinates",
    7: "approved native Android overlay companion and DeviceLink action allowlist",
    8: "outbound authenticated WebRTC live desktop and ZENO Anywhere",
    9: "faster-whisper/cloud STT router with timeouts and local fallback",
    10: "single openWakeWord subsystem, cooldown and deterministic state machine",
    11: "shared VAD/noise/echo-aware audio pipeline",
    12: "ElevenLabs plus bounded local TTS fallbacks",
    15: "Windows OCR; no duplicate Tesseract process required",
    16: "lazy native PDF/DOCX/XLSX/PPTX readers; Docling remains optional",
    21: "email boundary exists; mailbox account is not owner-authorized",
    22: "shared messaging router with Slack/Telegram/Discord/WhatsApp adapters",
    23: "local scheduling and reminders are installed; cloud calendar is optional",
    24: "requires an owner-selected contact account/provider",
    27: "local RAG, knowledge loader and citation-aware retrieval",
    28: "sqlite-vec is the chosen local vector authority",
    29: "temporal local knowledge graph with contradiction history",
    30: "Living Memory authority with optional Mem0 backend",
    31: "SQLite and bounded DuckDB engines",
    34: "native jobs/workflows installed; Prefect/Temporal alternatives remain flags",
    35: "bounded priority worker pool and scheduler",
    36: "Ollama local models detected and lazy",
    38: "health-aware model router with circuit breakers/fallback",
    40: "Git is installed; GitHub write access requires owner credentials",
    43: "authorization-gated security toolkit exists; external scanners are candidates",
    44: "redaction and secret broker; credentials never enter catalog output",
    47: "official MCP SDK, allowlist, trust states, bounded stdio and health",
    48: "no external A2A process is enabled by default",
    49: "manifest permissions, trust review and explicit enable states",
    50: "capability acquisition and marketplace discovery without auto-install",
    53: "local restricted sandbox plus optional stronger AIO/E2B boundary",
    56: "local spans/metrics with optional OpenTelemetry flag",
    58: "central health snapshot and kernel diagnostics",
    63: "local typo-tolerant universal search plus optional Meilisearch",
    66: "ffmpeg-based bounded media processing",
    70: "modular audio fingerprint recognition with confidence",
    71: "language detection/translation plus verification",
    77: "demonstration capture, approved workflow storage and replay",
    79: "bounded dynamic agent runtime and role-scoped tools",
    80: "event-driven on-demand orb presence",
    82: "single VoiceTurnManager and shared AudioManager",
    87: "local paid-work/client/project records; external CRM is optional",
    91: "requires owner-selected cloud storage account",
    92: "local Docker is available; cloud accounts are not assumed",
    94: "Kubernetes provider remains optional and disabled",
    99: "local tracing installed; remote OpenTelemetry export is flagged off",
    104: "persisted feature flags with environment/default resolution",
    105: "deterministic canary rollout by stable task/device key",
    108: "detected capability inventory and gap/acquisition planner",
    109: "one authoritative execution registry; provider alternatives are candidates",
    129: "read-only catalog API/tool exposes all sections and providers",
    135: "ToolAdapter protocol enforced across every executable registered tool",
    136: "normalized failure categories and recovery hints",
    137: "health, permission, device, reputation, latency and privacy scoring",
    138: "specialist scopes enforced again at execution boundary",
    141: "discovery is explicit/scheduled; uncontrolled installation is prohibited",
    147: "covered by the maintained warning-strict regression suite",
    148: "selective adapters and stability-first policy enforced",
}


def _section_state(number: int) -> str:
    if number in _NEEDS_LOGIN:
        return NEEDS_LOGIN
    if number in _NEEDS_DEVICE:
        return NEEDS_DEVICE
    if number in _EXPERIMENTAL:
        return EXPERIMENTAL
    if number in _AVAILABLE:
        return AVAILABLE
    return INSTALLED


def sections() -> list[CatalogSection]:
    return [CatalogSection(
        number=number,
        title=SECTION_TITLES[number],
        state=_section_state(number),
        evidence=_EVIDENCE.get(number, "implemented by the current native ZENO architecture/policy"),
    ) for number in sorted(SECTION_TITLES)]


@dataclass(frozen=True)
class ProviderCandidate:
    name: str
    capability: str
    adapter: str = ""
    package: str = ""
    binary: str = ""
    environment: tuple[str, ...] = ()
    feature_flag: str = ""
    device: str = "zeno-core"
    selected: bool = False
    note: str = ""

    def state(self) -> tuple[str, str]:
        if self.feature_flag:
            from reyes_agent.feature_flags import is_enabled
            if not is_enabled(self.feature_flag):
                return EXPERIMENTAL, f"feature flag '{self.feature_flag}' is off"
        missing_env = [key for key in self.environment if not os.environ.get(key, "").strip()]
        if missing_env:
            return NEEDS_LOGIN, "needs owner configuration: " + ", ".join(missing_env)
        if self.package and not _has_package(self.package):
            return AVAILABLE, f"optional package '{self.package}' is not installed"
        if self.binary and not _has_binary(self.binary):
            return AVAILABLE, f"optional binary '{self.binary}' is not installed"
        if self.adapter:
            if not _module_available(self.adapter):
                return AVAILABLE, f"no ZENO adapter is installed at {self.adapter}"
        else:
            return AVAILABLE, "cataloged alternative; no ZENO adapter selected"
        return INSTALLED, self.note or ("selected provider" if self.selected else "lazy adapter available")

    def as_dict(self) -> dict[str, Any]:
        state, reason = self.state()
        return {**asdict(self), "environment": list(self.environment),
                "state": state, "reason": reason}


@lru_cache(maxsize=128)
def _has_package(name: str) -> bool:
    """Probe an optional SDK without importing the capability package.

    Importing ``reyes_agent.capabilities`` loads its planner/graph package and
    cost about two seconds on this machine.  A catalog view only needs a local
    presence check, so keep that cost off this read-only path.
    """
    try:
        return importlib.util.find_spec(str(name).split(".", 1)[0]) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


@lru_cache(maxsize=64)
def _has_binary(name: str) -> bool:
    return shutil.which(str(name or "").strip()) is not None


@lru_cache(maxsize=256)
def _module_available(name: str) -> bool:
    module = str(name or "").strip()
    if module.startswith("reyes_agent."):
        project_root = Path(__file__).resolve().parents[2]
        parts = module.split(".")
        candidate = project_root.joinpath(*parts)
        return candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file()
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


# Alternatives are all visible, but only the smallest strong provider set has
# an adapter. This is integration without dependency sprawl or fake readiness.
PROVIDERS: tuple[ProviderCandidate, ...] = (
    ProviderCandidate("ZENO native agents", "orchestration", "reyes_agent.agent_runtime", selected=True),
    ProviderCandidate("Microsoft Agent Framework", "orchestration", package="agent_framework", feature_flag="enable_agent_framework"),
    ProviderCandidate("LangGraph", "orchestration", package="langgraph", feature_flag="enable_langgraph"),
    ProviderCandidate("AutoGen", "orchestration", package="autogen", feature_flag="enable_autogen", note="maintenance-mode candidate"),
    ProviderCandidate("CrewAI", "orchestration", package="crewai", feature_flag="enable_crewai"),
    ProviderCandidate("Playwright", "browser", "reyes_agent.browser_runtime", package="playwright", device="local-windows", selected=True),
    ProviderCandidate("browser-use", "browser", package="browser_use", feature_flag="enable_browser_use", device="local-windows"),
    ProviderCandidate("pywinauto", "desktop", "reyes_agent.computer.windows.pywinauto_backend", package="pywinauto", device="local-windows", selected=True),
    ProviderCandidate("Windows UI Automation / COM", "desktop", "reyes_agent.computer.agent_backends.ladder", package="comtypes", device="local-windows", selected=True),
    ProviderCandidate("PowerShell", "desktop", "reyes_agent.computer.controller", binary="powershell", device="local-windows", selected=True),
    ProviderCandidate("PyAutoGUI", "desktop fallback", "reyes_agent.computer.controller", package="pyautogui", device="local-windows", selected=True),
    ProviderCandidate("watchdog", "filesystem events", package="watchdog", feature_flag="enable_watchdog"),
    ProviderCandidate("pynput", "input observation", package="pynput", feature_flag="enable_pynput", device="local-windows"),
    ProviderCandidate("mss", "screen capture", "reyes_agent.computer.controller", package="mss", device="local-windows", selected=True),
    ProviderCandidate("Android DeviceLink", "phone control", "reyes_agent.devices.android_device", device="android", selected=True),
    ProviderCandidate("scrcpy", "phone screen", "reyes_agent.devices.android.scrcpy", binary="scrcpy", feature_flag="enable_scrcpy", device="android"),
    ProviderCandidate("aiortc", "WebRTC", "reyes_agent.remote_access.live_desktop_node", package="aiortc", selected=True),
    ProviderCandidate("faster-whisper", "speech recognition", "reyes_agent.voice.stt.faster_whisper", package="faster_whisper", selected=True),
    ProviderCandidate("whisper.cpp", "speech recognition", package="whisper_cpp", feature_flag="enable_whisper_cpp"),
    ProviderCandidate("Deepgram", "speech recognition", "reyes_agent.voice.stt.cloud", environment=("DEEPGRAM_API_KEY",)),
    ProviderCandidate("openWakeWord", "wake word", "reyes_agent.wake.openwakeword_backend", package="openwakeword", selected=True),
    ProviderCandidate("Silero VAD", "voice activity detection", package="torch", feature_flag="enable_silero_vad"),
    ProviderCandidate("Energy VAD", "voice activity detection", "reyes_agent.wake.vad", selected=True),
    ProviderCandidate("ElevenLabs", "text to speech", "reyes_agent.voice.tts", environment=("ELEVENLABS_API_KEY",)),
    ProviderCandidate("Kokoro/local TTS", "text to speech", "reyes_agent.voice.tts_router", package="onnxruntime", selected=True),
    ProviderCandidate("pyttsx3", "text to speech fallback", "reyes_agent.voice.tts_router", package="pyttsx3", selected=True),
    ProviderCandidate("FFmpeg", "media processing", "reyes_agent.creative.video.renderer", binary="ffmpeg", selected=True),
    ProviderCandidate("OpenCV", "computer vision", "reyes_agent.vision.camera.sensor", package="cv2", selected=True),
    ProviderCandidate("Windows OCR", "OCR", "reyes_agent.ocr", package="winsdk", device="local-windows", selected=True),
    ProviderCandidate("Tesseract", "OCR alternative", package="pytesseract", binary="tesseract", feature_flag="enable_tesseract"),
    ProviderCandidate("PaddleOCR", "OCR alternative", package="paddleocr", feature_flag="enable_paddleocr"),
    ProviderCandidate("PyMuPDF", "PDF", "reyes_agent.ocr", package="fitz", selected=True),
    ProviderCandidate("python-docx", "Word", "reyes_agent.ocr", package="docx", selected=True),
    ProviderCandidate("openpyxl", "Excel", "reyes_agent.ocr", package="openpyxl", selected=True),
    ProviderCandidate("python-pptx", "PowerPoint", "reyes_agent.ocr", package="pptx", selected=True),
    ProviderCandidate("Docling", "document intelligence", "reyes_agent.knowledge.documents.loader", package="docling", feature_flag="enable_docling"),
    ProviderCandidate("Slack desktop/API", "messaging", "reyes_agent.tools.messaging.slack", selected=True),
    ProviderCandidate("Gmail", "email", "reyes_agent.tools.email_tools", environment=("GMAIL_ACCESS_TOKEN",)),
    ProviderCandidate("Telegram", "messaging", "reyes_agent.tools.messaging.telegram", selected=True),
    ProviderCandidate("Discord", "messaging", "reyes_agent.tools.messaging.discord", selected=True),
    ProviderCandidate("SQLite", "database", "reyes_agent.memory.manager", selected=True),
    ProviderCandidate("DuckDB", "analytics", "reyes_agent.analytics", package="duckdb", selected=True),
    ProviderCandidate("sqlite-vec", "vector retrieval", "reyes_agent.knowledge.sqlite_vec_backend", package="sqlite_vec", selected=True),
    ProviderCandidate("Mem0", "optional memory", "reyes_agent.memory.mem0_backend", package="mem0", feature_flag="enable_mem0"),
    ProviderCandidate("Ollama", "local models", "reyes_agent.provider", binary="ollama", selected=True),
    ProviderCandidate("Git", "source control", "reyes_agent.coding_system.workspace", binary="git", selected=True),
    ProviderCandidate("GitHub", "source hosting", environment=("GITHUB_TOKEN",)),
    ProviderCandidate("Official MCP SDK", "MCP", "reyes_agent.tools.mcp.client", package="mcp", selected=True),
    ProviderCandidate("Docker", "containers", "reyes_agent.sandbox.manager", binary="docker", selected=True),
    ProviderCandidate("Kubernetes", "orchestration", binary="kubectl", feature_flag="enable_kubernetes"),
    ProviderCandidate("Semgrep", "defensive security", binary="semgrep", feature_flag="enable_semgrep"),
    ProviderCandidate("Trivy", "defensive security", binary="trivy", feature_flag="enable_trivy"),
    ProviderCandidate("Gitleaks", "defensive security", binary="gitleaks", feature_flag="enable_gitleaks"),
    ProviderCandidate("OSV-Scanner", "defensive security", binary="osv-scanner", feature_flag="enable_osv_scanner"),
    ProviderCandidate("OpenTelemetry", "tracing", "reyes_agent.observability", package="opentelemetry", feature_flag="enable_otel_traces"),
    ProviderCandidate("Meilisearch", "universal search", "reyes_agent.universal_search", feature_flag="enable_meilisearch"),
    ProviderCandidate("Temporal", "durable workflow alternative", package="temporalio", feature_flag="enable_temporal"),
)


# Make every optional provider gate visible in the one feature-flag authority.
# Registration is metadata-only: it does not import a provider SDK, start a
# process, download a model or enable the integration.
def _register_provider_flags() -> None:
    from reyes_agent.feature_flags import register

    for provider in PROVIDERS:
        if provider.feature_flag:
            register(
                provider.feature_flag,
                default=False,
                description=(f"Lazy optional provider for {provider.capability}: "
                             f"{provider.name}."),
            )


_register_provider_flags()


def provider_candidates() -> list[dict[str, Any]]:
    return [provider.as_dict() for provider in PROVIDERS]


def query(*, state: str = "", text: str = "", limit: int = 100) -> dict[str, Any]:
    wanted_state = str(state or "").strip().upper()
    needle = str(text or "").strip().casefold()
    capped = max(1, min(500, int(limit)))
    section_rows = [item.as_dict() for item in sections()]
    provider_rows = provider_candidates()
    if wanted_state:
        section_rows = [row for row in section_rows if row["state"] == wanted_state]
        provider_rows = [row for row in provider_rows if row["state"] == wanted_state]
    if needle:
        section_rows = [row for row in section_rows if needle in (
            f"{row['number']} {row['title']} {row['evidence']}").casefold()]
        provider_rows = [row for row in provider_rows if needle in (
            f"{row['name']} {row['capability']} {row['reason']}").casefold()]
    return {
        "sections": section_rows[:capped],
        "providers": provider_rows[:capped],
        "section_total": len(SECTION_TITLES),
        "provider_total": len(PROVIDERS),
        "states": list(STATES),
    }


def status() -> dict[str, Any]:
    section_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    for row in sections():
        section_counts[row.state] = section_counts.get(row.state, 0) + 1
    for row in provider_candidates():
        provider_counts[row["state"]] = provider_counts.get(row["state"], 0) + 1
    return {
        "state": "ONLINE",
        "sections": len(SECTION_TITLES),
        "providers": len(PROVIDERS),
        "section_states": section_counts,
        "provider_states": provider_counts,
        "rule": "discovered broadly, integrated selectively, never auto-installed",
    }


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).casefold()).strip("-")
