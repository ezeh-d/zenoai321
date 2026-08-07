"""Coding Executor -- does the generated project actually hold together?

Three jobs, all evidence-based:

1. `check_project` reads what was really written and reports concrete
   defects: a stylesheet the HTML references that does not exist, a script
   that will not parse, an empty file, malformed JSON.
2. `autofix` applies only corrections that cannot destroy work -- currently
   repointing a reference at the matching file that IS in the project.
   Anything needing new content is reported instead of silently patched,
   because an empty `styles.css` would pass a file-exists check while the
   page renders unstyled, which is precisely the kind of false success this
   whole change exists to remove.
3. `missing_dependencies` names what the project needs and the machine does
   not have, so ZENO can say "Node.js isn't installed" instead of pretending.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reyes_agent.executors import terminal

# Local asset references in HTML. Remote URLs and data: URIs are skipped --
# they are not this project's files to verify.
_REF_PATTERNS = (
    re.compile(r"""<link[^>]+href\s*=\s*["']([^"']+)["']""", re.I),
    re.compile(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""", re.I),
    re.compile(r"""<img[^>]+src\s*=\s*["']([^"']+)["']""", re.I),
)
_REMOTE = re.compile(r"^(https?:)?//|^data:|^mailto:|^#|^javascript:", re.I)
_ESM = re.compile(r"^\s*(import\s|export\s|import\()", re.M)
MAX_AUTO_FIX_ATTEMPTS = 5

_CATEGORY = {
    "missing_reference": "asset_reference",
    "syntax": "syntax",
    "invalid_json": "configuration",
    "empty_file": "content",
    "structure": "structure",
    "unsafe_form": "security",
    "undeclared_demo": "safety_notice",
}
_SEVERITY = {
    "unsafe_form": 10,
    "syntax": 6,
    "invalid_json": 6,
    "empty_file": 5,
    "missing_reference": 4,
    "structure": 4,
    "undeclared_demo": 1,
}


@dataclass
class Issue:
    kind: str          # missing_reference | syntax | empty_file | invalid_json | structure
    file: str
    detail: str
    fixable: bool = False
    suggestion: str = ""

    def as_dict(self) -> dict[str, str | bool]:
        return {"kind": self.kind, "file": self.file, "detail": self.detail,
                "category": _CATEGORY.get(self.kind, "other"),
                "fixable": self.fixable, "suggestion": self.suggestion}


@dataclass
class RepairReport:
    """Evidence from one bounded, non-destructive repair attempt sequence."""

    issues: list[Issue]
    applied: list[str]
    attempts: int
    categories: dict[str, int]
    rolled_back: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "issues": [issue.as_dict() for issue in self.issues],
            "applied": list(self.applied), "attempts": self.attempts,
            "categories": dict(self.categories), "rolled_back": self.rolled_back,
            "reason": self.reason,
        }


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _balanced(text: str) -> str:
    """Bracket balance check -- the fallback when no real parser is around.

    Deliberately reported as a weaker signal than a parser: it strips
    strings and comments first, but it is a heuristic and is described
    that way in the issue text rather than being presented as a syntax check.
    """
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    cleaned = re.sub(r"(^|[^:])//[^\n]*", r"\1", cleaned)
    cleaned = re.sub(r"'(\\.|[^'\\\n])*'", "''", cleaned)
    cleaned = re.sub(r'"(\\.|[^"\\\n])*"', '""', cleaned)
    cleaned = re.sub(r"`(\\.|[^`\\])*`", "``", cleaned, flags=re.S)
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for char in cleaned:
        if char in "([{":
            stack.append(char)
        elif char in pairs:
            if not stack or stack.pop() != pairs[char]:
                return f"unbalanced '{char}'"
    return f"{len(stack)} unclosed bracket(s)" if stack else ""


