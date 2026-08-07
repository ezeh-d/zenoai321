"""Vitest test output.

A failing test is not a build error, and flattening it into one loses the
part that matters: which test, what it expected, and what it got instead.
So this analyzer keeps the test name in `code`, the expected/received pair
in `likely_cause`, and points `file`/`line` at the assertion itself.
"""

from __future__ import annotations

import re
from pathlib import Path

from reyes_agent.executors import analyzers
from reyes_agent.executors.diagnostics import (BUILD, DEPENDENCY, ERROR, IMPORT,
                                               RUNTIME, BuildError)

TOOL = "vitest"

# FAIL  src/math.test.ts > adds numbers
_FAIL = re.compile(r"^\s*(?:FAIL|×|✗)\s+(?P<file>\S+?)(?:\s*[>›]\s*(?P<test>.+?))?\s*$")
# AssertionError: expected 3 to be 4
_ASSERTION = re.compile(r"^\s*(?P<kind>AssertionError|Error):\s*(?P<msg>.+)$")
_EXPECTED = re.compile(r"^\s*[-+]?\s*Expected:?\s*(?P<value>.+)$", re.I)
_RECEIVED = re.compile(r"^\s*[-+]?\s*Received:?\s*(?P<value>.+)$", re.I)
# ❯ src/math.test.ts:12:20
_LOCATION = re.compile(r"^\s*[❯>]?\s*(?P<file>[^\s:]+\.[jt]sx?):(?P<line>\d+):(?P<col>\d+)\s*$")
_TIMEOUT = re.compile(r"Test timed out in (?P<ms>\d+)\s*ms", re.I)
_HOOK = re.compile(r"(?P<hook>beforeEach|afterEach|beforeAll|afterAll)\b.*?(?:failed|error)", re.I)
_UNHANDLED = re.compile(r"Unhandled (?:Rejection|Error)", re.I)
_CANNOT_FIND = re.compile(r"(?:Cannot find module|Failed to load url|Failed to resolve import)\s*['\"]?(?P<target>[^'\"\s]+)", re.I)
_SUMMARY = re.compile(r"Tests?\s+(?P<failed>\d+)\s+failed", re.I)

_FINGERPRINTS = ("vitest", "test files", "❯", "assertionerror",
                 "tests  ", "test timed out", "describe(", "vite.config")


def claims(output: str) -> bool:
    text = str(output or "")
    lowered = text.lower()
    if "vitest" in lowered:
        return True
    if _SUMMARY.search(lowered) or ("test files" in lowered and "fail" in lowered):
        return True
    # Real vitest output often names neither itself nor a summary -- the
    # recognisable parts are the `FAIL <file> > <test>` header, the ❯ stack
    # marker and the timeout line. Without these the analyzer silently
    # declined its own output.
    if _TIMEOUT.search(text):
        return True
    has_fail_header = any(_FAIL.match(line) and re.search(r"\.(?:test|spec)\.[jt]sx?$|\.[jt]sx?$", (_FAIL.match(line).group("file") or ""))
                          for line in text.splitlines() if line.strip().upper().startswith(("FAIL", "×", "✗")))
    return bool(has_fail_header and ("assertionerror" in lowered or "❯" in text or "expected" in lowered))


def _relative(file: str, root: Path | None) -> str:
    from reyes_agent.executors.diagnostics import _relative as shared

    return shared(file, root)


def parse(output: str, root: Path | None = None) -> list[BuildError]:
    errors: list[BuildError] = []
    lines = str(output or "").splitlines()

    current_file = ""
    current_test = ""
    pending: BuildError | None = None
    expected = received = ""

    def flush() -> None:
        nonlocal pending, expected, received
        if pending is None:
            return
        if expected or received:
            pending.likely_cause = (f"expected {expected.strip()}, received {received.strip()}"
                                    if expected and received else pending.likely_cause)
        errors.append(pending)
        pending = None
        expected = received = ""

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        fail = _FAIL.match(line)
        if fail and re.search(r"\.[jt]sx?$|\.test\.|\.spec\.", fail.group("file") or ""):
            flush()
            current_file = _relative(fail.group("file"), root)
            current_test = (fail.group("test") or "").strip()
            continue

        timeout = _TIMEOUT.search(line)
        if timeout:
            flush()
            errors.append(BuildError(
                category=RUNTIME, message=line.strip(), file=current_file,
                likely_cause=f"the test did not finish within {timeout.group('ms')}ms",
                suggested_action="raise the timeout or fix what is hanging -- often an un-awaited promise",
                code=current_test, raw=line, tool=TOOL))
            continue

        missing = _CANNOT_FIND.search(line)
        if missing:
            flush()
            target = missing.group("target")
            local = target.startswith(".") or target.startswith("/")
            errors.append(BuildError(
                category=IMPORT if local else DEPENDENCY, message=line.strip(), file=current_file,
                likely_cause=("the test imports a path that does not exist"
                              if local else f"the test imports '{target}', which is not installed"),
                suggested_action=("correct the import path" if local else f"install '{target}'"),
                code=target, raw=line, tool=TOOL))
            continue

        hook = _HOOK.search(line)
        if hook:
            flush()
            errors.append(BuildError(
                category=RUNTIME, message=line.strip(), file=current_file,
                likely_cause=f"the {hook.group('hook')} hook threw, so its tests could not run",
                suggested_action="fix the hook before looking at the tests under it",
                code=current_test, raw=line, tool=TOOL))
            continue

        if _UNHANDLED.search(line):
            flush()
            errors.append(BuildError(
                category=RUNTIME, message=line.strip(), file=current_file,
                likely_cause="a promise rejected with nothing catching it",
                suggested_action="await the call or attach a .catch",
                code=current_test, raw=line, tool=TOOL))
            continue

        assertion = _ASSERTION.match(line)
        if assertion:
            flush()
            pending = BuildError(
                category=BUILD, message=f"{assertion.group('kind')}: {assertion.group('msg').strip()}",
                file=current_file, likely_cause="the assertion did not hold",
                suggested_action="fix the code under test, or the expectation if it is wrong",
                severity=ERROR, code=current_test, raw=line, tool=TOOL)
            continue

        if pending is not None:
            got_expected = _EXPECTED.match(line)
            if got_expected:
                expected = got_expected.group("value")
                continue
            got_received = _RECEIVED.match(line)
            if got_received:
                received = got_received.group("value")
                continue
            location = _LOCATION.match(line)
            if location:
                pending.file = _relative(location.group("file"), root) or pending.file
                pending.line = int(location.group("line"))
                pending.column = int(location.group("col"))
                flush()
                continue

    flush()
    return errors


analyzers.register(TOOL, claims, parse)
