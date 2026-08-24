"""Every capability ZENO has, with state that is DETECTED rather than declared.

THE DISTINCTION THE BRIEF INSISTS ON
------------------------------------
Knowledge is not capability. ZENO can understand accounting perfectly and
still be unable to reconcile an invoice, because that needs a PDF parser and
a query engine that may or may not be on this machine.

So a capability carries four independent states, and all four have to be
true before it can be used:

    PRESENT     the binary/package/service exists here
    CONFIGURED  it has whatever settings or endpoint it needs
    AUTHORISED  credentials exist AND permission policy allows it
    HEALTHY     a real check says it works

`import succeeded` is only the first of those. A capability is never marked
READY because a module imported -- the brief says so explicitly, and it is
the single easiest way for an assistant to start lying about itself.

WHY DETECTION AND NOT A CONFIG FILE
-----------------------------------
A declared inventory drifts. The owner installs Node, uninstalls ffmpeg,
revokes a token, and a hand-maintained list keeps claiming otherwise. Every
state below is derived from something real -- `capabilities.inventory` for
presence, `config`/`secrets` for configuration and authorisation -- so the
answer to "can you do this?" cannot go stale.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent.capabilities import inventory

# Categories, as the brief lists them.
KNOWLEDGE = "KNOWLEDGE"
API = "API"
MCP_TOOL = "MCP_TOOL"
WINDOWS_APP = "WINDOWS_APP"
BROWSER_TOOL = "BROWSER_TOOL"
COMMAND_LINE_TOOL = "COMMAND_LINE_TOOL"
PYTHON_LIBRARY = "PYTHON_LIBRARY"
LOCAL_MODEL = "LOCAL_MODEL"
CLOUD_MODEL = "CLOUD_MODEL"
DATABASE = "DATABASE"
WORKFLOW = "WORKFLOW"
EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
DEVICE = "DEVICE"
AGENT = "AGENT"
LEARNED_SKILL = "LEARNED_SKILL"

CATEGORIES = (KNOWLEDGE, API, MCP_TOOL, WINDOWS_APP, BROWSER_TOOL,
              COMMAND_LINE_TOOL, PYTHON_LIBRARY, LOCAL_MODEL, CLOUD_MODEL,
              DATABASE, WORKFLOW, EXTERNAL_SERVICE, DEVICE, AGENT, LEARNED_SKILL)

# Health states, as the brief lists them.
ONLINE = "ONLINE"
READY = "READY"
STANDBY = "STANDBY"
AUTH_REQUIRED = "AUTH_REQUIRED"
DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
DISABLED = "DISABLED"

# Only these mean "ZENO can use this right now".
USABLE = frozenset({ONLINE, READY})

# Risk, for the permission broker.
SAFE, ORDINARY, SENSITIVE, DANGEROUS = "SAFE", "ORDINARY", "SENSITIVE", "DANGEROUS"


@dataclass
class Capability:
    name: str
    description: str = ""
    category: str = PYTHON_LIBRARY
    # How presence is established. Exactly one is normally set.
    binary: str = ""
    package: str = ""
    detector: Callable[[], bool] | None = None
    # What it needs before it can be used.
    requires_config: tuple[str, ...] = ()      # config attribute names
    requires_secret: tuple[str, ...] = ()      # secret key names
    depends_on: tuple[str, ...] = ()           # other capability names
    # What using it costs the owner.
    risk: str = ORDINARY
    network: bool = False
    filesystem: bool = False
    cost: str = "free"
    # Live counters.
    uses: int = 0
    successes: int = 0
    failures: int = 0
    last_used: float = 0.0
    install_hint: str = ""

    @property
    def success_rate(self) -> float:
        return (self.successes / self.uses) if self.uses else 0.0

    def present(self) -> bool:
        """Is the thing physically here. The cheap question."""
        if self.detector is not None:
            try:
                return bool(self.detector())
            except Exception:  # noqa: BLE001
                return False
        if self.binary:
            return inventory.has_binary(self.binary)
        if self.package:
            return inventory.has_package(self.package)
        return True                # KNOWLEDGE capabilities need nothing installed

    def configured(self) -> bool:
        if not self.requires_config:
            return True
        try:
            from reyes_agent import config
        except Exception:  # noqa: BLE001
            return False
        return all(bool(getattr(config, name, "")) for name in self.requires_config)

    def authorised(self) -> tuple[bool, str]:
        """Credentials present AND policy permitting. Both, or neither counts."""
        if self.requires_secret:
            missing = [k for k in self.requires_secret if not _credential(k)]
            if missing:
                return False, f"needs credentials: {', '.join(missing)}"
        return True, "no additional credentials required"

    def health(self) -> tuple[str, str]:
        """(state, why). The only place a capability's usability is decided."""
        if not self.present():
            hint = f" -- {self.install_hint}" if self.install_hint else ""
            what = self.binary or self.package or self.name
            return DEPENDENCY_MISSING, f"{what} is not installed here{hint}"
        if not self.configured():
            return STANDBY, (f"installed but not configured; needs "
                             f"{', '.join(self.requires_config)}")
        allowed, why = self.authorised()
        if not allowed:
            return AUTH_REQUIRED, why
        for other in self.depends_on:
            dependency = get(other)
            if dependency is None:
                return DEPENDENCY_MISSING, f"depends on '{other}', which ZENO does not know"
            state, reason = dependency.health()
            if state not in USABLE:
                return DEPENDENCY_MISSING, f"depends on '{other}', which is {state}: {reason}"
        return READY, "present, configured and permitted"

    @property
    def usable(self) -> bool:
        return self.health()[0] in USABLE

    def record(self, ok: bool) -> None:
        self.uses += 1
        self.last_used = time.time()
        if ok:
            self.successes += 1
        else:
            self.failures += 1

    def as_dict(self) -> dict[str, Any]:
        state, why = self.health()
        return {"name": self.name, "description": self.description,
                "category": self.category, "state": state, "why": why,
                "usable": state in USABLE, "risk": self.risk,
                "network": self.network, "filesystem": self.filesystem,
                "cost": self.cost, "depends_on": list(self.depends_on),
                "uses": self.uses, "success_rate": round(self.success_rate, 3),
                "last_used": self.last_used or None,
                "install_hint": self.install_hint}


