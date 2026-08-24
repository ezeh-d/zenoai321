"""Serializable contracts for the self-extension control plane."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DISCOVERED = "DISCOVERED"
INSPECTING = "INSPECTING"
SECURITY_REVIEW = "SECURITY_REVIEW"
COMPATIBILITY_REVIEW = "COMPATIBILITY_REVIEW"
SANDBOX_TEST = "SANDBOX_TEST"
BENCHMARK = "BENCHMARK"
APPROVAL = "APPROVAL"
CANARY = "CANARY"
ACTIVE = "ACTIVE"
REJECTED = "REJECTED"
QUARANTINED = "QUARANTINED"
BROKEN = "BROKEN"
DISABLED = "DISABLED"
REMOVED = "REMOVED"

STATES = (
    DISCOVERED, INSPECTING, SECURITY_REVIEW, COMPATIBILITY_REVIEW,
    SANDBOX_TEST, BENCHMARK, APPROVAL, CANARY, ACTIVE,
    REJECTED, QUARANTINED, BROKEN, DISABLED, REMOVED,
)

GITHUB_REPOSITORY = "GITHUB_REPOSITORY"
GITHUB_FILE = "GITHUB_FILE"
GITHUB_DIRECTORY = "GITHUB_DIRECTORY"
GITHUB_RELEASE = "GITHUB_RELEASE"
PYTHON_PACKAGE = "PYTHON_PACKAGE"
NODE_PACKAGE = "NODE_PACKAGE"
MCP_SERVER = "MCP_SERVER"
PLUGIN = "PLUGIN"
SKILL = "SKILL"
MODEL_ADAPTER = "MODEL_ADAPTER"
TOOL_ADAPTER = "TOOL_ADAPTER"
LOCAL_FILE = "LOCAL_FILE"
LOCAL_DIRECTORY = "LOCAL_DIRECTORY"


@dataclass(frozen=True)
class SourceReference:
    original: str
    kind: str
    owner: str = ""
    repository: str = ""
    ref: str = ""
    subpath: str = ""
    package: str = ""
    local_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionProfile:
    filesystem: str = "NONE"
    network: tuple[str, ...] = ()
    camera: bool = False
    microphone: bool = False
    browser: bool = False
    desktop: bool = False
    messages: bool = False
    accounts: tuple[str, ...] = ()
    location: bool = False
    subprocess: bool = False

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["network"] = list(self.network)
        value["accounts"] = list(self.accounts)
        return value


@dataclass
class RepositorySnapshot:
    source: SourceReference
    files: dict[str, str] = field(default_factory=dict)
    all_paths: list[str] = field(default_factory=list)
    binary_paths: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    commit: str = ""
    truncated: bool = False
    bytes_read: int = 0


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    detail: str
    path: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InspectionReport:
    structure: tuple[str, ...] = ()
    languages: dict[str, int] = field(default_factory=dict)
    manifests: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    entrypoints: tuple[str, ...] = ()
    license: str = "UNKNOWN"
    license_implication: str = "Review required before copying code."
    permissions: PermissionProfile = field(default_factory=PermissionProfile)
    findings: tuple[Finding, ...] = ()
    endpoints: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    coverage: str = "BOUNDED"
    supply_chain: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["permissions"] = self.permissions.as_dict()
        value["findings"] = [item.as_dict() for item in self.findings]
        return value


@dataclass
class CompatibilityReport:
    compatible: bool
    windows: str
    python: str
    node: str
    conflicts: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Component:
    name: str
    kind: str
    source_files: tuple[str, ...]
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_files"] = list(self.source_files)
        return value


@dataclass
class IntegrationPlan:
    classification: str
    components: list[Component]
    existing_matches: list[str]
    permissions: PermissionProfile
    adapter_kind: str
    feature_flag: str
    promotion_eligible: bool = False
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["components"] = [item.as_dict() for item in self.components]
        value["permissions"] = self.permissions.as_dict()
        return value


@dataclass(frozen=True)
class TestRecord:
    name: str
    state: str
    detail: str
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.state == "PASSED"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}
