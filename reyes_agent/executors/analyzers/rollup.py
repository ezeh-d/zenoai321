"""Rollup build output.

Rollup reports a short headline then an indented detail block, and its
location line uses `file (line:col)` rather than the `file:line:col` shape
every other tool uses -- which is precisely why it needs its own parser.
"""

from __future__ import annotations

import re
from pathlib import Path

from reyes_agent.executors import analyzers
from reyes_agent.executors.diagnostics import (BUILD, CONFIGURATION, DEPENDENCY, ERROR,
                                               IMPORT, JAVASCRIPT, WARNING, BuildError)

TOOL = "rollup"

# [!] Error: Could not resolve './missing' from src/main.js
_COULD_NOT_RESOLVE = re.compile(
    r"Could not resolve\s+['\"](?P<target>[^'\"]+)['\"](?:\s+from\s+(?P<from>\S+))?", re.I)
# [!] (plugin commonjs) SyntaxError: Unexpected token
_PLUGIN = re.compile(r"\(plugin\s+(?P<plugin>[\w@/.-]+)\)\s*(?P<msg>.+)$", re.I)
# src/main.js (12:4)   -- rollup's own location shape
_LOCATION = re.compile(r"^\s*(?P<file>[^\s(][^(]*?)\s*\((?P<line>\d+):(?P<col>\d+)\)\s*$")
# [!] Error: Unexpected token (Note that you need plugins to import files that are not JavaScript)
_UNEXPECTED = re.compile(r"(?:Error:\s*)?Unexpected token(?:\s*\((?P<note>[^)]*)\))?", re.I)
_CIRCULAR = re.compile(r"Circular dependency:\s*(?P<chain>.+)$", re.I)
_BANG = re.compile(r"^\s*\[!\]\s*(?P<msg>.+)$")

_FINGERPRINTS = ("[!]", "rollup", "could not resolve", "(plugin ", "circular dependency")


def claims(output: str) -> bool:
    lowered = str(output or "").lower()
    # "[!]" alone is rollup's signature prefix; the rest guard against
    # claiming output that merely mentions the word rollup in passing.
    return "[!]" in lowered or ("rollup" in lowered and any(m in lowered for m in _FINGERPRINTS))


def _relative(file: str, root: Path | None) -> str:
    from reyes_agent.executors.diagnostics import _relative as shared

    return shared(file, root)


def parse(output: str, root: Path | None = None) -> list[BuildError]:
    errors: list[BuildError] = []
    lines = str(output or "").splitlines()
    pending: BuildError | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        # A pending error is waiting for rollup's `file (line:col)` line.
        if pending is not None:
            location = _LOCATION.match(line)
            if location:
                pending.file = _relative(location.group("file"), root)
                pending.line = int(location.group("line"))
                pending.column = int(location.group("col"))
                errors.append(pending)
                pending = None
                continue
            errors.append(pending)
            pending = None

        circular = _CIRCULAR.search(line)
        if circular:
            # A warning, not a failure -- reported so it is visible without
            # being treated as something to repair.
            errors.append(BuildError(
                category=BUILD, message=f"Circular dependency: {circular.group('chain').strip()}",
                likely_cause="two or more modules import each other",
                suggested_action="move the shared code into a third module",
                severity=WARNING, raw=line, tool=TOOL))
            continue

        resolve = _COULD_NOT_RESOLVE.search(line)
        if resolve:
            target = resolve.group("target")
            local = target.startswith(".") or target.startswith("/")
            pending = BuildError(
                category=IMPORT if local else DEPENDENCY, message=line.strip().lstrip("[!] ").strip(),
                file=_relative(resolve.group("from") or "", root),
                likely_cause=("the imported path does not exist in the project"
                              if local else f"the package '{target}' is not installed"),
                suggested_action=("create the file or correct the import path"
                                  if local else f"add '{target}' to package.json and install it"),
                code=target, raw=line, tool=TOOL)
            # Deliberately NOT appended yet even when `from <file>` gave us a
            # filename: rollup prints `file (line:col)` on the NEXT line, and
            # appending here threw that position away.
            continue

        plugin = _PLUGIN.search(line)
        if plugin:
            message = plugin.group("msg").strip()
            pending = BuildError(
                category=JAVASCRIPT if "syntaxerror" in message.lower() else CONFIGURATION,
                message=message,
                likely_cause=f"the rollup plugin '{plugin.group('plugin')}' failed on this input",
                suggested_action="check that plugin's configuration and the file it was given",
                code=plugin.group("plugin"), raw=line, tool=TOOL)
            continue

        bang = _BANG.match(line)
        if bang:
            message = bang.group("msg").strip()
            unexpected = _UNEXPECTED.search(message)
            pending = BuildError(
                category=JAVASCRIPT if unexpected else BUILD, message=message,
                likely_cause=("rollup could not parse this file -- it may need a plugin for this file type"
                              if unexpected else "rollup stopped with an error"),
                severity=ERROR, raw=line, tool=TOOL)
            continue

    if pending is not None:
        errors.append(pending)
    return errors


analyzers.register(TOOL, claims, parse)