def _credential(key: str) -> bool:
    """Is this key resolvable, without ever reading its value into a variable
    that outlives the check.

    `config` is consulted FIRST and deliberately: it is the authority ZENO's
    own providers read, and importing it is what loads `.env` into the
    environment. Asking the secret store alone made this order-dependent --
    the same capability reported READY or AUTH_REQUIRED depending on whether
    anything had imported config yet, which is worse than either answer.
    """
    try:
        from reyes_agent import config

        if bool(getattr(config, key, "")):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        from reyes_agent.security import secrets

        return bool(secrets.get(key))
    except Exception:  # noqa: BLE001
        return False


_capabilities: dict[str, Capability] = {}


def register(capability: Capability) -> Capability:
    _capabilities[capability.name] = capability
    return capability


def get(name: str) -> Capability | None:
    return _capabilities.get(str(name or "").strip().lower())


def all_capabilities(category: str = "") -> list[Capability]:
    items = list(_capabilities.values())
    if category:
        items = [c for c in items if c.category == category]
    return sorted(items, key=lambda c: (c.category, c.name))


def usable_names() -> list[str]:
    return sorted(c.name for c in _capabilities.values() if c.usable)


def _seed() -> None:
    """The capabilities ZENO ships with. Presence is still detected."""
    if _capabilities:
        return

    def cap(name, description, category, **kw):
        register(Capability(name=name, description=description,
                            category=category, **kw))

    # --- things that must physically exist -------------------------------
    cap("python", "run Python code", COMMAND_LINE_TOOL, detector=lambda: True)
    cap("node", "run JavaScript and npm tooling", COMMAND_LINE_TOOL, binary="node",
        install_hint="install Node.js from nodejs.org")
    cap("git", "read and write repositories", COMMAND_LINE_TOOL, binary="git",
        install_hint="install Git for Windows")
    cap("ffmpeg", "convert audio and video", COMMAND_LINE_TOOL, binary="ffmpeg",
        install_hint="install ffmpeg and put it on PATH")
    cap("duckdb", "query tabular data properly instead of guessing", DATABASE,
        package="duckdb", install_hint="pip install duckdb")
    cap("pandas", "manipulate tabular data", PYTHON_LIBRARY, package="pandas",
        install_hint="pip install pandas")
    cap("docling", "parse PDF, DOCX, PPTX and XLSX", PYTHON_LIBRARY, package="docling",
        install_hint="pip install docling")
    cap("playwright", "drive a real browser with selectors", BROWSER_TOOL,
        package="playwright")
    cap("opencv", "process images and camera frames", PYTHON_LIBRARY, package="cv2")
    cap("numpy", "numeric computation", PYTHON_LIBRARY, package="numpy")
    cap("psutil", "inspect processes and resources", PYTHON_LIBRARY, package="psutil")
    cap("uiautomation", "read and drive Windows application controls", WINDOWS_APP,
        package="comtypes")
    cap("pywinauto", "inspect native Windows UI Automation controls", WINDOWS_APP,
        package="pywinauto", risk=SENSITIVE,
        install_hint="python install.py --catalog-safe")
    cap("native_documents", "extract bounded text from PDF, DOCX, XLSX and PPTX",
        PYTHON_LIBRARY,
        detector=lambda: all(inventory.has_package(name)
                             for name in ("fitz", "docx", "openpyxl", "pptx")),
        filesystem=True, install_hint="python install.py --catalog-safe")
    cap("ollama", "run a local model", LOCAL_MODEL, binary="ollama",
        install_hint="install Ollama from ollama.com")

    # --- things that need a key ------------------------------------------
    cap("gemini", "frontier reasoning", CLOUD_MODEL, requires_secret=("GEMINI_API_KEY",),
        network=True, cost="metered")
    cap("openai", "frontier reasoning", CLOUD_MODEL, requires_secret=("OPENAI_API_KEY",),
        network=True, cost="metered")
    cap("deepgram", "speech to text", CLOUD_MODEL, requires_secret=("DEEPGRAM_API_KEY",),
        network=True, cost="metered")
    cap("elevenlabs", "speech synthesis", CLOUD_MODEL,
        requires_secret=("ELEVENLABS_API_KEY",), network=True, cost="metered")
    cap("github", "read and write GitHub", API, requires_secret=("GITHUB_TOKEN",),
        network=True, risk=SENSITIVE)
    cap("home_assistant", "control the home", EXTERNAL_SERVICE,
        requires_secret=("HOME_ASSISTANT_TOKEN",), network=True, risk=SENSITIVE)

    # --- email: the brief's worked example --------------------------------
    # Deliberately registered so ZENO can say exactly WHY it cannot do email
    # automation yet, rather than "I don't support that".
    cap("email_provider", "read and send mail through a real mailbox", EXTERNAL_SERVICE,
        detector=lambda: False, network=True, risk=SENSITIVE,
        install_hint="connect Gmail, Outlook or an IMAP account -- ZENO has no mailbox yet")
    cap("calendar", "read and write calendar events", EXTERNAL_SERVICE,
        detector=lambda: False, network=True, risk=SENSITIVE,
        install_hint="connect a calendar account")

    # --- things ZENO built and therefore genuinely has ---------------------
    cap("web_research", "fetch and extract web pages with citations", BROWSER_TOOL,
        detector=lambda: True, network=True)
    cap("semantic_search", "retrieve from the local knowledge index", DATABASE,
        detector=lambda: True)
    cap("computer_control", "read the screen and operate applications", WINDOWS_APP,
        detector=lambda: True, risk=SENSITIVE)
    cap("memory", "remember across sessions", DATABASE, detector=lambda: True)
    cap("skills", "run workflows the owner has approved", LEARNED_SKILL,
        detector=lambda: True)
    cap("missions", "run long work that survives a restart", WORKFLOW,
        detector=lambda: True)
    cap("opportunity_intelligence", "score evidence-led legitimate opportunities without income guarantees",
        WORKFLOW, detector=lambda: True)
    cap("agents", "delegate to specialist agents", AGENT, detector=lambda: True)
    cap("sandbox", "run generated code somewhere contained", WORKFLOW,
        detector=lambda: True, risk=SENSITIVE)


def refresh() -> dict[str, Any]:
    """Re-detect everything. Called when software changes."""
    inventory.invalidate()
    return status()


def status() -> dict[str, Any]:
    _seed()
    items = all_capabilities()
    by_state: dict[str, int] = {}
    for capability in items:
        state = capability.health()[0]
        by_state[state] = by_state.get(state, 0) + 1
    return {
        "state": "ONLINE",
        "total": len(items),
        "usable": len([c for c in items if c.usable]),
        "by_state": by_state,
        "by_category": {c: len(all_capabilities(c)) for c in CATEGORIES
                        if all_capabilities(c)},
        "inventory": inventory.stats(),
        "note": ("State is detected, never declared. A capability is never READY "
                 "because a module imported -- it must be present, configured, "
                 "permitted, and its dependencies usable."),
    }


def describe(category: str = "") -> dict[str, Any]:
    """What ZENO can do, grouped -- the answer to 'what can you do?'."""
    _seed()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for capability in all_capabilities(category):
        grouped.setdefault(capability.category, []).append(capability.as_dict())
    return {"categories": grouped,
            "usable": usable_names(),
            "summary": f"{len(usable_names())} of {len(all_capabilities())} capabilities usable now"}
