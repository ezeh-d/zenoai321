"""Per-tool build-output analyzers.

WHY A PACKAGE INSTEAD OF MORE REGEXES IN ONE FILE
-------------------------------------------------
`diagnostics.py` grew a core parser for the tools this project runs most
(tsc, esbuild/vite, eslint, npm, node, postcss). Adding webpack, rollup and
vitest to the same linear scan would have made one long function where a
pattern for one tool can silently shadow another's -- which already happened
once, when the generic module pattern swallowed esbuild's location line.

So each tool gets its own module with its own patterns and its own tests,
and this registry decides which ones to try. Adding a tool is a new file
plus one `register()` call; it cannot break the tools already working.

HOW A TOOL IS CHOSEN
--------------------
Each analyzer declares `claims(output)` -- a cheap check for a fingerprint
only that tool emits. Analyzers that do not claim the output are skipped
entirely, so rollup's patterns never see webpack's text. When nothing
claims it, the caller falls back to the core parser and finally to UNKNOWN
with the raw text preserved.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover -- import cycle avoidance only
    from reyes_agent.executors.diagnostics import BuildError

# name -> (claims, parse)
_REGISTRY: dict[str, tuple[Callable[[str], bool], Callable[[str, Path | None], list]]] = {}


def register(name: str, claims: Callable[[str], bool],
             parse: Callable[[str, Path | None], list]) -> None:
    _REGISTRY[name] = (claims, parse)


def names() -> list[str]:
    return sorted(_REGISTRY)


def claimants(output: str) -> list[str]:
    """Which analyzers recognise this output. Usually zero or one."""
    text = str(output or "")
    return [name for name, (claims, _parse) in sorted(_REGISTRY.items()) if _safe_claim(claims, text)]


def _safe_claim(claims: Callable[[str], bool], text: str) -> bool:
    try:
        return bool(claims(text))
    except Exception:  # noqa: BLE001 -- a broken analyzer must not break analysis
        return False


def analyze(output: str, root: Path | None = None) -> list["BuildError"]:
    """Run every analyzer that claims this output.

    Results are concatenated rather than first-wins: a single `npm run build`
    can emit webpack errors AND a node stack trace, and dropping one because
    another matched first loses real information. `diagnostics.dedupe`
    collapses any genuine overlap afterwards.
    """
    text = str(output or "")
    found: list["BuildError"] = []
    for name in claimants(text):
        _claims, parse = _REGISTRY[name]
        try:
            found.extend(parse(text, root) or [])
        except Exception:  # noqa: BLE001 -- one bad analyzer cannot fail the build check
            continue
    return found


# Import the built-in analyzers for their registration side effects. Kept at
# the bottom so `register` exists when they run.
from reyes_agent.executors.analyzers import rollup, vitest, webpack  # noqa: E402,F401
