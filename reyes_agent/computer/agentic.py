"""The AGENTIC path: observe -> ground -> act -> verify, bounded.

WHERE THE DANGER IS
-------------------
A computer-use loop fails in two ways. It clicks something it should not
(handled in `safety.py`), or it never stops -- retrying a step forever
because each attempt "almost" worked. Every loop here is bounded by three
independent limits: step count, wall-clock deadline, and consecutive
no-change attempts. Any one of them ends the run.

WHAT MAKES AN ACTION LEGITIMATE
-------------------------------
Coordinates are never invented. A click resolves a description against
elements the screen actually reported (`vision.grounding`), and if nothing
matches confidently enough the step FAILS rather than guessing a pixel. If
two elements match equally well, it stops and asks instead of picking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from reyes_agent import vision
from reyes_agent.computer import input_guard, safety, verification, window

MAX_STEPS = 12
DEADLINE_S = 90.0
MAX_NO_CHANGE = 3          # consecutive actions that changed nothing on screen
SETTLE_S = 0.6             # let the GUI repaint before observing

# Actions that seize the real mouse/keyboard. `observe` does not.
_SENDS_INPUT = frozenset({"click", "type", "key"})


@dataclass
class Step:
    action: str
    target: str = ""
    text: str = ""
    ok: bool = False
    detail: str = ""
    risk: str = ""
    changed: bool = False
    blocked_on_owner: bool = False
    focus_moved: bool = False
    at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "target": self.target, "ok": self.ok,
                "detail": self.detail, "risk": self.risk, "changed": self.changed,
                "blocked_on_owner": self.blocked_on_owner,
                "focus_moved": self.focus_moved}


@dataclass
class Outcome:
    ok: bool
    steps: list[Step] = field(default_factory=list)
    reason: str = ""
    needs_approval: str = ""
    blocked_on_owner: bool = False
    observations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason,
                "needs_approval": self.needs_approval,
                "blocked_on_owner": self.blocked_on_owner,
                "steps": [s.as_dict() for s in self.steps],
                "observations": self.observations[-3:]}

    def summary(self) -> str:
        lines = [self.reason or ("done" if self.ok else "did not complete")]
        for step in self.steps:
            mark = "ok " if step.ok else "FAIL"
            lines.append(f"  {mark} {step.action} {step.target!r} -- {step.detail}")
        if self.needs_approval:
            lines.append(f"  WAITING ON YOU: {self.needs_approval}")
        return "\n".join(lines)


def _send_click(x: int, y: int) -> tuple[bool, str]:
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.click(x, y)
        return True, f"clicked ({x},{y})"
    except Exception as exc:  # noqa: BLE001
        return False, f"click failed: {type(exc).__name__}: {exc}"


def _send_text(text: str) -> tuple[bool, str]:
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.write(str(text), interval=0.01)
        return True, f"typed {len(str(text))} characters"
    except Exception as exc:  # noqa: BLE001
        return False, f"typing failed: {type(exc).__name__}: {exc}"


def _send_keys(combo: str) -> tuple[bool, str]:
    try:
        import pyautogui

        keys = [k.strip().lower() for k in str(combo).replace("-", "+").split("+") if k.strip()]
        if not keys:
            return False, "no keys given"
        pyautogui.hotkey(*keys)
        return True, f"pressed {'+'.join(keys)}"
    except Exception as exc:  # noqa: BLE001
        return False, f"hotkey failed: {type(exc).__name__}: {exc}"


def act(action: str, target: str = "", text: str = "", *,
        approved: bool = False, override_idle: bool = False,
        cancel_check: Callable[[], None] | None = None) -> Step:
    """ONE grounded action, gated and verified."""
    if cancel_check:
        cancel_check()
    step = Step(action=action, target=target, text=text)
    before = vision.scene_state.current()

    allowed, risk = safety.gate(action, target, before.window, approved=approved)
    step.risk = risk.tier
    if not allowed:
        step.detail = risk.reason
        return step

    # Resolve the target BEFORE asking for the mouse. A step that was never
    # going to send input -- an element that is not there, an ambiguous
    # description -- should say so plainly whether or not the owner happens
    # to be typing; asking for control first would replace a useful answer
    # with an irrelevant one.
    target_point: tuple[int, int] | None = None
    if action == "click":
        if vision.grounding.ambiguous(before, target):
            options = [e.label for _s, e in vision.grounding.candidates(before, target, 3)]
            step.detail = f"'{target}' is ambiguous -- could be: {', '.join(options)}"
            return step
        element = vision.grounding.find(before, target)
        if element is None:
            step.detail = f"'{target}' is not on screen; nothing was clicked"
            if not before.reliable and before.coverage is not None:
                # Do not let a bad read masquerade as a missing button.
                step.detail += (f" -- but I could not read this window properly "
                                f"({before.coverage.reason}), so it may well be there. "
                                f"{before.coverage.remedy.capitalize()}.")
            return step
        target_point = element.center
    elif action == "observe":
        step.ok, step.detail = True, before.summary(limit=12)
        return step
    elif action == "focus":
        # The remedy for a minimized or suspended window. It sends no mouse
        # or keyboard input, but yanking a window in front of someone who is
        # mid-sentence is just as rude, so it answers to the same guard.
        grant = input_guard.may_take_control(override=override_idle)
        if not grant.allowed:
            step.detail = grant.reason
            step.blocked_on_owner = True
            return step
        matches = window.find_by_title(target)
        if not matches:
            step.detail = f"no open window matching '{target}'"
            return step
        handle, title = matches[0]
        step.ok, step.detail = window.activate(handle)
        step.detail = f"{title!r}: {step.detail}"
        if step.ok:
            time.sleep(SETTLE_S)
            vision.scene_state.invalidate()
            step.changed = True
        return step
    elif action not in _SENDS_INPUT:
        step.detail = f"unknown action '{action}'"
        return step

    # Two different questions. `safety` asks whether the action is permissible
    # at all; this asks whether NOW is an acceptable moment to take the
    # owner's mouse away from them.
    grant = input_guard.may_take_control(override=override_idle)
    if not grant.allowed:
        step.detail = grant.reason
        step.blocked_on_owner = True
        return step

    # The scene was parsed from ONE window and the coordinates and keystrokes
    # below are aimed at that window. If focus has moved since -- the owner
    # alt-tabbed, a notification stole it -- then those coordinates point at a
    # stranger's UI and the keystrokes land in someone else's document.
    # Refusing here is the difference between a failed step and typing into
    # the owner's email.
    if before.window_handle:
        live = vision.parser.foreground_handle()
        if live and live != before.window_handle:
            step.detail = (f"focus moved to another window since I looked at "
                           f"'{before.window}' -- I will not send input to a window "
                           "I have not read")
            step.focus_moved = True
            return step

    if action == "click":
        step.ok, step.detail = _send_click(*target_point)
    elif action == "type":
        step.ok, step.detail = _send_text(text or target)
    else:
        step.ok, step.detail = _send_keys(target)

    # The GUI needs a moment, and the cached scene is now a lie.
    time.sleep(SETTLE_S)
    vision.scene_state.invalidate()
    after = vision.scene_state.current(force=True)
    change = verification.compare(before, after)
    step.changed = change.changed
    step.detail = f"{step.detail}; {change.detail}"
    return step


def run(goal: str, plan: list[dict], *, approved: bool = False,
        override_idle: bool = False,
        max_steps: int = MAX_STEPS, deadline_s: float = DEADLINE_S,
        cancel_check: Callable[[], None] | None = None) -> Outcome:
    """Execute a grounded plan with hard bounds.

    `plan` is a list of {action, target, text, expect} produced by the model
    -- ZENO decides WHAT to do, this decides whether each step is allowed,
    possible and effective.

    The whole run is wrapped so the pointer returns to where the owner left
    it, however the run ends -- success, refusal, deadline or exception.
    """
    with input_guard.cursor_home():
        return _run_locked(goal, plan, approved=approved, override_idle=override_idle,
                           max_steps=max_steps, deadline_s=deadline_s,
                           cancel_check=cancel_check)


def _run_locked(goal: str, plan: list[dict], *, approved: bool, override_idle: bool,
                max_steps: int, deadline_s: float,
                cancel_check: Callable[[], None] | None) -> Outcome:
    outcome = Outcome(ok=False)
    # Deadlines must not jump when Windows synchronises or corrects its wall
    # clock. Step timestamps remain wall time for diagnostics; elapsed-time
    # enforcement uses the monotonic clock.
    started = time.monotonic()
    no_change = 0

    for index, raw in enumerate(plan[:max_steps]):
        if cancel_check:
            try:
                cancel_check()
            except Exception:  # noqa: BLE001 -- cancellation is an ending, not an error
                outcome.reason = "cancelled"
                return outcome
        if time.monotonic() - started > deadline_s:
            outcome.reason = f"stopped at the {deadline_s:.0f}s deadline after {index} step(s)"
            return outcome

        action = str(raw.get("action", "")).strip().lower()
        step = act(action, str(raw.get("target", "")), str(raw.get("text", "")),
                   approved=approved, override_idle=override_idle,
                   cancel_check=cancel_check)
        outcome.steps.append(step)

        if step.risk == safety.REFUSED:
            outcome.reason = "refused: " + step.detail
            return outcome
        if step.blocked_on_owner:
            # Not a failure of the plan -- a deliberate refusal to fight the
            # owner for the mouse. Distinct so the caller can offer to retry.
            outcome.blocked_on_owner = True
            outcome.reason = step.detail
            return outcome
        if step.focus_moved:
            outcome.reason = step.detail
            return outcome
        if step.risk == safety.APPROVAL and not step.ok:
            outcome.needs_approval = step.detail
            outcome.reason = "waiting for your approval before continuing"
            return outcome
        if not step.ok:
            outcome.reason = f"step {index + 1} failed: {step.detail}"
            return outcome

        expectation = str(raw.get("expect", "")).strip()
        if expectation:
            met, why = verification.expects(vision.scene_state.current(), expectation)
            outcome.observations.append(why)
            if not met:
                outcome.reason = f"step {index + 1} ran but {why}"
                return outcome

        no_change = no_change + 1 if not step.changed else 0
        if no_change >= MAX_NO_CHANGE:
            # Three actions in a row that moved nothing means the loop is
            # not making progress. Stop rather than grind.
            outcome.reason = (f"stopped after {no_change} actions that changed nothing on "
                              "screen -- the plan is not working")
            return outcome

    outcome.ok = True
    outcome.reason = f"completed {len(outcome.steps)} step(s)"
    outcome.observations.append(vision.scene_state.current().summary(limit=8))
    return outcome
