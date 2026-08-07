"""Build Checker -- run the project's REAL checks and repair what is safe.

WHERE THIS SITS
---------------
Three pieces already existed and are reused rather than reimplemented:

* ``coding.check_project`` / ``coding.repair_project`` -- static analysis of
  the files, with its own bounded, scored, rollback-on-worse repair loop.
* ``terminal.run`` -- allow-listed command execution with captured output.
* ``diagnostics.analyze`` -- turns that captured output into structured errors.

What was missing is the bridge: nothing actually ran ``npm run build`` or
``tsc`` and fed the result back. A static checker cannot see "Cannot find
module './Nav'" because that only exists once a bundler resolves imports.

WHAT IT WILL AND WILL NOT REPAIR
--------------------------------
Only repairs that are deterministic and safe happen automatically:

* ``npm install`` when dependencies are declared but not installed.
* The static asset-reference repointing ``coding.repair_project`` already does.

It will NOT install a package name scraped out of an error message. That
name comes from generated code, and auto-installing it turns a typo into an
arbitrary package download -- the supply-chain risk the brief rules out.
It will NOT rewrite code it does not understand. Anything needing real
comprehension is returned as structured errors for ZENO to fix deliberately,
which is a decision with a checkpoint behind it rather than a silent guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import task_engine
from reyes_agent.executors import coding, diagnostics, jobs, patching, terminal

# How a repair was arrived at. The distinction matters: a deterministic fix
# is provably safe and applies directly, a model-written one is scoped,
# checkpointed, applied and then judged on whether it actually helped.
DETERMINISTIC = "DETERMINISTIC"
MODEL_GENERATED = "MODEL_GENERATED"
MANUAL_REQUIRED = "MANUAL_REQUIRED"

# Bounded by config; this is the ceiling regardless of what is configured.
MAX_ATTEMPTS_CEILING = 5
# How long a caller waits inline before a check becomes "still running".
# Small projects finish well inside this; a real React build does not, and
# holding a chat worker for its full duration is the thing being fixed.
_INLINE_WAIT_S = 25.0


@dataclass
class Check:
    name: str
    command: str
    optional: bool = False


@dataclass
class CheckRun:
    check: str
    command: str
    ok: bool
    exit_code: int | None
    errors: list[diagnostics.BuildError] = field(default_factory=list)
    skipped: str = ""
    job_id: str = ""
    pending: bool = False        # still running as a background job

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.check, "command": self.command, "ok": self.ok,
                "exit_code": self.exit_code, "skipped": self.skipped,
                "job_id": self.job_id, "pending": self.pending,
                "errors": [e.as_dict() for e in self.errors]}


@dataclass
class BuildReport:
    ok: bool
    runs: list[CheckRun] = field(default_factory=list)
    errors: list[diagnostics.BuildError] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    attempts: int = 0
    rolled_back: bool = False
    reason: str = ""
    static: dict[str, Any] = field(default_factory=dict)
    # One entry per repair attempt, with how it was arrived at. This is what
    # makes "attempt 1 deterministic, attempt 2 model" auditable afterwards.
    ledger: list[dict[str, Any]] = field(default_factory=list)
    exhausted: bool = False

    @property
    def confidence(self) -> str:
        if self.ok:
            return DETERMINISTIC if not any(e.get("confidence") == MODEL_GENERATED for e in self.ledger) else MODEL_GENERATED
        return MANUAL_REQUIRED

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "attempts": self.attempts, "rolled_back": self.rolled_back,
                "reason": self.reason, "repairs": list(self.repairs),
                "runs": [r.as_dict() for r in self.runs],
                "errors": [e.as_dict() for e in self.errors], "static": dict(self.static),
                "ledger": list(self.ledger), "exhausted": self.exhausted,
                "confidence": self.confidence}

    def summary(self) -> str:
        lines = [self.reason or ("Checks passed." if self.ok else "Checks failed.")]
        for run in self.runs:
            if run.skipped:
                lines.append(f"  - {run.check}: skipped ({run.skipped})")
            else:
                lines.append(f"  - {run.check}: {'ok' if run.ok else f'FAILED (exit {run.exit_code})'}")
        if self.repairs:
            lines.append("Repaired automatically: " + "; ".join(self.repairs[:5]))
        if self.errors:
            lines.append(diagnostics.summarize(self.errors))
        return "\n".join(lines)


def _scripts(root: Path) -> dict[str, str]:
    package = root / "package.json"
    if not package.is_file():
        return {}
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts")
    return scripts if isinstance(scripts, dict) else {}


def applicable_checks(root: Path) -> list[Check]:
    """Which real checks this project actually supports.

    Derived from what is on disk, never assumed: running `npm run lint` on a
    project with no lint script produces a confusing failure that is about
    the checker, not the code.
    """
    root = Path(root)
    scripts = _scripts(root)
    checks: list[Check] = []
    if not scripts:
        return checks
    if "build" in scripts:
        checks.append(Check("build", "npm run build"))
    if "typecheck" in scripts:
        checks.append(Check("typecheck", "npm run typecheck"))
    elif (root / "tsconfig.json").is_file():
        checks.append(Check("typecheck", "npx tsc --noEmit", optional=True))
    if "lint" in scripts:
        checks.append(Check("lint", "npm run lint", optional=True))
    return checks


def dependencies_installed(root: Path) -> bool:
    """True when there is nothing to install, or node_modules already exists."""
    root = Path(root)
    package = root / "package.json"
    if not package.is_file():
        return True
    try:
        data = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    declared = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if not declared:
        return True
    return (root / "node_modules").is_dir()


def run_checks(task_id: str, root: Path, *, wait_s: float = _INLINE_WAIT_S) -> list[CheckRun]:
    """Run every applicable check as a BACKGROUND JOB and parse the output.

    A build is started, not awaited indefinitely. Small projects finish
    inside `wait_s` and behave exactly as before; a genuinely long build
    hands back a job id and keeps running, so the caller returns instead of
    holding a worker for minutes. That is the whole point -- ZENO can say
    "still building" rather than freezing.
    """
    root = Path(root)
    runs: list[CheckRun] = []
    for check in applicable_checks(root):
        task_engine.check_cancelled(task_id)
        job, error = jobs.start(check.command, root, project=root.name,
                                task_id=task_id, kind=jobs.classify(check.command))
        if job is None:
            # Refused by the allow-list, or it could not start at all.
            runs.append(CheckRun(check.name, check.command, ok=True, exit_code=None,
                                 skipped=error or "could not start"))
            continue

        finished = jobs.wait(job.id, timeout=wait_s)
        if finished is not None and finished.running:
            runs.append(CheckRun(check.name, check.command, ok=True, exit_code=None,
                                 job_id=job.id, pending=True,
                                 skipped=f"still running as job {job.id}"))
            continue

        output = job.output()
        result_ok = job.state == jobs.SUCCESS
        errors = diagnostics.analyze(output, root, source=check.command)
        if job.state == jobs.TIMED_OUT:
            errors.append(diagnostics.BuildError(
                category=diagnostics.BUILD,
                message=f"`{check.command}` timed out after {job.timeout}s.",
                likely_cause="the command took longer than its configured budget",
                suggested_action="raise WEB_BUILD_TIMEOUT_SECONDS, or find what is hanging",
                raw=output[-500:]))
        if not result_ok and not errors:
            # The command failed but nothing parsed. Say that rather than
            # reporting a clean run -- an unexplained failure is still a
            # failure, and a silent "ok" here is exactly the false success
            # this whole subsystem exists to prevent.
            errors = [diagnostics.BuildError(
                category=diagnostics.BUILD,
                message=f"`{check.command}` failed with exit {job.exit_code} and no parsable error.",
                likely_cause="the tool reported a failure this analyzer could not interpret",
                raw=output[-500:])]
        runs.append(CheckRun(check.name, check.command, ok=result_ok,
                             exit_code=job.exit_code, errors=errors, job_id=job.id))
    return runs


def _collect(runs: list[CheckRun]) -> list[diagnostics.BuildError]:
    errors: list[diagnostics.BuildError] = []
    for run in runs:
        errors.extend(run.errors)
    return diagnostics.dedupe(errors)


def _install_if_missing(task_id: str, root: Path, errors: list[diagnostics.BuildError]) -> str:
    """The one deterministic command repair: install DECLARED dependencies.

    Only fires when package.json declares dependencies that are not
    installed. Package names parsed out of error text are deliberately not
    used -- that would let generated code choose what gets downloaded.
    """
    if dependencies_installed(root):
        return ""
    wants = [e for e in errors if e.category in {diagnostics.DEPENDENCY, diagnostics.IMPORT, diagnostics.BUILD}]
    if not wants:
        return ""
    return install(task_id, root)


def install(task_id: str, root: Path, *, wait_s: float | None = None) -> str:
    """Install DECLARED dependencies as a background job.

    An install is the longest thing this subsystem does -- minutes on a
    cold cache -- so it runs as a job like everything else. The wait budget
    is the configured install timeout, because a half-installed
    node_modules is worse than waiting for the real one.
    """
    job, error = jobs.start("npm install", Path(root), project=Path(root).name,
                            task_id=task_id, kind=jobs.INSTALL)
    if job is None:
        return ""
    finished = jobs.wait(job.id, timeout=wait_s if wait_s is not None else job.timeout)
    if finished is None or finished.state != jobs.SUCCESS:
        return ""
    _ = error
    return "npm install (declared dependencies were not installed)"


def verify(task_id: str, root: Path, *, auto_fix: bool = True,
           max_attempts: int = MAX_ATTEMPTS_CEILING, patcher=None) -> BuildReport:
    """Check the project, repair what is safe, and report the rest honestly.

    The loop is bounded twice: by `max_attempts`, and by the fact that it
    stops the moment an iteration has no safe repair left to try. It never
    grinds -- a project that needs real code changes gets its structured
    errors returned so ZENO can make them deliberately.
    """
    root = Path(root)
    if not root.is_dir():
        return BuildReport(ok=False, reason=f"{root} does not exist.")

    limit = max(0, min(MAX_ATTEMPTS_CEILING, int(max_attempts)))
    repairs: list[str] = []
    rolled_back = False

    # 1. Static analysis first -- it is free, and reusing coding.repair_project
    #    keeps ONE static repair implementation rather than a second one here.
    if auto_fix and limit:
        static_report = coding.repair_project(root, max_attempts=limit)
        repairs.extend(static_report.applied)
        rolled_back = static_report.rolled_back
        static = static_report.as_dict()
    else:
        issues = coding.check_project(root)
        static = coding.RepairReport(issues=issues, applied=[], attempts=0,
                                     categories=coding.analyze_issues(issues)).as_dict()

    # 2. Real checks. A project with no build tooling is not "unverified" --
    #    a static site genuinely has no build step, and static analysis
    #    already covered it.
    checks = applicable_checks(root)
    if not checks:
        blocking_static = [i for i in static.get("issues", [])
                           if i.get("kind") in {"syntax", "invalid_json", "empty_file", "unsafe_form"}]
        return BuildReport(
            ok=not blocking_static, repairs=repairs, rolled_back=rolled_back,
            static=static, attempts=static.get("attempts", 0),
            reason=("No build tooling in this project -- static checks only."
                    if not blocking_static else "Static checks found blocking defects."),
            errors=[diagnostics.BuildError(
                category=diagnostics.BUILD, message=str(i.get("detail", ""))[:200],
                file=str(i.get("file", "")), likely_cause=str(i.get("suggestion", "")) or "")
                for i in blocking_static])

    if not dependencies_installed(root) and auto_fix:
        note = _install_if_missing(task_id, root, [diagnostics.BuildError(diagnostics.DEPENDENCY, "pre-install")])
        if note:
            repairs.append(note)

    attempts = 0
    runs = run_checks(task_id, root)
    errors = _collect(runs)
    ledger: list[dict[str, Any]] = []

    while auto_fix and attempts < limit and diagnostics.blocking(errors):
        before = len(diagnostics.blocking(errors))

        # 1. DETERMINISTIC first -- cheaper, safer, and needs no model.
        note = _install_if_missing(task_id, root, errors)
        if note:
            attempts += 1
            repairs.append(note)
            ledger.append({"attempt": attempts, "confidence": DETERMINISTIC, "detail": note})
            runs = run_checks(task_id, root)
            errors = _collect(runs)
            if len(diagnostics.blocking(errors)) >= before:
                break
            continue

        # 2. MODEL_GENERATED -- only when a patcher was supplied. Executors
        #    stay model-free: the caller injects the model call, this module
        #    validates and applies the DATA it returns.
        if patcher is None:
            break
        outcome = _model_repair(task_id, root, errors, ledger, attempt=attempts + 1, patcher=patcher)
        if outcome is None:
            break                       # no usable patch -- hand it back
        attempts += 1
        repairs.append(outcome["detail"])
        ledger.append(outcome)
        if not outcome["applied"]:
            # Nothing was written (rejected patch, or the request failed).
            # Re-running the checks would just reproduce the same errors.
            break
        runs = run_checks(task_id, root)
        errors = _collect(runs)
        after = len(diagnostics.blocking(errors))
        if after >= before:
            # The model's change did not help. Undo it -- a repair that does
            # not improve the measured result must not survive.
            restored = _restore(root, outcome.get("checkpoint", ""))
            rolled_back = rolled_back or restored
            ledger[-1]["rolled_back"] = restored
            runs = run_checks(task_id, root)
            errors = _collect(runs)
            break

    hard = diagnostics.blocking(errors)
    ok = not hard
    exhausted = bool(hard) and attempts >= limit
    if ok:
        reason = "All project checks passed."
    elif exhausted:
        reason = (f"AUTO_FIX_EXHAUSTED after {attempts} attempt(s). {len(hard)} error(s) remain "
                  "and the last known-good checkpoint is preserved.")
    else:
        reason = f"{len(hard)} error(s) remain after {attempts} automatic repair attempt(s)."
    if rolled_back:
        reason += " A repair was rolled back for not improving the result."
    return BuildReport(ok=ok, runs=runs, errors=errors, repairs=repairs, attempts=attempts,
                       rolled_back=rolled_back, reason=reason, static=static,
                       ledger=ledger, exhausted=exhausted)


def _checkpoint(root: Path, label: str) -> str:
    """Best-effort restore point before a model-written change."""
    try:
        from reyes_agent import website_builder

        return str(website_builder.checkpoint(root, label).get("version", ""))
    except Exception:  # noqa: BLE001 -- an un-checkpointable project still gets repaired
        return ""


def _restore(root: Path, version: str) -> bool:
    if not version:
        return False
    try:
        from reyes_agent import website_builder

        website_builder.restore_checkpoint(root, version)
        return True
    except Exception:  # noqa: BLE001
        return False


def _model_repair(task_id: str, root: Path, errors: list[diagnostics.BuildError],
                  ledger: list[dict[str, Any]], *, attempt: int, patcher) -> dict[str, Any] | None:
    """Ask for a targeted patch, validate it, checkpoint, apply.

    Returns a ledger entry, or None when nothing usable came back.
    """
    hard = diagnostics.blocking(errors)
    if not hard:
        return None
    context = patching.context_for(root, hard)
    if not context["files"]:
        # Nothing to show the model -- the errors named no readable file, so
        # a patch would be guesswork.
        return None

    task_engine.record_terminal(task_id, f"[repair] asking for a targeted patch (attempt {attempt})")
    try:
        proposed = patcher({
            "errors": [e.as_dict() for e in hard[:6]],
            "sources": context["files"],
            "metadata": context["metadata"],
            "previous_attempts": [
                {k: v for k, v in entry.items() if k in {"attempt", "confidence", "detail", "rolled_back"}}
                for entry in ledger
            ],
        })
    except Exception as exc:  # noqa: BLE001 -- a failed model call is not a crash
        return {"attempt": attempt, "confidence": MODEL_GENERATED, "applied": False,
                "detail": f"the repair request failed: {type(exc).__name__}", "retry": False}

    files = patching.coerce(proposed)
    allowed = {name.replace("\\", "/").casefold() for name in context["named"] if name}
    checkpoint = _checkpoint(root, f"before model repair attempt {attempt}")
    result = patching.apply(root, files, allowed_files=allowed)
    if not result.ok:
        return {"attempt": attempt, "confidence": MODEL_GENERATED, "applied": False,
                "detail": f"patch rejected: {result.reason}", "checkpoint": checkpoint,
                "retry": False}
    return {"attempt": attempt, "confidence": MODEL_GENERATED, "applied": True,
            "detail": f"applied a targeted patch to {', '.join(result.applied)}",
            "checkpoint": checkpoint, "files": result.applied}
