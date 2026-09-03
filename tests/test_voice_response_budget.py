from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_fast_reply_allowlist_is_consequence_free() -> None:
    from reyes_agent.voice.latency_governor import reply_for

    assert reply_for("hello") is not None
    assert reply_for("How you dey?") is not None
    assert reply_for("thanks ZENO") is not None
    assert reply_for("open Chrome") is None
    assert reply_for("what is my account balance") is None
    assert reply_for("delete the file") is None
    assert reply_for("continue yesterday's project") is None


def test_default_tool_payload_is_actually_compact() -> None:
    from reyes_agent.tools import tool_definitions

    core = tool_definitions()
    names = {item["name"] for item in core}
    assert len(core) <= 13  # defense_mode joined the core set; keep this pinned to the real count
    assert len(json.dumps(core)) < 15_000
    assert {"enable_tools", "delegate", "open_app", "web_search", "build_project"} <= names
    assert "defense_mode" in names
    assert "website_project" not in names
    builder = {item["name"] for item in tool_definitions(groups={"build"})}
    assert "website_project" in builder
    expanded = {item["name"] for item in tool_definitions(groups={"extended"})}
    assert {"set_volume", "read_file", "browser_open", "remember"} <= expanded


def test_fast_chat_prompt_is_compact_and_keeps_safety_boundary() -> None:
    from reyes_agent import config

    prompt = config.FAST_CHAT_SYSTEM_PROMPT
    assert len(prompt) < 2_500
    # SYSTEM_PROMPT was deliberately trimmed for consistent speed (was >15k
    # chars); assert it stays in the new compact range instead of the old
    # size, but still carries real content -- an empty/near-empty prompt
    # would silently drop the safety boundary this test exists to protect.
    assert 3_000 < len(config.SYSTEM_PROMPT) < 12_000
    assert "Never pretend" in prompt
    assert "Voice identity alone never authorizes" in prompt


def test_thinking_ack_is_cache_only() -> None:
    from reyes_agent import voice_manager

    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        phrase = voice_manager.THINKING_ACKNOWLEDGEMENTS[0]
        cached = tmp_path / "ack.mp3"
        cached.write_bytes(b"real-cached-mp3")

        def fake_path(text, _profile):
            return cached if text == phrase else tmp_path / "missing.mp3"

        original = voice_manager._cache_path
        voice_manager._cache_path = fake_path
        try:
            result = voice_manager.cached_thinking_acknowledgement()
            assert result == (phrase, b"real-cached-mp3")
        finally:
            voice_manager._cache_path = original


def test_ack_latency_is_measured_separately() -> None:
    from reyes_agent import latency

    turn_id = latency.begin(kind="voice", message_preview="test")
    start = time.time()
    latency.mark(turn_id, "endpoint_detected", start)
    latency.mark(turn_id, "thinking_ack_audio", start + 0.65)
    latency.mark(turn_id, "first_audio", start + 0.65)
    line = latency.finish(turn_id)
    assert line is not None
    assert line["derived"]["time_to_ack_audio"] == 0.65
    assert line["derived"]["time_to_first_audio"] == 0.65


def test_both_webviews_use_cache_only_thinking_ack() -> None:
    root = Path(__file__).resolve().parents[1] / "reyes_agent" / "static"
    dashboard = (root / "index.html").read_text(encoding="utf-8")
    mini = (root / "mini.html").read_text(encoding="utf-8")
    assert "/api/voice/thinking-ack" in dashboard
    assert "/api/voice/thinking-ack" in mini
    assert "thinking_ack_audio" in dashboard
    assert "thinking_ack_audio" in mini


def _run_all() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        started = time.perf_counter()
        try:
            test()
            print(f"PASS {test.__name__} ({time.perf_counter() - started:.3f}s)")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
