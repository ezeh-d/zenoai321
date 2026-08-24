"""Turn redacted production failures into deterministic golden cases."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent.memory.privacy import redact

_ROOT = config.PROJECT_ROOT / "tests" / "golden" / "failures"


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k)[:80]: ("[REDACTED]" if any(x in str(k).casefold()
                for x in ("password", "secret", "token", "cookie", "key")) else _safe(v))
                for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return [_safe(v) for v in value[:100]]
    return redact(value, limit=2000) if isinstance(value, (str, bytes)) else value


class RegressionCorpus:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or _ROOT
        self._lock = threading.RLock()

    def cases(self) -> list[dict[str, Any]]:
        found = []
        for path in sorted(self.root.glob("*.json")) if self.root.exists() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    found.append(data)
            except (OSError, ValueError):
                continue
        return found

    def write(self, case: dict[str, Any]) -> Path:
        safe = _safe(case)
        fingerprint = hashlib.sha256(json.dumps(safe, sort_keys=True, default=str).encode()).hexdigest()[:16]
        path = self.root / f"{fingerprint}.json"
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"case_id": fingerprint, **safe}, indent=2,
                                                sort_keys=True, default=str), encoding="utf-8")
                temporary.replace(path)
        return path


class RegressionCaseGenerator:
    REQUIRED = {"input", "system_state", "failure_class", "expected_behavior", "fix"}

    def generate(self, **case: Any) -> dict[str, Any]:
        missing = sorted(self.REQUIRED - set(case))
        if missing:
            raise ValueError(f"missing regression fields: {', '.join(missing)}")
        payload = {**case, "captured_at": float(case.get("captured_at") or time.time()),
                   "schema_version": 1}
        path = RegressionCorpus().write(payload)
        return {"created": True, "path": str(path), "case": payload}


class FailureCaptureService:
    def __init__(self, generator: RegressionCaseGenerator | None = None) -> None:
        self.generator = generator or RegressionCaseGenerator()

    def capture(self, *, input: Any, system_state: dict[str, Any], failure_class: str,
                expected_behavior: Any, fix: Any = "pending") -> dict[str, Any]:
        return self.generator.generate(input=input, system_state=system_state,
                                       failure_class=failure_class,
                                       expected_behavior=expected_behavior, fix=fix)
