"""ZENO Hands: typing/keys/click as brain tools -- reuse the gated engine,
standardized results, honest verification, never fake success."""

from __future__ import annotations

import json

from reyes_agent.tools import hands_tools


class FakeStep:
    def __init__(self, ok: bool, changed: bool, detail: str) -> None:
        self.ok, self.changed, self.detail = ok, changed, detail


def _patch_act(monkeypatch, step, sink=None):
    def _act(action, target="", text="", **kw):
        if sink is not None:
            sink.append((action, target, text))
        return step
    monkeypatch.setattr("reyes_agent.computer.agentic.act", _act)


def test_type_text_success_is_verified(monkeypatch):
    _patch_act(monkeypatch, FakeStep(True, True, "typed 5 characters; window changed"))
    out = json.loads(hands_tools.type_text("hello"))
    assert out["success"] is True and out["verified"] is True
    assert out["tool"] == "computer.type_text" and out["action"] == "type"
    assert out["error"] is None and out.get("evidence")


def test_type_text_failure_not_faked(monkeypatch):
    _patch_act(monkeypatch, FakeStep(False, False, "focus moved to another window"))
    out = json.loads(hands_tools.type_text("hello"))
    assert out["success"] is False and out["verified"] is False
    assert out["error"] and "focus moved" in out["error"]


def test_type_text_empty_is_rejected():
    out = json.loads(hands_tools.type_text(""))
    assert out["success"] is False


def test_press_keys_passes_combo_to_engine(monkeypatch):
    calls: list = []
    _patch_act(monkeypatch, FakeStep(True, True, "pressed ctrl+s"), calls)
    out = json.loads(hands_tools.press_keys("ctrl+s"))
    assert out["success"] is True
    assert calls == [("key", "ctrl+s", "")]


def test_press_keys_empty_rejected():
    assert json.loads(hands_tools.press_keys("  "))["success"] is False


def test_click_element_is_grounded_by_description(monkeypatch):
    calls: list = []
    _patch_act(monkeypatch, FakeStep(True, True, "clicked; window changed"), calls)
    out = json.loads(hands_tools.click_element("the Send button"))
    assert out["success"] is True and calls == [("click", "the Send button", "")]


def test_click_ambiguous_reports_honestly(monkeypatch):
    _patch_act(monkeypatch, FakeStep(False, False, "'button' is ambiguous -- could be: Send, Save"))
    out = json.loads(hands_tools.click_element("button"))
    assert out["success"] is False and "ambiguous" in out["error"]


def test_secret_is_typed_but_not_echoed(monkeypatch):
    _patch_act(monkeypatch, FakeStep(True, True, "typed 28 characters"))
    out = json.loads(hands_tools.type_text("my password is hunter2secret"))
    assert "password" not in out["target"] and "redacted" in out["target"]
    assert out["success"] is True   # it was still typed, just not echoed


def test_long_tokenish_string_is_redacted(monkeypatch):
    _patch_act(monkeypatch, FakeStep(True, True, "typed"))
    out = json.loads(hands_tools.type_text("sk-abcdefghijklmnopqrstuvwxyz123456"))
    assert "redacted" in out["target"]


def test_standardized_result_shape(monkeypatch):
    _patch_act(monkeypatch, FakeStep(True, False, "ok"))
    out = json.loads(hands_tools.type_text("x"))
    assert set(out) >= {"success", "ok", "tool", "action", "target",
                        "duration_ms", "verified", "detail", "error"}


def test_scroll_respects_input_guard(monkeypatch):
    class Grant:
        allowed = False
        reason = "the owner is using the computer"

    monkeypatch.setattr("reyes_agent.computer.input_guard.may_take_control",
                        lambda override=False: Grant())
    out = json.loads(hands_tools.scroll_screen("down"))
    assert out["success"] is False and "owner" in out["error"]


def test_hands_tools_are_registered():
    from reyes_agent.tools import TOOLS
    for name in ("type_text", "press_keys", "click_element", "scroll_screen"):
        assert name in TOOLS
