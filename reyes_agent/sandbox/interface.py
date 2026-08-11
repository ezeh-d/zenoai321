"""Common sandbox contracts. Backends must state their containment strength."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    state: str
    backend: str
    return_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    containment: str
    verified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class SandboxBackend(Protocol):
    def status(self) -> dict[str, Any]: ...
    def execute_python(self, script: str, *, workspace: str, timeout_s: float) -> SandboxResult: ...
