"""Webpack build output.

Webpack's error format is multi-line and positional: a header line naming
the module, then the reason, then often a stack or a "resolved as" trail.
Parsing it line-by-line in a shared scanner is what makes patterns from
other tools collide, so it lives here with its own small state machine.
"""

from __future__ import annotations

import re
from pathlib import Path

from reyes_agent.executors import analyzers
from reyes_agent.executors.diagnostics import (BUILD, CONFIGURATION, DEPENDENCY, ERROR,
                                               IMPORT, JAVASCRIPT, WARNING, BuildError)

TOOL = "webpack"

# ERROR in ./src/App.js 12:4-30
_HEADER = re.compile(r"^(?:ERROR|WARNING)\s+in\s+(?P<file>\S+?)(?:\s+(?P<line>\d+):(?P<col>\d+)(?:-\d+)?)?\s*$")
# Module not found: Error: Can't resolve './Missing' in '/abs/path'
_NOT_FOUND = re.compile(r"Module not found:\s*(?:Error:\s*)?Can't resolve\s*['\"](?P<target>[^'\"]+)['\"]", re.I)
# Module parse failed: Unexpected token (12:4)
_PARSE_FAILED = re.compile(r"Module parse failed:\s*(?P<msg>.+?)(?:\s*\((?P<line>\d+):(?P<col>\d+)\))?\s*$", re.I)
# Module build failed (from ./node_modules/babel-loader/lib/index.js):
_LOADER = re.compile(r"Module build failed\s*\(from\s*(?P<loader>[^)]+)\)", re.I)
# SyntaxError: /abs/file.js: Unexpected token (12:4)
_SYNTAX_AT = re.compile(r"^(?P<kind>\w*(?:Syntax|Type|Reference)Error):\s*(?P<file>[^:]+):\s*(?P<msg>.+?)(?:\s*\((?P<line>\d+):(?P<col>\d+)\))?\s*$")
_PLUGIN = re.compile(r"^\s*(?:Error:\s*)?\[(?P<plugin>[\w@/.-]+)\]\s*(?P<msg>.+)$")
_COMPILE_FAILED = re.compile(r"(?:Compilation failed|webpack.*compiled with \d+ errors?)", re.I)

_FINGERPRINTS = ("module not found", "module parse failed", "module build failed",
                 "webpack compiled", "compiled with", "erroneous webpack", "webpack-cli",
                 "error in ./", "warning in ./")


def claims(output: str) -> bool:
    lowered = str(output or "").lower()
    return any(mark in lowered for mark in _FINGERPRINTS)


def _relative(file: str, root: Path | None) -> str:
    from reyes_agent.executors.diagnostics import _relative as shared

    return shared(file, root)


def parse(output: str, root: Path | None = None) -> list[BuildError]:
    errors: list[BuildError] = []
    lines = str(output or "").splitlines()
    current_file = ""
    current_line: int | None = None
    current_col: int | None = None
    severity = ERROR

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        header = _HEADER.match(line.strip())
        if header:
            # Webpack names the module first; every reason under it belongs
            # to that file until the next header.
            current_file = _relative(header.group("file"), root)
            current_line = int(header.group("line")) if header.group("line") else None
            current_col = int(header.group("col")) if header.group("col") else None
            severity = WARNING if line.strip().upper().startswith("WARNING") else ERROR
            continue

        not_found = _NOT_FOUND.search(line)
        if not_found:
            target = not_found.group("target")
            local = target.startswith(".") or target.startswith("/")
            errors.append(BuildError(
                category=IMPORT if local else DEPENDENCY,
                message=line.strip(), file=current_file, line=current_line, column=current_col,
                likely_cause=("the imported path does not exist relative to that file"
                              if local else f"the package '{target}' is not installed"),
                suggested_action=("create the file or correct the import path"
                                  if local else f"add '{target}' to package.json and install it"),
                severity=severity, code=target, raw=line, tool=TOOL))
            continue

        loader = _LOADER.search(line)
        if loader:
            errors.append(BuildError(
                category=CONFIGURATION, message=line.strip(), file=current_file,
                line=current_line, column=current_col,
                likely_cause=f"the loader {loader.group('loader').strip()} rejected this module",
                suggested_action="check the loader's options in the webpack config",
                severity=severity, raw=line, tool=TOOL))
            continue

        parse_failed = _PARSE_FAILED.search(line)
        if parse_failed:
            errors.append(BuildError(
                category=BUILD, message=parse_failed.group("msg").strip(), file=current_file,
                line=int(parse_failed.group("line")) if parse_failed.group("line") else current_line,
                column=int(parse_failed.group("col")) if parse_failed.group("col") else current_col,
                likely_cause="webpack has no loader configured for this file type, or the file is malformed",
                suggested_action="add the right loader for this extension, or fix the syntax",
                severity=severity, raw=line, tool=TOOL))
            continue

        syntax = _SYNTAX_AT.match(line.strip())
        if syntax:
            errors.append(BuildError(
                category=JAVASCRIPT, message=f"{syntax.group('kind')}: {syntax.group('msg').strip()}",
                file=_relative(syntax.group("file"), root) or current_file,
                line=int(syntax.group("line")) if syntax.group("line") else current_line,
                column=int(syntax.group("col")) if syntax.group("col") else current_col,
                likely_cause="the file is not valid JavaScript at that point",
                suggested_action="fix the syntax at the reported position",
                severity=severity, code=syntax.group("kind"), raw=line, tool=TOOL))
            continue

        plugin = _PLUGIN.match(line)
        if plugin and current_file:
            errors.append(BuildError(
                category=CONFIGURATION, message=plugin.group("msg").strip(), file=current_file,
                line=current_line, column=current_col,
                likely_cause=f"the {plugin.group('plugin')} plugin reported a problem",
                severity=severity, code=plugin.group("plugin"), raw=line, tool=TOOL))
            continue

    if not errors and _COMPILE_FAILED.search(str(output or "")):
        # Webpack said it failed but named nothing this parser understood.
        # Reported as BUILD with the raw text rather than as a clean run.
        errors.append(BuildError(
            category=BUILD, message="webpack reported a failed compilation",
            likely_cause="webpack failed without an error this analyzer could attribute to a file",
            raw=str(output or "")[-500:], tool=TOOL))
    return errors


analyzers.register(TOOL, claims, parse)
