"""The mic input-device override lets ZENO use a working mic without changing
the Windows default (the fix when the default input is muted/dead)."""

from __future__ import annotations

import pytest

from reyes_agent.audio_recognition import _resolve_input_device


class _FakeSD:
    _DEVICES = [
        {"name": "Dead USB Mic (default)", "max_input_channels": 1},
        {"name": "Realtek Microphone Array", "max_input_channels": 2},
        {"name": "Speakers (output only)", "max_input_channels": 0},
    ]

    def query_devices(self, arg=None, kind=None):
        if kind == "input":
            return self._DEVICES[0]          # the (dead) system default
        if isinstance(arg, int):
            return self._DEVICES[arg]
        return list(self._DEVICES)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("ZENO_INPUT_DEVICE", raising=False)


def test_unset_uses_system_default():
    assert _resolve_input_device(_FakeSD())["name"].startswith("Dead USB")


def test_name_substring_selects_working_mic(monkeypatch):
    monkeypatch.setenv("ZENO_INPUT_DEVICE", "realtek")
    assert _resolve_input_device(_FakeSD())["name"] == "Realtek Microphone Array"


def test_index_selects_device(monkeypatch):
    monkeypatch.setenv("ZENO_INPUT_DEVICE", "1")
    assert _resolve_input_device(_FakeSD())["name"] == "Realtek Microphone Array"


def test_output_only_index_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ZENO_INPUT_DEVICE", "2")   # speakers: no input channels
    assert _resolve_input_device(_FakeSD())["name"].startswith("Dead USB")


def test_unmatched_name_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ZENO_INPUT_DEVICE", "nonexistent-device")
    assert _resolve_input_device(_FakeSD())["name"].startswith("Dead USB")


def test_never_raises_on_bad_provider(monkeypatch):
    monkeypatch.setenv("ZENO_INPUT_DEVICE", "5")

    class _Broken:
        def query_devices(self, arg=None, kind=None):
            if kind == "input":
                return {"name": "fallback", "max_input_channels": 1}
            raise RuntimeError("boom")

    assert _resolve_input_device(_Broken())["name"] == "fallback"
