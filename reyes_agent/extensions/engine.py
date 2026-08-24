"""Security-gated autonomous extension lifecycle for ZENO."""

from __future__ import annotations

import ast
import hashlib
import json
import time
from pathlib import Path, PurePosixPath
from typing import Any

from reyes_agent.extensions.adapter import AdapterGenerator, ZenoCapabilityAdapter, adapter_is_healthy
from reyes_agent.extensions.inspection import CompatibilityAnalyzer, IntegrationPlanner, RepositoryInspector
from reyes_agent.extensions.models import (
    ACTIVE, APPROVAL, BENCHMARK, BROKEN, CANARY, COMPATIBILITY_REVIEW,
    INSPECTING, QUARANTINED, REJECTED, SANDBOX_TEST, SECURITY_REVIEW,
    RepositorySnapshot, TestRecord,
)
from reyes_agent.extensions.registry import ExtensionRegistry, ExtensionRollbackManager
from reyes_agent.extensions.source import GitHubImportEngine, SourceError

_EXECUTABLE_SUFFIXES = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh",
    ".ps1", ".bat", ".cmd", ".exe", ".dll", ".msi", ".jar", ".whl",
}


class ExtensionSandbox:
    """Report and enforce whether an actual strong sandbox is available."""

    def status(self) -> dict[str, Any]:
        from reyes_agent.sandbox.manager import SandboxManager
        status = SandboxManager.status()
        backends = status.get("backends") or {}
        strong = [name for name in ("aio", "e2b")
                  if bool((backends.get(name) or {}).get("available"))]
        return {**status, "strong_available": bool(strong), "strong_backends": strong,
                "unknown_code_execution": "DENIED" if not strong else "STAGED_ONLY"}

    def validate_for(self, snapshot: RepositorySnapshot) -> TestRecord:
        if not has_executable_content(snapshot):
            return TestRecord("sandbox_execution", "PASSED",
                              "No executable content was present; execution was not needed.")
        status = self.status()
        if not status["strong_available"]:
            return TestRecord("sandbox_execution", "BLOCKED",
                              "Unknown executable code requires configured AIO Sandbox or E2B; local restrictions are not an OS boundary.")
        # Availability is not evidence that repository code was tested. A
        # deployment-specific runner must return evidence before promotion.
        return TestRecord("sandbox_execution", "BLOCKED",
                          "Strong isolation is configured, but no source-specific execution evidence exists yet.")


class ExtensionTestRunner:
    def __init__(self, sandbox: ExtensionSandbox | None = None) -> None:
        self.sandbox = sandbox or ExtensionSandbox()

    def run(self, snapshot: RepositorySnapshot) -> list[TestRecord]:
        records: list[TestRecord] = []
        started = time.perf_counter()
        syntax_errors: list[str] = []
        for path, text in snapshot.files.items():
            if PurePosixPath(path).suffix.casefold() != ".py":
                continue
            try:
                ast.parse(text, filename=path)
            except SyntaxError as exc:
                syntax_errors.append(f"{path}:{exc.lineno}")
        records.append(TestRecord(
            "python_static_syntax", "FAILED" if syntax_errors else "PASSED",
            ", ".join(syntax_errors[:10]) if syntax_errors else "All inspected Python parsed without execution.",
            round((time.perf_counter() - started) * 1000, 2),
        ))
        bad_json = []
        for path, text in snapshot.files.items():
            if PurePosixPath(path).name.casefold() not in {"package.json", "mcp.json", "plugin.json"}:
                continue
            try:
                json.loads(text)
            except ValueError:
                bad_json.append(path)
        records.append(TestRecord("manifest_schema", "FAILED" if bad_json else "PASSED",
                                  ", ".join(bad_json) if bad_json else "Inspected JSON manifests parse."))
        records.append(self.sandbox.validate_for(snapshot))
        return records


