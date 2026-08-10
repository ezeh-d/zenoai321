"""Pick the cheapest technique that can actually do the job.

THE LADDER, IN THE ORDER THE BRIEF SETS
---------------------------------------
    1  native API              open_app, open_path -- no perception at all
    2  Windows UI Automation   accessibility ground truth, ~0.2s, no model
    3  Playwright DOM          real selectors, for pages
    4  known workflow          a skill the owner already approved
    5  accessibility action    invoke a control rather than clicking a pixel
    6  CUA / UFO               VM-hosted computer-use agents
    7  Agent TARS / UI-TARS    visual operator for interfaces with no structure
    8  vision grounding        describe-and-locate against a parsed screen
    9  coordinates             last resort, and the only rung that guesses

WHY ORDER BY COST AND NOT BY CAPABILITY
---------------------------------------
Rung 7 can do almost anything rung 1 can, and people therefore reach for it
first. That is the mistake. "Open Chrome" through a visual agent costs a
screenshot, a model call and several seconds, and it can fail; through
`open_app` it is milliseconds and cannot. Measured on this machine: a UIA
read of a real window is **~0.2-0.8s** with no model at all, which is why
rungs 2 and 5 handle most real work.

Every rung above 5 is an OPTIONAL_PLUGIN, off by default, and reports
honestly when it is not installed. None of them is required for ZENO to
drive this desktop, because rungs 1-5 already do.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not execute. It answers "which technique should this go through,
and why" -- `controller.py` remains the only thing that acts. Keeping the
chooser separate from the doer is what makes the choice testable and the
fallback order auditable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

NATIVE = "native_api"
UIA = "windows_uia"
DOM = "playwright_dom"
WORKFLOW = "known_workflow"
ACCESSIBILITY = "accessibility_action"
CUA = "cua_ufo"
TARS = "agent_tars"
VISION = "vision_grounding"
COORDINATES = "coordinates"

# Index in this tuple IS the priority. Nothing else encodes the order.
LADDER = (NATIVE, UIA, DOM, WORKFLOW, ACCESSIBILITY, CUA, TARS, VISION, COORDINATES)

_FLAGS = {
    CUA: "ZENO_CUA_ENABLED",
    TARS: "ZENO_AGENT_TARS_ENABLED",
    VISION: "ZENO_VISION_GROUNDING_ENABLED",
}

_DESCRIPTIONS = {
    NATIVE: "a direct API call -- no screenshot, no model, cannot mis-click",
    UIA: "the accessibility tree the app already publishes (~0.2-0.8s, no model)",
    DOM: "real Playwright selectors against the page",
    WORKFLOW: "a skill you already approved for exactly this",
    ACCESSIBILITY: "invoking the control itself rather than clicking where it looks",
    CUA: "a computer-use agent in a VM/container",
    TARS: "a visual operator for interfaces with no readable structure",
    VISION: "locating a described element on a parsed screen",
    COORDINATES: "clicking a position -- the only rung that guesses, and the last",
}


@dataclass(frozen=True)
class Choice:
    backend: str
    rung: int
    reason: str
    considered: tuple[str, ...] = ()

    @property
    def guesses(self) -> bool:
        return self.backend == COORDINATES

    def as_dict(self) -> dict[str, Any]:
        return {"backend": self.backend, "rung": self.rung + 1, "reason": self.reason,
                "guesses": self.guesses, "considered": list(self.considered),
                "description": _DESCRIPTIONS.get(self.backend, "")}


def enabled(backend: str) -> bool:
    """Optional rungs are OFF unless the owner turned them on."""
    flag = _FLAGS.get(backend)
    if flag is None:
        return True                    # rungs 1-5 are always available
    return os.environ.get(flag, "").strip().lower() in {"1", "true", "yes", "on"}


def installed(backend: str) -> bool:
    """Whether the rung could actually run, as opposed to being switched on."""
    import importlib.util as finder

    if backend == DOM:
        return finder.find_spec("playwright") is not None
    if backend == CUA:
        # Only the real package. Probing for a module called "agent" matched
        # something unrelated on this machine and reported CUA as installed.
        return finder.find_spec("cua") is not None
    if backend == TARS:
        return finder.find_spec("ui_tars") is not None
    if backend in (NATIVE, UIA, ACCESSIBILITY):
        return finder.find_spec("comtypes") is not None
    return True                        # workflow, vision and coordinates need nothing extra


def choose(request: str, *, scene: Any = None,
           deterministic: Callable[[str], bool] | None = None,
           has_skill: Callable[[str], bool] | None = None,
           is_web: bool = False) -> Choice:
    """The cheapest rung that can plausibly handle this request.

    `scene` matters more than anything else here: a window whose
    accessibility tree could not be read is exactly the case where the
    structural rungs must be skipped rather than tried and trusted.
    """
    considered: list[str] = []

    # 1. Something ZENO can just do.
    considered.append(NATIVE)
    if deterministic is not None and deterministic(request):
        return Choice(NATIVE, 0, "this is a known command; no perception needed",
                      tuple(considered))

    # 4 out of order deliberately: an approved skill beats generic perception,
    # because the owner has already said this exact sequence is correct.
    considered.append(WORKFLOW)
    if has_skill is not None and has_skill(request):
        return Choice(WORKFLOW, 3, "you have already approved a skill for this",
                      tuple(considered))

    # 3. Pages are better driven by selectors than by pixels.
    if is_web:
        considered.append(DOM)
        if installed(DOM):
            return Choice(DOM, 2, "this is a page, so real selectors beat pixels",
                          tuple(considered))

    readable = scene is None or bool(getattr(scene, "reliable", True))
    actionable = bool(getattr(scene, "interactive", []) if scene is not None else True)

    # 2 and 5. Structural rungs, only when the screen was genuinely read.
    considered.append(UIA)
    if readable and actionable:
        return Choice(ACCESSIBILITY, 4,
                      "the window publishes real controls, so act on the control "
                      "itself rather than a pixel", tuple(considered))
    if readable and scene is not None and not actionable:
        # Read fine, nothing to click: no amount of vision invents a button.
        return Choice(UIA, 1, "the window was read and exposes nothing actionable",
                      tuple(considered))

    # 6-8. Only now is a model worth paying for, and only if it exists.
    for backend, rung, why in ((CUA, 5, "structure was unreadable; a computer-use agent"),
                               (TARS, 6, "structure was unreadable; a visual operator"),
                               (VISION, 7, "structure was unreadable; locate by description")):
        considered.append(backend)
        if enabled(backend) and installed(backend):
            coverage = getattr(scene, "coverage", None) if scene is not None else None
            detail = f" ({coverage.state})" if coverage is not None else ""
            return Choice(backend, rung, why + detail, tuple(considered))

    considered.append(COORDINATES)
    return Choice(COORDINATES, 8,
                  "nothing above this could read the window, and no visual backend is "
                  "enabled -- I would be guessing at a position, so I would rather ask you",
                  tuple(considered))


def describe() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "ladder": [{
            "rung": index + 1, "backend": name, "description": _DESCRIPTIONS[name],
            "optional": name in _FLAGS, "flag": _FLAGS.get(name, ""),
            "enabled": enabled(name), "installed": installed(name),
        } for index, name in enumerate(LADDER)],
        "default_path": "rungs 1-5 need no optional dependency and handle real work today",
        "note": ("Order is by cost, not by capability. A visual agent can open Chrome, "
                 "but open_app does it in milliseconds and cannot mis-click."),
    }


status = describe
