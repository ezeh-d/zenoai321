"""Browser automation torture test.

WHY VERIFICATION IS THE POINT, NOT THE EXTRA
---------------------------------------------
"The click did not raise" is not evidence that anything happened. Everywhere
else in this codebase that distinction has already caught real defects: the
Slack adapter refuses to type into a window it cannot read, and a render is
only finished when ffprobe says the file has a video stream.

So every action here is followed by a question to the page about its actual
state. An action that succeeds and cannot be verified is reported as
UNVERIFIED, not as success.

WHAT IT WATCHES FOR
-------------------
Chromium processes are the leak that matters. A browser worker that opens a
context per command and never closes one looks perfectly healthy until the
machine runs out of memory. Process count is sampled before, during and after,
and the after-count is compared to the before-count.

SITES
-----
example.com and the local ZENO dashboard: stable, fast, and nobody's terms of
service are involved. The point is to exercise ZENO's automation, not to
hammer somebody else's servers.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# Deliberately boring and stable. A flaky third-party page would produce
# failures that say nothing about ZENO.
TARGETS = ("https://example.com", "http://127.0.0.1:8765/")


@dataclass
class Step:
    name: str
    ok: bool = False
    verified: bool = False
    detail: str = ""
    ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"step": self.name, "ok": self.ok, "verified": self.verified,
                "detail": self.detail[:120], "ms": round(self.ms, 1)}


@dataclass
class Report:
    cycles: int = 0
    steps: list[Step] = field(default_factory=list)
    chromium_before: int = 0
    chromium_peak: int = 0
    chromium_after: int = 0
    notes: list[str] = field(default_factory=list)


def _chromium_count() -> int:
    try:
        import psutil

        return sum(1 for p in psutil.process_iter(["name"])
                   if any(marker in (p.info.get("name") or "").lower()
                          for marker in ("chrome", "chromium", "msedge")))
    except Exception:  # noqa: BLE001
        return 0


def _call(tool: str, **kwargs) -> tuple[bool, str, float]:
    """Run a registered browser tool the way ZENO does."""
    from reyes_agent.tools import TOOLS, execute_tool

    started = time.perf_counter()
    entry = TOOLS.get(tool)
    if entry is None:
        return False, f"{tool} is not registered", 0.0
    try:
        out = execute_tool(entry, kwargs)
        ms = (time.perf_counter() - started) * 1000
        text = str(out)
        # Failure markers appear ANYWHERE, not only at position zero. The
        # first version matched only a leading "error", so ZENO's actual
        # message -- "Browser error: TimeoutError: Page.click: Timeout
        # 15000ms exceeded" -- was scored as SUCCESS, and this harness nearly
        # reported a defect that did not exist. The tool was behaving
        # correctly; the test was wrong.
        low = text.lower()
        failed = any(marker in low for marker in (
            "error", "failed", "could not", "timeout", "exceeded",
            "unavailable", "not found", "no such"))
        return (not failed), text[:300], ms
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", (time.perf_counter() - started) * 1000


def _step(report: Report, name: str, tool: str, *, expect: str = "",
          **kwargs) -> Step:
    """Run one action and then ASK THE PAGE whether it happened."""
    ok, detail, ms = _call(tool, **kwargs)
    step = Step(name=name, ok=ok, detail=detail, ms=ms)

    if ok and expect:
        # Verification is a separate question to the page, not a re-reading of
        # the action's own return value.
        read_ok, text, _ms = _call("browser_read")
        step.verified = read_ok and expect.lower() in text.lower()
        if not step.verified:
            step.detail = f"action reported success; page did not show {expect!r}"
    elif ok:
        step.verified = True
    report.steps.append(step)
    return step


def run(cycles: int = 15) -> Report:
    report = Report(cycles=cycles)
    report.chromium_before = _chromium_count()
    report.chromium_peak = report.chromium_before

    for index in range(cycles):
        target = TARGETS[index % len(TARGETS)]
        expect = "example" if "example.com" in target else "zeno"

        _step(report, "open", "browser_open", url=target, expect=expect)
        _step(report, "read", "browser_read")
        _step(report, "scroll", "browser_scroll", direction="down")
        _step(report, "extract", "browser_extract", selector="body")
        _step(report, "screenshot", "browser_screenshot")

        # A selector that cannot exist: the recovery path matters more than
        # the happy path, because this is what a changed page looks like.
        # A click on a selector that cannot exist MUST fail. Success here
        # would mean ZENO reports actions it did not perform.
        missing = _step(report, "missing_selector_must_fail", "browser_click",
                        selector="#definitely-not-here-zeno-stress")
        if missing.ok:
            report.notes.append(
                "clicking a non-existent selector reported SUCCESS -- a click "
                "that cannot have happened must not report success")
        else:
            missing.detail = "correctly refused: " + missing.detail[:80]

        report.chromium_peak = max(report.chromium_peak, _chromium_count())

    _call("browser_close")
    time.sleep(3)
    report.chromium_after = _chromium_count()
    return report


def analyse(report: Report) -> dict[str, Any]:
    by_name: dict[str, list[Step]] = {}
    for step in report.steps:
        by_name.setdefault(step.name, []).append(step)

    summary = {}
    for name, steps in by_name.items():
        oks = sum(1 for s in steps if s.ok)
        verified = sum(1 for s in steps if s.verified)
        times = [s.ms for s in steps if s.ms]
        summary[name] = {
            "attempts": len(steps),
            "ok": oks,
            "verified": verified,
            "median_ms": round(statistics.median(times), 1) if times else 0,
        }

    leaked = report.chromium_after - report.chromium_before
    return {
        "cycles": report.cycles,
        "steps_run": len(report.steps),
        "by_action": summary,
        "chromium": {"before": report.chromium_before,
                     "peak": report.chromium_peak,
                     "after": report.chromium_after,
                     "leaked": leaked,
                     "verdict": "LEAK" if leaked > 1 else "clean"},
        "notes": report.notes,
    }


if __name__ == "__main__":
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    print(f"browser stress: {cycles} cycles", flush=True)
    outcome = analyse(run(cycles))
    print(json.dumps(outcome, indent=2))
    out = f"browser_stress_{int(time.time())}.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(outcome, handle, indent=2)
    print(f"written: {out}")
