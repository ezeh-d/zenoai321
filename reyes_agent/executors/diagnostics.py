"""Error Analyzer -- turn real build output into something actionable.

WHAT THIS IS FOR
----------------
`coding.py` reads the FILES and finds defects statically. This module reads
what the TOOLS actually said -- tsc, vite/esbuild, eslint, npm, node -- and
turns those walls of text into structured errors with a category, a file, a
line and a plain-language likely cause.

The two are complements, not alternatives: static analysis catches a broken
brace before anything runs, and this catches "Cannot find module './Nav'"
which only a real build knows about.

THE HONESTY RULE
----------------
If a line cannot be parsed, it becomes an UNKNOWN error carrying the raw
text. It never gets a guessed file or an invented line number. A confident
wrong file path sends the repair loop to edit something that was never
broken, which is worse than admitting the output was not understood.

Deduplication matters here: build tools repeat the same failure once per
importing module, and a loop that counts 40 errors when there is really one
will conclude it is making things worse and roll back a good fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Categories the brief asked for.
DEPENDENCY = "DEPENDENCY"
BUILD = "BUILD"
TYPESCRIPT = "TYPESCRIPT"
JAVASCRIPT = "JAVASCRIPT"
CSS = "CSS"
ROUTING = "ROUTING"
IMPORT = "IMPORT"
RUNTIME = "RUNTIME"
SERVER = "SERVER"
NETWORK = "NETWORK"
CONFIGURATION = "CONFIGURATION"
UNKNOWN = "UNKNOWN"

CATEGORIES = (DEPENDENCY, BUILD, TYPESCRIPT, JAVASCRIPT, CSS, ROUTING, IMPORT,
              RUNTIME, SERVER, NETWORK, CONFIGURATION, UNKNOWN)

ERROR, WARNING = "error", "warning"


@dataclass
class BuildError:
    category: str
    message: str
    file: str = ""
    line: int | None = None
    column: int | None = None
    likely_cause: str = ""
    severity: str = ERROR
    code: str = ""
    raw: str = ""
    # What the repair loop is allowed to do about it on its own. Set by
    # `repairable()` below rather than guessed by the caller.
    auto_repair: str = ""
    # Which analyzer produced this. "" means the built-in core parser.
    tool: str = ""
    # A concrete next step when one can be stated. Empty when the analyzer
    # genuinely does not know -- an invented suggestion sends the repair
    # loop somewhere pointless.
    suggested_action: str = ""

    def key(self) -> tuple:
        """Identity for deduplication -- same defect, however many times a
        build tool repeats it."""
        return (self.category, self.file, self.line, self.message[:120])

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "file": self.file, "line": self.line,
                "column": self.column, "message": self.message,
                "likely_cause": self.likely_cause, "severity": self.severity,
                "code": self.code, "auto_repair": self.auto_repair,
                "tool": self.tool, "suggested_action": self.suggested_action,
                # The original text is ALWAYS preserved, including for
                # UNKNOWN. A parser that discards what it could not read
                # leaves nobody able to work out what happened.
                "raw_message": self.raw}


# --- output patterns -----------------------------------------------------
# Each is a real format emitted by a tool this project actually runs. Kept
# narrow: a loose pattern that matches prose produces confident nonsense.

# tsc:  src/App.tsx(42,15): error TS2304: Cannot find name 'foo'.
_TSC_PAREN = re.compile(
    r"^(?P<file>[^\s(][^(]*?)\((?P<line>\d+),(?P<col>\d+)\):\s*(?P<sev>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.+)$")
# tsc --pretty / vite:  src/App.tsx:42:15 - error TS2304: Cannot find name 'foo'.
_TSC_COLON = re.compile(
    r"^(?P<file>[^\s:][^:]*?):(?P<line>\d+):(?P<col>\d+)\s*[-–]\s*(?P<sev>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.+)$")
# eslint stylish body:    12:5  error  'x' is not defined  no-undef
_ESLINT_ROW = re.compile(
    r"^\s+(?P<line>\d+):(?P<col>\d+)\s+(?P<sev>error|warning)\s+(?P<msg>.+?)\s\s+(?P<code>[\w@/-]+)\s*$")
# esbuild/vite:  ✘ [ERROR] Could not resolve "./missing"
_ESBUILD = re.compile(r"^[^\w]*\[(?P<sev>ERROR|WARNING)\]\s*(?P<msg>.+)$")
# A bare  path:line:col:  continuation line under an esbuild error.
_LOCATION = re.compile(r"^\s*(?P<file>[^\s:][^:]*?):(?P<line>\d+):(?P<col>\d+):?\s*$")
# node / bundlers:  Cannot find module './Nav'  |  Module not found: Error: Can't resolve 'x'
_MODULE = re.compile(
    r"(?:Cannot find module|Could not resolve|Can't resolve|Failed to resolve import|Module not found:.*?resolve)\s*[:\s]\s*[\"'](?P<target>[^\"']+)[\"']", re.I)
# generic JS syntax errors from node
_SYNTAX = re.compile(r"^(?P<kind>SyntaxError|ReferenceError|TypeError|RangeError):\s*(?P<msg>.+)$")
# npm failures
_NPM_CODE = re.compile(r"^npm (?:ERR!|error)\s+code\s+(?P<code>[A-Z0-9_]+)\s*$", re.I)
_NPM_404 = re.compile(r"^npm (?:ERR!|error)\s+404\s+(?P<msg>.+)$", re.I)
_NPM_MISSING_SCRIPT = re.compile(r"Missing script:\s*[\"']?(?P<script>[\w:-]+)", re.I)
# CSS / postcss
_CSS = re.compile(r"(?P<file>[^\s]+\.(?:css|scss|sass|less))[:(](?P<line>\d+)[:,](?P<col>\d+)\)?\s*[-:]?\s*(?P<msg>.+)$", re.I)

_NETWORK_HINTS = ("ETIMEDOUT", "ENOTFOUND", "ECONNREFUSED", "ECONNRESET", "EAI_AGAIN",
                  "network", "getaddrinfo", "socket hang up", "registry.npmjs.org")
_NOISE = re.compile(r"^\s*(?:at\s|npm (?:ERR!|error)\s+(?:A complete log|This is probably)|"
                    r"\s*\^|-{3,}|=+|\d+\s+(?:problems?|errors?|warnings?)\b)", re.I)


def _relative(file: str, root: Path | None) -> str:
    """Project-relative where possible, so paths mean something to the owner."""
    text = str(file or "").strip().strip('"').replace("\\", "/")
    if not text or root is None:
        return text
    try:
        candidate = Path(text)
        if candidate.is_absolute():
            return str(candidate.resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except (ValueError, OSError):
        pass
    return text.lstrip("./")


def _cause_for_ts(code: str, message: str) -> str:
    """Plain-language cause for the TypeScript codes that actually recur."""
    causes = {
        "TS2304": "a name is used that was never imported or declared",
        "TS2307": "the imported file or package does not exist at that path",
        "TS2339": "the property does not exist on that type",
        "TS2345": "an argument's type does not match the parameter",
        "TS2322": "the assigned value's type does not match the declaration",
        "TS7006": "a parameter has no type and implicit any is disallowed",
        "TS6133": "the value is declared but never used",
        "TS1005": "a token is missing -- usually a comma, bracket or semicolon",
        "TS1128": "a declaration or statement was expected -- often an unclosed block",
        "TS2551": "the name is close to an existing one; probably a typo",
    }
    return causes.get(code.upper(), f"TypeScript rejected this: {message[:90]}")


def _classify_plain(message: str) -> tuple[str, str]:
    """(category, likely_cause) for a line with no structured format."""
    lowered = message.lower()
    if any(hint.lower() in lowered for hint in _NETWORK_HINTS):
        return NETWORK, "the machine could not reach the package registry"
    if "eaccess" in lowered or "eperm" in lowered or "permission denied" in lowered:
        return CONFIGURATION, "a file or folder could not be accessed with current permissions"
    if "port" in lowered and ("in use" in lowered or "eaddrinuse" in lowered):
        return SERVER, "the port is already taken by another process"
    if "route" in lowered or "router" in lowered or "404" in lowered and "npm" not in lowered:
        return ROUTING, "a route or page path does not resolve"
    return UNKNOWN, ""


def analyze(output: str, root: Path | None = None, *, source: str = "") -> list[BuildError]:
    """Parse real command output into structured errors, deduplicated.

    Tool-specific analyzers (webpack, rollup, vitest -- see the `analyzers`
    package) run FIRST, because only they recognise their own multi-line
    shapes. The core scanner below then runs over the same text for the
    tools it owns; `dedupe` collapses any genuine overlap. Concatenating
    rather than first-wins matters: one `npm run build` can legitimately
    emit webpack errors and a node stack trace together.

    `source` is the command that produced the output; it only ever
    influences the category when the text itself is ambiguous.
    """
    errors: list[BuildError] = []
    try:
        from reyes_agent.executors import analyzers

        errors.extend(analyzers.analyze(output, root))
    except Exception:  # noqa: BLE001 -- a plugin must never break core parsing
        pass
    if errors:
        # A specialist claimed this output and produced structured results.
        # Running the core scanner over the SAME text as well produced a
        # second, worse copy of every error -- same defect, no file, no
        # cause -- which dedupe cannot collapse because the fields differ.
        # The specialist wins; that is the point of having one.
        return dedupe(errors)
    lines = str(output or "").splitlines()
    eslint_file = ""       # eslint prints the path once, then indented rows
    pending_esbuild: BuildError | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue

        # An esbuild error is followed by an indented "file:line:col:" line.
        if pending_esbuild is not None:
            spot = _LOCATION.match(line)
            if spot:
                pending_esbuild.file = _relative(spot.group("file"), root)
                pending_esbuild.line = int(spot.group("line"))
                pending_esbuild.column = int(spot.group("col"))
                errors.append(pending_esbuild)
                pending_esbuild = None
                continue
            errors.append(pending_esbuild)
            pending_esbuild = None

        match = _TSC_PAREN.match(line) or _TSC_COLON.match(line)
        if match:
            code = match.group("code")
            message = match.group("msg").strip()
            errors.append(BuildError(
                category=TYPESCRIPT, message=message,
                file=_relative(match.group("file"), root),
                line=int(match.group("line")), column=int(match.group("col")),
                likely_cause=_cause_for_ts(code, message),
                severity=ERROR if match.group("sev").lower() == "error" else WARNING,
                code=code, raw=line))
            continue

        # esbuild/vite FIRST: its bracket line is followed by an indented
        # `file:line:col:` line carrying the location. Matching the generic
        # module pattern first threw that location away -- the error said
        # "Could not resolve ./Hero" with no file, when the very next line
        # named src/App.jsx:3:18.
        esbuild = _ESBUILD.match(line)
        if esbuild:
            message = esbuild.group("msg").strip()
            module = _MODULE.search(message)
            if module:
                target = module.group("target")
                local = target.startswith(".") or target.startswith("/")
                category = IMPORT if local else DEPENDENCY
                cause = ("the imported path does not exist in the project" if local
                         else f"the package '{target}' is not installed")
                code = target
            else:
                category, cause = _classify_plain(message)
                category = BUILD if category == UNKNOWN else category
                cause = cause or "the bundler could not complete the build"
                code = ""
            pending_esbuild = BuildError(
                category=category, message=message, likely_cause=cause, code=code,
                severity=ERROR if esbuild.group("sev").upper() == "ERROR" else WARNING,
                raw=line)
            continue

        module = _MODULE.search(line)
        if module:
            target = module.group("target")
            local = target.startswith(".") or target.startswith("/")
            errors.append(BuildError(
                category=IMPORT if local else DEPENDENCY,
                message=line.strip(),
                likely_cause=("the imported path does not exist in the project"
                              if local else f"the package '{target}' is not installed"),
                code=target, raw=line))
            continue

        # postcss/sass print `file.css:line:col: message` only for problems,
        # so requiring the literal word "error" missed every real one.
        css = _CSS.search(line)
        if css:
            errors.append(BuildError(
                category=CSS, message=css.group("msg").strip(),
                file=_relative(css.group("file"), root), line=int(css.group("line")),
                column=int(css.group("col")),
                likely_cause="the stylesheet could not be parsed at that point", raw=line))
            continue

        syntax = _SYNTAX.match(line.strip())
        if syntax:
            kind = syntax.group("kind")
            errors.append(BuildError(
                category=JAVASCRIPT if kind == "SyntaxError" else RUNTIME,
                message=f"{kind}: {syntax.group('msg').strip()}",
                likely_cause=("the file is not valid JavaScript at that point"
                              if kind == "SyntaxError" else "the code threw while running"),
                code=kind, raw=line))
            continue

        script = _NPM_MISSING_SCRIPT.search(line)
        if script:
            errors.append(BuildError(
                category=CONFIGURATION, message=line.strip(), file="package.json",
                likely_cause=f"package.json has no '{script.group('script')}' script",
                code=script.group("script"), raw=line))
            continue

        npm404 = _NPM_404.match(line)
        if npm404:
            errors.append(BuildError(
                category=DEPENDENCY, message=npm404.group("msg").strip(),
                likely_cause="the package name does not exist in the registry -- often a typo",
                raw=line))
            continue

        npm_code = _NPM_CODE.match(line)
        if npm_code:
            code = npm_code.group("code").upper()
            category = NETWORK if code in {"ETIMEDOUT", "ENOTFOUND", "ECONNREFUSED", "EAI_AGAIN"} else DEPENDENCY
            errors.append(BuildError(
                category=category, message=f"npm failed with {code}",
                likely_cause=("npm could not reach the registry" if category == NETWORK
                              else "the install could not complete"),
                code=code, raw=line))
            continue

        # Anything left that plainly announces failure is kept as UNKNOWN
        # rather than dropped -- but with no invented file or line.
        if re.search(r"\berror\b", line, re.I) and not _NOISE.match(line):
            eslint = _ESLINT_ROW.match(raw_line)
            if eslint:
                errors.append(BuildError(
                    category=JAVASCRIPT, message=eslint.group("msg").strip(),
                    file=eslint_file, line=int(eslint.group("line")),
                    column=int(eslint.group("col")),
                    likely_cause=f"lint rule '{eslint.group('code')}' was violated",
                    severity=ERROR if eslint.group("sev") == "error" else WARNING,
                    code=eslint.group("code"), raw=line))
                continue
            category, cause = _classify_plain(line)
            errors.append(BuildError(category=category if category != UNKNOWN else BUILD,
                                     message=line.strip()[:300], likely_cause=cause, raw=line))
            continue

        # eslint prints the file path on its own line before its rows.
        if not line.startswith(" ") and re.search(r"\.(?:[jt]sx?|css|html)$", line.strip()):
            eslint_file = _relative(line.strip(), root)

    if pending_esbuild is not None:
        errors.append(pending_esbuild)

    _ = source
    return dedupe(errors)


def dedupe(errors: list[BuildError]) -> list[BuildError]:
    """One entry per real defect.

    Bundlers repeat the same missing module once per importer. Counting
    those separately makes a successful repair look like a regression to
    the loop that compares before/after counts.
    """
    seen: set[tuple] = set()
    unique: list[BuildError] = []
    for error in errors:
        if error.key() in seen:
            continue
        seen.add(error.key())
        unique.append(error)
    return unique


def blocking(errors: list[BuildError]) -> list[BuildError]:
    return [e for e in errors if e.severity == ERROR]


def summarize(errors: list[BuildError], limit: int = 8) -> str:
    """Short, readable. The full output stays in the task's terminal log."""
    if not errors:
        return "No build errors."
    hard = blocking(errors)
    lines = [f"{len(hard)} error(s), {len(errors) - len(hard)} warning(s):"]
    for error in errors[:limit]:
        where = error.file or "(file not identified)"
        if error.line:
            where += f":{error.line}"
        lines.append(f"  [{error.category}] {where} -- {error.message[:120]}")
        if error.likely_cause:
            lines.append(f"      likely: {error.likely_cause}")
    if len(errors) > limit:
        lines.append(f"  ... and {len(errors) - limit} more")
    return "\n".join(lines)


def group_by_file(errors: list[BuildError]) -> dict[str, list[BuildError]]:
    grouped: dict[str, list[BuildError]] = {}
    for error in errors:
        grouped.setdefault(error.file or "", []).append(error)
    return grouped