class SelfExtensionEngine:
    def __init__(self, registry: ExtensionRegistry | None = None,
                 importer: GitHubImportEngine | None = None) -> None:
        self.registry = registry or ExtensionRegistry()
        self.importer = importer or GitHubImportEngine()
        self.inspector = RepositoryInspector()
        self.compatibility = CompatibilityAnalyzer()
        self.planner = IntegrationPlanner()
        self.adapters = AdapterGenerator()
        self.tests = ExtensionTestRunner()
        self.rollback_manager = ExtensionRollbackManager(self.registry)
        self._runtime_adapters: dict[str, ZenoCapabilityAdapter] = {}

    def inspect(self, source: str | Path, *, focus: str = "") -> dict[str, Any]:
        reference = self.importer.parse(source)
        record = self.registry.create(reference.as_dict())
        extension_id = str(record["id"])
        # A repeated request gets a fresh bounded review without bypassing an
        # existing terminal/quarantine gate.
        if record["state"] == QUARANTINED:
            record = self.registry.transition(extension_id, INSPECTING, "owner requested re-inspection")
        elif record["state"] != INSPECTING:
            if record["state"] not in {"DISCOVERED"}:
                return record
            record = self.registry.transition(extension_id, INSPECTING, "bounded source acquisition started")
        try:
            snapshot = self.importer.inspect_source(reference)
        except (OSError, SourceError, ValueError) as exc:
            return self.registry.transition(extension_id, BROKEN,
                    f"source inspection failed: {type(exc).__name__}", health="INSPECTION_FAILED")
        self.registry.transition(extension_id, SECURITY_REVIEW, "static security and license review")
        report = self.inspector.inspect(snapshot)
        trust = calculate_trust(snapshot, report)
        self.registry.patch(extension_id, inspection=report.as_dict(), provenance={
            "source": reference.original, "commit": snapshot.commit,
            "bytes_read": snapshot.bytes_read, "truncated": snapshot.truncated,
            "inspected_at": time.time(),
        }, trust=trust)
        critical = [finding for finding in report.findings if finding.severity == "CRITICAL"]
        if critical:
            return self.registry.transition(extension_id, REJECTED,
                    "critical security/prohibited-purpose finding", health="REJECTED",
                    rejection_reasons=[item.as_dict() for item in critical])
        self.registry.transition(extension_id, COMPATIBILITY_REVIEW, "host/dependency compatibility review")
        compatibility = self.compatibility.analyze(snapshot, report)
        plan = self.planner.plan(snapshot, report, compatibility, focus)
        adapter_manifest = self.adapters.generate(extension_id, snapshot, plan)
        from reyes_agent import feature_flags
        feature_flags.register(plan.feature_flag, False,
                               f"Owner-reviewed extension {extension_id}; defaults disabled.")
        self.registry.patch(extension_id, compatibility=compatibility.as_dict(),
                            plan=plan.as_dict(), adapter=adapter_manifest,
                            version=snapshot_version(snapshot))
        if not compatibility.compatible or plan.classification == "INCOMPATIBLE":
            return self.registry.transition(extension_id, REJECTED,
                    compatibility.reason or "extension is incompatible", health="INCOMPATIBLE")
        if snapshot.truncated:
            return self.registry.transition(extension_id, QUARANTINED,
                    "The bounded review did not inspect the complete source; promotion is denied until complete inspection is available.",
                    health="INCOMPLETE_INSPECTION", feature_enabled=False)
        self.registry.transition(extension_id, SANDBOX_TEST, "static and isolated tests started")
        tests = self.tests.run(snapshot)
        self.registry.patch(extension_id, tests=[item.as_dict() for item in tests])
        failed = [item for item in tests if not item.passed]
        if failed:
            return self.registry.transition(extension_id, QUARANTINED,
                    "; ".join(item.detail for item in failed)[:2000], health="NOT_EXECUTED",
                    feature_enabled=False)
        self.registry.transition(extension_id, BENCHMARK,
                                 "bounded static baseline complete; no existing provider replaced")
        return self.registry.transition(extension_id, APPROVAL,
                "review complete; owner approval and a real healthy adapter are required",
                health="AWAITING_APPROVAL", feature_enabled=False)

    def approve(self, extension_id: str, adapter: ZenoCapabilityAdapter | None = None) -> dict[str, Any]:
        record = self._require(extension_id)
        if record["state"] != APPROVAL:
            return {"ok": False, "extension": record,
                    "reason": f"Extension must be in APPROVAL, not {record['state']}."}
        if adapter is None:
            return {"ok": False, "extension": record,
                    "reason": "No executable adapter was supplied; a generated manifest is not working code."}
        healthy, health = adapter_is_healthy(adapter)
        if not healthy:
            return {"ok": False, "extension": record, "health": health,
                    "reason": "Adapter health check did not pass."}
        self.registry.transition(extension_id, CANARY, "owner approved bounded canary", health=health)
        # Registration is allowed only if this adapter also fulfils the one
        # existing universal tool contract. No duplicate tool universe.
        from reyes_agent.tools.universal_registry import ToolAdapter, get_global_tool_registry
        if not isinstance(adapter, ToolAdapter):
            return self.registry.transition(extension_id, BROKEN,
                    "adapter does not implement GlobalToolRegistry contract",
                    health="ADAPTER_CONTRACT_FAILED", feature_enabled=False)
        registered: dict[str, Any] = {}
        try:
            metadata = get_global_tool_registry().register(adapter)
            registered = metadata.as_dict()
            self._runtime_adapters[extension_id] = adapter
            from reyes_agent import feature_flags
            feature_flags.get_flags().enable(str((record.get("plan") or {}).get("feature_flag") or ""), rollout=10)
        except Exception as exc:  # noqa: BLE001 - extension failure boundary
            self._unregister({**record, "registered_tool": registered})
            self._disable_flag(record)
            broken = self.registry.transition(extension_id, BROKEN,
                    f"canary registration failed: {type(exc).__name__}",
                    health="CANARY_REGISTRATION_FAILED", feature_enabled=False)
            return {"ok": False, "extension": broken}
        canary = self.registry.patch(extension_id, health="CANARY_PENDING_EVIDENCE",
                                     feature_enabled=True, registered_tool=metadata.as_dict())
        self._declare_truth(canary, tested=False)
        return {"ok": True, "extension": canary,
                "note": "Adapter is limited to a 10% canary until verified evidence is recorded."}

    def record_canary(self, extension_id: str, *, passed: bool,
                      evidence: dict[str, Any]) -> dict[str, Any]:
        record = self._require(extension_id)
        if record["state"] != CANARY:
            return {"ok": False, "extension": record, "reason": "Extension is not in CANARY."}
        if not evidence or not evidence.get("verification"):
            return {"ok": False, "extension": record,
                    "reason": "Canary promotion requires verification evidence."}
        verification = str(evidence.get("verification") or "").upper()
        if passed and verification not in {"VERIFIED", "PASSED"}:
            return {"ok": False, "extension": record,
                    "reason": "Canary evidence must explicitly be VERIFIED or PASSED."}
        adapter = self._runtime_adapters.get(extension_id)
        healthy, health = adapter_is_healthy(adapter) if adapter is not None else (
            False, {"state": "MISSING", "reason": "Runtime adapter is not loaded."})
        if passed and not healthy:
            passed = False
            evidence = {**evidence, "adapter_health": health,
                        "verification": "FAILED_ADAPTER_HEALTH"}
        flag = str((record.get("plan") or {}).get("feature_flag") or "")
        from reyes_agent import feature_flags
        if not passed:
            self._unregister(record)
            feature_flags.get_flags().disable(flag)
            broken = self.registry.transition(extension_id, BROKEN, "canary verification failed",
                        health="CANARY_FAILED", feature_enabled=False, canary_evidence=evidence)
            return {"ok": False, "extension": broken}
        version = str(record.get("version") or "")
        known_good = list(record.get("known_good") or [])
        if not known_good or str(known_good[-1].get("version") or "") != version:
            known_good.append({"version": version, "verified_at": time.time(), "evidence": evidence})
        feature_flags.get_flags().enable(flag, rollout=100)
        active = self.registry.transition(extension_id, ACTIVE, "canary evidence verified",
                    health="HEALTHY", feature_enabled=True, canary_evidence=evidence,
                    known_good=known_good[-10:])
        self._declare_truth(active, tested=True)
        return {"ok": True, "extension": active}

    def disable(self, extension_id: str) -> dict[str, Any]:
        record = self._require(extension_id)
        if record["state"] not in {ACTIVE, APPROVAL, CANARY, BROKEN}:
            return {"ok": False, "extension": record, "reason": "Extension is not disableable from its current state."}
        state = self.registry.transition(extension_id, "DISABLED", "owner disabled extension",
                                         feature_enabled=False, health="DISABLED")
        self._unregister(record)
        self._disable_flag(record)
        return {"ok": True, "extension": state}

    def remove(self, extension_id: str) -> dict[str, Any]:
        record = self._require(extension_id)
        if record["state"] == ACTIVE:
            self.registry.transition(extension_id, "DISABLED", "disabled before metadata removal",
                                     feature_enabled=False)
        current = self._require(extension_id)
        if current["state"] not in {APPROVAL, "DISABLED", QUARANTINED, REJECTED, BROKEN}:
            return {"ok": False, "extension": current,
                    "reason": "Disable or finish inspection before removal."}
        self._unregister(current)
        self._disable_flag(current)
        removed = self.registry.transition(extension_id, "REMOVED", "owner removed extension metadata",
                                           feature_enabled=False, health="REMOVED")
        return {"ok": True, "extension": removed,
                "note": "Only registry-owned metadata was removed; unrelated files were untouched."}

    def rollback(self, extension_id: str) -> dict[str, Any]:
        record = self._require(extension_id)
        result = self.rollback_manager.rollback(extension_id)
        if result.get("ok"):
            self._unregister(record)
            self._disable_flag(record)
        return result

    def status(self) -> dict[str, Any]:
        self._reconcile_runtime()
        rows = self.registry.list()
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        sandbox = self.tests.sandbox.status()
        return {"state": "ONLINE", "extensions": rows, "counts": counts,
                "policy": "AUTO_SANDBOX_BUT_ASK_BEFORE_ENABLE",
                "unknown_code_execution": sandbox["unknown_code_execution"],
                "strong_sandbox_available": sandbox["strong_available"],
                "catalog": str(self.registry.path)}

    def _reconcile_runtime(self) -> None:
        for record in self.registry.list():
            if record.get("state") not in {ACTIVE, CANARY}:
                continue
            extension_id = str(record.get("id") or "")
            if extension_id in self._runtime_adapters:
                continue
            self._disable_flag(record)
            self.registry.transition(extension_id, BROKEN,
                    "runtime adapter was not restored after process start",
                    health="WORKER_NOT_LOADED", feature_enabled=False)

    def doctor(self, extension_id: str) -> dict[str, Any]:
        record = self._require(extension_id)
        tests = list(record.get("tests") or [])
        return {"extension": extension_id, "name": record.get("name"),
                "state": record.get("state"), "health": record.get("health"),
                "version": record.get("version"), "permissions": (record.get("plan") or {}).get("permissions", {}),
                "tests": {"passed": sum(bool(row.get("passed")) for row in tests), "total": len(tests)},
                "source": record.get("source"), "feature_enabled": record.get("feature_enabled", False),
                "last_event": (record.get("history") or [{}])[-1]}

    def _require(self, extension_id: str) -> dict[str, Any]:
        record = self.registry.get(extension_id)
        if not record:
            raise KeyError(f"unknown extension '{extension_id}'")
        return record

    def _unregister(self, record: dict[str, Any]) -> None:
        tool = record.get("registered_tool") or {}
        tool_id = str(tool.get("tool_id") or tool.get("name") or "")
        if tool_id:
            try:
                from reyes_agent.tools.universal_registry import get_global_tool_registry
                get_global_tool_registry().unregister(tool_id)
            except (KeyError, ValueError):
                pass
        self._runtime_adapters.pop(str(record.get("id") or ""), None)

    @staticmethod
    def _disable_flag(record: dict[str, Any]) -> None:
        try:
            from reyes_agent import feature_flags
            feature_flags.get_flags().disable(str((record.get("plan") or {}).get("feature_flag") or ""))
        except Exception:
            pass

    @staticmethod
    def _declare_truth(record: dict[str, Any], *, tested: bool) -> None:
        try:
            from reyes_agent.capability_truth import get_truth
            tool = record.get("registered_tool") or {}
            get_truth().declare(str(tool.get("name") or record["id"]), installed=True,
                implemented=True, tested=tested, observable=True, documented=True,
                available=True, provider=str(tool.get("provider") or "extension"),
                version=str(record.get("version") or ""),
                permissions=tuple((record.get("plan") or {}).get("permissions", {}).keys()),
                verification_method="extension canary health and adapter verification")
        except Exception:
            pass