def _node_check(path: Path) -> str:
    """Real JS parse via Node when it exists. Returns '' when clean."""
    if not terminal.tool_available("node"):
        return ""
    text = _read(path)
    target = path
    tmp: Path | None = None
    try:
        if _ESM.search(text) and path.suffix.lower() == ".js":
            # `node --check` parses .js as CommonJS, so ES module syntax
            # would be reported as a syntax error it is not. Check it as
            # a module instead of emitting a false failure.
            handle = tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8")
            with handle:
                handle.write(text)
            tmp = Path(handle.name)
            target = tmp
        result = subprocess.run(["node", "--check", str(target)], capture_output=True,
                                text=True, timeout=30, check=False)
        if result.returncode == 0:
            return ""
        message = (result.stderr or result.stdout or "").strip().splitlines()
        return next((line for line in message if "Error" in line or "error" in line), message[0] if message else "syntax error")
    except Exception:  # noqa: BLE001 -- a checker that crashes reports nothing
        return ""
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def check_project(root: Path) -> list[Issue]:
    """Inspect every file that was really written. Cheap and read-only."""
    root = Path(root)
    issues: list[Issue] = []
    if not root.is_dir():
        return [Issue("structure", str(root), "The project folder does not exist.")]

    from reyes_agent.executors import filesystem

    names = filesystem.list_files(root)
    if not names:
        return [Issue("structure", str(root), "The project folder is empty -- no files were written.")]
    existing = {name.casefold(): name for name in names}

    for name in names:
        path = root / name
        suffix = path.suffix.lower()
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size == 0:
            issues.append(Issue("empty_file", name, "File is empty (0 bytes)."))
            continue
        text = _read(path)

        if suffix in {".html", ".htm"}:
            for pattern in _REF_PATTERNS:
                for ref in pattern.findall(text):
                    ref = ref.strip()
                    if not ref or _REMOTE.match(ref):
                        continue
                    rel = ref.split("?")[0].split("#")[0].replace("\\", "/").lstrip("./").lstrip("/")
                    if not rel:
                        continue
                    if (root / rel).is_file():
                        continue
                    # Same file present under a different path is a safe,
                    # unambiguous repoint. Anything else needs real content.
                    base = Path(rel).name.casefold()
                    matches = [n for n in names if Path(n).name.casefold() == base]
                    issues.append(Issue(
                        "missing_reference", name,
                        f"references '{ref}', which does not exist in the project.",
                        fixable=len(matches) == 1,
                        suggestion=matches[0] if len(matches) == 1 else "",
                    ))
        elif suffix in {".js", ".mjs", ".cjs"}:
            error = _node_check(path)
            if error:
                issues.append(Issue("syntax", name, f"JavaScript syntax error: {error}"))
            elif not terminal.tool_available("node"):
                imbalance = _balanced(text)
                if imbalance:
                    issues.append(Issue("syntax", name,
                                        f"possible syntax problem ({imbalance}); Node.js is not "
                                        "installed, so this is a bracket-balance heuristic, not a parse."))
        elif suffix == ".css":
            imbalance = _balanced(text)
            if imbalance:
                issues.append(Issue("syntax", name, f"CSS looks malformed ({imbalance})."))
        elif suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                issues.append(Issue("invalid_json", name, f"invalid JSON: {exc}"))
        elif suffix == ".py":
            try:
                ast.parse(text)
            except SyntaxError as exc:
                issues.append(Issue("syntax", name, f"Python syntax error on line {exc.lineno}: {exc.msg}"))

    if not any(Path(n).name.lower() in {"index.html", "main.py", "app.py", "index.js"} for n in names):
        issues.append(Issue("structure", str(root),
                            "No entry point (index.html / app.py / index.js) was created.",
                            suggestion="create index.html"))
    _ = existing
    return issues


def autofix(root: Path, issues: list[Issue]) -> list[str]:
    """Apply only corrections that cannot lose work. Returns what changed."""
    root = Path(root)
    applied: list[str] = []
    for issue in issues:
        if issue.kind != "missing_reference" or not issue.fixable or not issue.suggestion:
            continue
        path = root / issue.file
        text = _read(path)
        if not text:
            continue
        broken = re.search(r"references '([^']+)'", issue.detail)
        if not broken:
            continue
        old = broken.group(1)
        new = issue.suggestion.replace("\\", "/")
        updated = text.replace(f'"{old}"', f'"{new}"').replace(f"'{old}'", f"'{new}'")
        if updated == text:
            continue
        from reyes_agent.executors import filesystem

        result = filesystem.write_file(root, issue.file, updated)
        if result.ok:
            applied.append(f"{issue.file}: repointed '{old}' -> '{new}'")
    return applied


def analyze_issues(issues: list[Issue]) -> dict[str, int]:
    """Return stable defect categories for the Activity View/API.

    This is intentionally a count of observed checker results, not a model
    confidence score or a claim that a page looks correct.
    """
    categories: dict[str, int] = {}
    for issue in issues:
        category = _CATEGORY.get(issue.kind, "other")
        categories[category] = categories.get(category, 0) + 1
    return categories


def _score(issues: list[Issue]) -> int:
    return sum(_SEVERITY.get(issue.kind, 3) for issue in issues)


def _backup_fix_targets(root: Path, issues: list[Issue]) -> dict[str, bytes]:
    """Save exactly the files the safe fixer is allowed to alter.

    Taking a blanket project snapshot to repair one broken HTML reference is
    costly and can itself hit a size cap. `autofix` currently edits only the
    `issue.file` for safe missing-reference repairs, so this tight backup is
    sufficient and makes rollback deterministic.
    """
    root = Path(root).resolve()
    saved: dict[str, bytes] = {}
    for issue in issues:
        if issue.kind != "missing_reference" or not issue.fixable:
            continue
        candidate = (root / issue.file).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file() and not candidate.is_symlink():
            try:
                saved[str(candidate.relative_to(root)).replace("\\", "/")] = candidate.read_bytes()
            except OSError:
                continue
    return saved


def _restore_backup(root: Path, backup: dict[str, bytes]) -> bool:
    from reyes_agent.executors import filesystem

    restored = True
    for relative, data in backup.items():
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            restored = False
            continue
        if not filesystem.write_file(root, relative, content).ok:
            restored = False
    return restored


