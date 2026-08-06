"""Evidence/risk regression tests for ZENO's unified confidence engine."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reyes_agent.confidence import assess, decide_tool, risk_for_tool
from reyes_agent.voice.stt import transcribe_result


def test_unknown_confidence_is_not_converted_into_a_positive_score() -> None:
    decision = assess({}, risk="high")
    assert decision.confidence is None
    assert decision.requires_confirmation
    assert "no measured confidence" in decision.reason


def test_high_confidence_low_risk_can_proceed_but_weak_high_risk_cannot() -> None:
    low = assess({"speech": 0.95, "intent": 0.92, "plan": 0.9}, risk="low")
    weak = assess({"speech": 0.45, "intent": 0.55}, risk="high")
    assert low.confidence is not None and low.confidence > 0.9
    assert not low.requires_confirmation
    assert weak.confidence is not None and weak.confidence < 0.7
    assert weak.requires_confirmation


def test_tool_risk_uses_existing_permission_capabilities() -> None:
    assert risk_for_tool("list_dir") == "low"
    assert risk_for_tool("browser_open") == "medium"
    assert risk_for_tool("delete_file", requires_confirmation=True) == "high"
    assert decide_tool("delete_file", requires_confirmation=True).requires_confirmation


def test_empty_stt_has_no_fabricated_confidence() -> None:
    assert transcribe_result(b"") == {"transcript": "", "confidence": None}


def test_web_exposes_real_speech_confidence_and_diagnostics() -> None:
    web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    ui = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")
    assert '@app.get("/api/confidence")' in web
    assert "transcribe_result" in web
    assert "result.confidence" in ui


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