class ExtensionUpdateManager:
    def __init__(self, engine: SelfExtensionEngine) -> None:
        self.engine = engine

    def check(self, extension_id: str) -> dict[str, Any]:
        record = self.engine._require(extension_id)
        source = str((record.get("source") or {}).get("original") or "")
        current = str(record.get("version") or "")
        try:
            snapshot = self.engine.importer.inspect_source(source)
        except (SourceError, OSError, ValueError) as exc:
            return {"extension": extension_id, "state": "CHECK_FAILED",
                    "current_version": current, "error": type(exc).__name__}
        candidate = snapshot_version(snapshot)
        changed = bool(candidate and candidate not in {current, "UNPINNED"})
        return {"extension": extension_id,
                "state": "UPDATE_DISCOVERED" if changed else "UP_TO_DATE",
                "current_version": current, "candidate_version": candidate,
                "automatic_upgrade": False,
                "next_step": ("Run the candidate through inspection, sandbox, regression, benchmark and canary."
                              if changed else "No source revision change was observed."),
                "breaking_change_review": "REQUIRED" if changed else "NOT_APPLICABLE"}


class CapabilityHunter:
    """Rank owner-supplied candidates; it never installs search results."""

    def __init__(self, importer: GitHubImportEngine | None = None) -> None:
        self.importer = importer or GitHubImportEngine()

    def search(self, capability: str, *, limit: int = 5) -> dict[str, Any]:
        candidates = self.importer.search_repositories(capability, limit=limit)
        return self.recommend(capability, [str(item.get("url") or "") for item in candidates]) | {
            "results": candidates,
        }

    def recommend(self, capability: str, candidates: list[str]) -> dict[str, Any]:
        return {"capability": str(capability), "candidates": list(candidates)[:20],
                "state": "DISCOVERED", "automatic_install": False,
                "next_step": "Inspect an owner-selected source through SelfExtensionEngine."}