def repair_project(root: Path, *, max_attempts: int = MAX_AUTO_FIX_ATTEMPTS) -> RepairReport:
    """Run a bounded repair loop and undo a repair that makes defects worse.

    Only `autofix`'s existing unambiguous asset-reference repair is eligible.
    Syntax, content and security defects are categorised and reported, never
    guessed at by a model or rewritten silently. Each iteration measures the
    checker result from disk. A strictly worse score restores the exact files
    changed in that iteration before returning.
    """
    root = Path(root)
    limit = max(0, min(MAX_AUTO_FIX_ATTEMPTS, int(max_attempts)))
    issues = check_project(root)
    applied: list[str] = []
    attempts = 0
    reason = "No safe automatic repair was available."

    while attempts < limit:
        eligible = [item for item in issues if item.kind == "missing_reference" and item.fixable]
        if not eligible:
            break
        backup = _backup_fix_targets(root, eligible)
        if not backup:
            reason = "A safe repair target could not be backed up."
            break
        before_score = _score(issues)
        attempts += 1
        changed = autofix(root, eligible)
        if not changed:
            reason = "Safe repair made no on-disk change."
            break
        after = check_project(root)
        after_score = _score(after)
        if after_score > before_score:
            restored = _restore_backup(root, backup)
            restored_issues = check_project(root)
            return RepairReport(
                issues=restored_issues, applied=applied, attempts=attempts,
                categories=analyze_issues(restored_issues), rolled_back=True,
                reason=("Automatic repair increased the measured defect score and was rolled back."
                        if restored else "Automatic repair was worse and rollback could not be fully verified."),
            )
        applied.extend(changed)
        if after_score >= before_score:
            issues = after
            reason = "Automatic repair did not improve the measured defect score."
            break
        issues = after
        reason = "Automatic repair improved the measured defect score."

    return RepairReport(issues=issues, applied=applied, attempts=attempts,
                        categories=analyze_issues(issues), reason=reason)


def missing_dependencies(root: Path) -> list[str]:
    """What the project declares that this machine does not have.

    Named plainly so ZENO reports "Node.js is not installed" rather than
    running a build step that was never going to work.
    """
    root = Path(root)
    missing: list[str] = []
    if (root / "package.json").is_file():
        if not terminal.tool_available("node"):
            missing.append("Node.js (package.json is present but `node` is not on PATH)")
        elif not terminal.tool_available("npm"):
            missing.append("npm (package.json is present but `npm` is not on PATH)")
    if (root / "requirements.txt").is_file() and not terminal.tool_available("python"):
        missing.append("Python (requirements.txt is present but `python` is not on PATH)")
    return missing


_FINANCE_HINTS = ("bank", "banking", "account", "iban", "sort code", "routing number",
                  "card number", "cvv", "credit card", "debit card", "transfer", "payment")
_DEMO_MARKERS = ("demo", "sample", "fictional", "mock", "example", "not a real", "prototype",
                 "test data", "simulated", "for illustration")
_SENSITIVE_INPUT = re.compile(
    r"""<input[^>]*(?:type\s*=\s*["']password["']|name\s*=\s*["'][^"']*"""
    r"""(?:ssn|social|cvv|cvc|card|iban|routing|sortcode|pin)[^"']*["'])""", re.I)
_EXTERNAL_FORM = re.compile(r"""<form[^>]+action\s*=\s*["'](https?://[^"']+)["']""", re.I)


def demo_safety_issues(root: Path) -> list[Issue]:
    """Keep a 'banking website' a demonstration, not a credential trap.

    Two different severities, on purpose:

    * A form that POSTs to an absolute external URL alongside password or
      card fields is a hard failure. Whatever the intent, that page sends
      whatever a real person types into it to a real server, and a
      convincing bank UI is exactly what makes someone type real details.
    * Sensitive-looking inputs with nothing on the page saying it is a
      demo are a warning: the page is fine locally, but it should say what
      it is.
    """
    root = Path(root)
    issues: list[Issue] = []
    if not root.is_dir():
        return issues
    from reyes_agent.executors import filesystem

    for name in filesystem.list_files(root):
        if Path(name).suffix.lower() not in {".html", ".htm"}:
            continue
        text = _read(root / name)
        lowered = text.lower()
        for action in _EXTERNAL_FORM.findall(text):
            issues.append(Issue(
                "unsafe_form", name,
                f"a form submits to the external URL '{action}'. A demo must not send "
                "anything typed into it off this machine.",
            ))
        if _SENSITIVE_INPUT.search(text) and not any(marker in lowered for marker in _DEMO_MARKERS):
            if any(hint in lowered for hint in _FINANCE_HINTS):
                issues.append(Issue(
                    "undeclared_demo", name,
                    "collects password/card-style input but never says on the page that it "
                    "is a demonstration with sample data.",
                    suggestion="add a visible 'Demo -- sample data, no real credentials' notice",
                ))
    return issues


def summarize(issues: list[Issue]) -> str:
    if not issues:
        return "No code problems found."
    lines = [f"{len(issues)} problem(s) found:"]
    for issue in issues[:12]:
        lines.append(f"  - {issue.file}: {issue.detail}")
    return "\n".join(lines)
