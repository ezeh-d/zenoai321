"""ZENO_TRUST_LOCAL_OWNER: local owner may send private messages without the
approval step, while every dangerous action keeps its confirmation.

This is the scoped, safe version of "let me send without approving every time":
the trust covers PRIVATE messaging/email only -- never public posts, shell
execution, deletion, money or security tooling, and never remote turns.
"""

from __future__ import annotations

import importlib

import pytest

from reyes_agent import action_policy as AP


def _effect(monkeypatch, *, trust, tool, cap, args, utterance,
            source="voice", authenticated=False):
    monkeypatch.setenv("ZENO_TRUST_LOCAL_OWNER", "1" if trust else "0")
    import reyes_agent.config as C
    importlib.reload(C)
    with AP.use_action_context(utterance, source=source,
                               owner_authenticated=authenticated):
        return AP.evaluate(tool, args, requires_confirmation=True,
                           permission_state="allow", capability=cap).effect


_MSG = {"platform": "whatsapp", "destination": "Mum", "message": "on my way"}


def test_trust_on_lets_local_voice_send_without_prompt(monkeypatch):
    eff = _effect(monkeypatch, trust=True, tool="send_message",
                  cap="messaging_send", args=_MSG,
                  utterance="zeno send a message to Mum saying on my way")
    assert eff is AP.PolicyEffect.EXECUTE


def test_trust_off_keeps_unconfirmed_voice_from_sending(monkeypatch):
    eff = _effect(monkeypatch, trust=False, tool="send_message",
                  cap="messaging_send", args=_MSG,
                  utterance="zeno send a message to Mum")
    assert eff is AP.PolicyEffect.DENY


def test_trust_does_not_open_shell_execution(monkeypatch):
    eff = _effect(monkeypatch, trust=True, tool="run_command", cap="",
                  args={"command": "del /f /s C:/x"},
                  utterance="zeno run del /f /s C:/x")
    assert eff is AP.PolicyEffect.HIGH_IMPACT_CONFIRMATION


def test_trust_never_covers_public_posts(monkeypatch):
    eff = _effect(monkeypatch, trust=True, tool="social_publish",
                  cap="social_post", args={"content": "hi"},
                  utterance="zeno post this")
    assert eff is AP.PolicyEffect.DENY


def test_trust_does_not_open_deletion(monkeypatch):
    eff = _effect(monkeypatch, trust=True, tool="delete_file", cap="",
                  args={"path": "r.pdf"}, utterance="zeno delete report")
    assert eff is AP.PolicyEffect.HIGH_IMPACT_CONFIRMATION


def test_confirmed_owner_still_sends_regardless_of_flag(monkeypatch):
    # the pre-existing authenticated-owner path is unchanged
    eff = _effect(monkeypatch, trust=False, tool="send_message",
                  cap="messaging_send", args=_MSG, authenticated=True,
                  utterance="zeno send a message to Mum saying on my way")
    assert eff is AP.PolicyEffect.EXECUTE