def has_executable_content(snapshot: RepositorySnapshot) -> bool:
    paths = set(snapshot.all_paths) | set(snapshot.binary_paths)
    return any(PurePosixPath(path).suffix.casefold() in _EXECUTABLE_SUFFIXES
               or PurePosixPath(path).name.casefold() in {"dockerfile", "makefile"}
               for path in paths)


def calculate_trust(snapshot: RepositorySnapshot, report: Any) -> dict[str, Any]:
    score = 100
    deductions: list[str] = []
    weights = {"CRITICAL": 70, "HIGH": 15, "MEDIUM": 5, "LOW": 1}
    for finding in report.findings:
        amount = weights.get(str(finding.severity).upper(), 3)
        score -= amount
        deductions.append(f"-{amount} {finding.category}")
    if report.license == "UNKNOWN":
        score -= 15
        deductions.append("-15 unknown license")
    if snapshot.truncated:
        score -= 25
        deductions.append("-25 incomplete inspection")
    if snapshot.metadata.get("archived"):
        score -= 15
        deductions.append("-15 archived repository")
    has_tests = any("test" in PurePosixPath(path).name.casefold() for path in snapshot.all_paths)
    if not has_tests:
        score -= 5
        deductions.append("-5 no tests observed")
    return {"score": max(0, min(100, score)), "deductions": deductions,
            "meaning": "Measured review heuristic; not proof that source is safe."}


def snapshot_version(snapshot: RepositorySnapshot) -> str:
    if snapshot.commit:
        return snapshot.commit
    digest = hashlib.sha256()
    for path, text in sorted(snapshot.files.items()):
        digest.update(path.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8", errors="replace"))
        digest.update(b"\0")
    for path in sorted(snapshot.binary_paths):
        digest.update(f"binary:{path}\0".encode("utf-8", errors="replace"))
    return f"inspect-sha256:{digest.hexdigest()}"


_engine: SelfExtensionEngine | None = None


def get_extension_engine() -> SelfExtensionEngine:
    global _engine
    if _engine is None:
        _engine = SelfExtensionEngine()
    return _engine
