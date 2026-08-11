"""Conservative local fallback policy; not an OS security boundary."""
from __future__ import annotations

import ast
import re
from pathlib import Path

_BLOCKED_IMPORTS = {"ctypes", "multiprocessing", "os", "pathlib", "requests", "socket", "subprocess", "urllib", "winreg"}
_BLOCKED_CALLS = {"compile", "eval", "exec", "__import__", "breakpoint", "input"}
_ABSOLUTE = re.compile(r"(?:[A-Za-z]:[\\/]|(?:^|[\"'])/|\\\\)")


def inspect_python(source: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"syntax error at line {exc.lineno}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [item.name.split(".")[0] for item in node.names] if isinstance(node, ast.Import) else [str(node.module or "").split(".")[0]]
            blocked = sorted(set(names) & _BLOCKED_IMPORTS)
            if blocked:
                return False, f"blocked import: {', '.join(blocked)}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
            return False, f"blocked dynamic execution call: {node.func.id}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if ".." in Path(value).parts or _ABSOLUTE.search(value):
                return False, "absolute or parent-traversal path literal is not allowed"
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("__"):
            return False, "dunder attribute access is not allowed"
    return True, "source passed the restricted local policy"
