"""Independent proof that an action achieved its requested outcome."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

VERIFIED, LIKELY, PARTIAL, UNVERIFIED, FAILED = (
    "VERIFIED", "LIKELY", "PARTIAL", "UNVERIFIED", "FAILED")


@dataclass
class VerificationResult:
    state: str
    strategy: str
    evidence: dict[str, Any]
    reason: str = ""

    @property
    def verified(self) -> bool:
        return self.state == VERIFIED

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


Strategy = Callable[[dict[str, Any]], VerificationResult]


class VerificationStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, name: str, strategy: Strategy) -> None:
        self._strategies[str(name)] = strategy

    def verify(self, name: str, expectation: dict[str, Any]) -> VerificationResult:
        strategy = self._strategies.get(str(name))
        if strategy is None:
            return VerificationResult(UNVERIFIED, str(name), {}, "no verification strategy")
        try:
            return strategy(expectation)
        except Exception as exc:
            return VerificationResult(FAILED, str(name), {}, f"verifier failed: {type(exc).__name__}")


def _file(expectation: dict[str, Any]) -> VerificationResult:
    path = Path(str(expectation.get("path") or ""))
    if not path.is_file():
        return VerificationResult(FAILED, "file", {"path": str(path), "exists": False},
                                  "expected file does not exist")
    expected = expectation.get("contains")
    if expected is not None:
        try:
            matched = str(expected) in path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            matched = False
        if not matched:
            return VerificationResult(FAILED, "file", {"path": str(path), "exists": True},
                                      "expected content not found")
    if expectation.get("valid_json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return VerificationResult(FAILED, "file", {"path": str(path)}, "invalid JSON")
    return VerificationResult(VERIFIED, "file", {"path": str(path), "size": path.stat().st_size})


def _provider_receipt(expectation: dict[str, Any]) -> VerificationResult:
    receipt = expectation.get("external_result_id") or expectation.get("message_id")
    if not receipt:
        return VerificationResult(UNVERIFIED, "provider_receipt", {}, "provider returned no receipt ID")
    evidence = {"external_result_id": str(receipt),
                "target": str(expectation.get("target") or "")[:300]}
    return VerificationResult(VERIFIED, "provider_receipt", evidence)


def _predicate(expectation: dict[str, Any]) -> VerificationResult:
    check = expectation.get("check")
    if not callable(check):
        return VerificationResult(UNVERIFIED, "predicate", {}, "no independent check")
    matched = bool(check())
    return VerificationResult(VERIFIED if matched else FAILED, "predicate", {},
                              "" if matched else "independent state check failed")


class ActionVerifier:
    def __init__(self, registry: VerificationStrategyRegistry | None = None) -> None:
        self.registry = registry or VerificationStrategyRegistry()
        if registry is None:
            self.registry.register("file", _file)
            self.registry.register("provider_receipt", _provider_receipt)
            self.registry.register("predicate", _predicate)

    def verify(self, strategy: str, expectation: dict[str, Any], *,
               action: dict[str, Any] | None = None) -> VerificationResult:
        result = self.registry.verify(strategy, expectation)
        if action:
            try:
                from reyes_agent.evidence_ledger import get_evidence_ledger
                get_evidence_ledger().record(
                    command_id=str(action.get("command_id") or ""),
                    source_device=str(action.get("source_device") or ""),
                    executing_device=str(action.get("executing_device") or ""),
                    agent=str(action.get("agent") or "ZENO"),
                    capability=str(action.get("capability") or ""),
                    provider=str(action.get("provider") or ""),
                    target=str(action.get("target") or ""),
                    result=result.reason or result.state,
                    verification=result.state,
                    external_result_id=str(result.evidence.get("external_result_id") or ""),
                    trace_id=str(action.get("trace_id") or ""),
                )
            except Exception:
                pass
        return result


OutcomeVerifier = ActionVerifier

_verifier = ActionVerifier()


def get_action_verifier() -> ActionVerifier:
    return _verifier


# ---------------------------------------------------------------------------
# Backward-compatible action-oriented API.  This was ZENO's original verifier
# contract and remains the authority used by existing desktop/tool callers.

@dataclass(frozen=True)
class Verdict:
    verified: bool
    verifiable: bool
    method: str
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_UNVERIFIABLE = Verdict(False, False, "none", "no independent check available")


def _running_processes() -> list[str]:
    try:
        import psutil
        return [(proc.info.get("name") or "").casefold()
                for proc in psutil.process_iter(["name"]) if proc.info.get("name")]
    except Exception:
        return []


_APP_PROCESS_HINTS = {
    "chrome": ["chrome"], "google chrome": ["chrome"],
    "edge": ["msedge"], "microsoft edge": ["msedge"], "firefox": ["firefox"],
    "slack": ["slack"], "notepad": ["notepad"],
    "calculator": ["calculatorapp", "calc"], "calc": ["calculatorapp", "calc"],
    "explorer": ["explorer"], "file explorer": ["explorer"],
    "code": ["code"], "vs code": ["code"], "visual studio code": ["code"],
    "word": ["winword"], "excel": ["excel"], "powerpoint": ["powerpnt"],
    "outlook": ["outlook"], "teams": ["teams", "ms-teams"],
    "spotify": ["spotify"], "discord": ["discord"], "telegram": ["telegram"],
    "terminal": ["windowsterminal"], "cmd": ["cmd"], "powershell": ["powershell"],
}


def app_is_running(app: str) -> tuple[bool, str]:
    app_l = str(app or "").strip().casefold()
    if not app_l:
        return False, ""
    processes = _running_processes()
    if not processes:
        return False, ""
    hints = _APP_PROCESS_HINTS.get(app_l) or [app_l.replace(" ", "")]
    for hint in hints:
        for name in processes:
            if hint and hint in name:
                return True, f"process '{name}' is running"
    return False, ""


def _parse_result(result: Any) -> Any:
    if isinstance(result, str):
        stripped = result.strip()
        if stripped[:1] in "{[":
            try:
                return json.loads(stripped)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    return result


def _explicit_evidence(result: Any) -> Verdict | None:
    parsed = _parse_result(result)
    if not isinstance(parsed, dict):
        return None
    evidence = parsed.get("evidence") or parsed.get("verification_evidence")
    if parsed.get("ok") is True and evidence:
        return Verdict(True, True, "evidence", str(evidence)[:200])
    if parsed.get("verified") is True or str(parsed.get("verification_state", "")).casefold() == "verified":
        return Verdict(True, True, "evidence", "tool reported verified")
    if parsed.get("ok") is False or parsed.get("success") is False:
        return Verdict(False, True, "evidence", "tool reported failure")
    return None


def _arg(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _verify_open_app(args: dict[str, Any], result: Any) -> Verdict:
    app = _arg(args, "app", "app_name", "name", "target")
    if not app and isinstance(result, str):
        low = result.casefold()
        for token in ("opened ", "launched ", "starting ", "started "):
            index = low.find(token)
            if index >= 0:
                app = result[index + len(token):].strip(" .\n")
                break
    if not app:
        return _UNVERIFIABLE
    running, why = app_is_running(app)
    return (Verdict(True, True, "process", why) if running else
            Verdict(False, True, "process", f"no running process matches '{app}'"))


def _verify_path(args: dict[str, Any], _result: Any) -> Verdict:
    path = _arg(args, "path", "file", "filename", "dest", "destination", "target")
    if not path:
        return _UNVERIFIABLE
    try:
        exists = os.path.exists(path)
    except Exception:
        return _UNVERIFIABLE
    return (Verdict(True, True, "path", f"'{path}' exists") if exists else
            Verdict(False, True, "path", f"'{path}' is missing"))


_CHECKS: dict[str, Callable[[dict[str, Any], Any], Verdict]] = {
    "open_app": _verify_open_app, "launch_app": _verify_open_app,
    "open_application": _verify_open_app, "create_file": _verify_path,
    "write_file": _verify_path, "save_file": _verify_path,
    "create_folder": _verify_path, "make_folder": _verify_path,
    "download": _verify_path,
}


def register(action: str, checker: Callable[[dict[str, Any], Any], Verdict]) -> None:
    _CHECKS[str(action).strip().casefold()] = checker


def verify(action: str, args: dict[str, Any] | None = None, result: Any = None) -> Verdict:
    try:
        supplied = args if isinstance(args, dict) else {}
        evidence = _explicit_evidence(result)
        if evidence is not None:
            return evidence
        key = str(action or "").strip().casefold()
        checker = _CHECKS.get(key) or _CHECKS.get(key.rsplit(".", 1)[-1])
        return checker(supplied, result) if checker is not None else _UNVERIFIABLE
    except Exception:
        return _UNVERIFIABLE


def _action_strategy(expectation: dict[str, Any]) -> VerificationResult:
    verdict = verify(str(expectation.get("action") or ""),
                     expectation.get("args") if isinstance(expectation.get("args"), dict) else {},
                     expectation.get("result"))
    state = VERIFIED if verdict.verified else FAILED if verdict.verifiable else UNVERIFIED
    return VerificationResult(state, "action", {"method": verdict.method,
                              "evidence": verdict.evidence}, verdict.evidence)


_verifier.registry.register("action", _action_strategy)
