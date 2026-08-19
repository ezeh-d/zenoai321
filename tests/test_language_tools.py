"""The explicit language tools -- the half the owner asks for by name.

Understanding is automatic and tested in test_language_engine. These cover the
tools that fire only on a deliberate request: translate INTO a language,
explain a language, teach a phrase, show diagnostics.
"""

from __future__ import annotations

import os

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.tools import TOOLS  # noqa: E402


def _call(name: str, **kwargs) -> str:
    return TOOLS[name].func(**kwargs)


# --- registration + routing ---------------------------------------------
def test_the_four_language_tools_are_registered():
    for name in ("translate_text", "explain_language", "remember_phrase",
                 "language_diagnostics"):
        assert name in TOOLS, f"{name} is not registered"


def test_explicit_language_requests_route_to_language():
    from reyes_agent.routing import capability

    for msg in ("translate this to French", "tell him in Yoruba I am coming",
                "what does abeg mean", "language debug",
                "when I say bring it out I mean give me the full output"):
        assert "language" in capability.tools_for(msg).capabilities, msg


def test_ordinary_multilingual_input_does_not_route_to_the_tools():
    """Understanding Pidgin is automatic; it must NOT pull in the explicit
    tools, or every Nigerian sentence would waste the language toolset."""
    from reyes_agent.routing import capability

    for msg in ("abeg open chrome", "wetin dey happen", "open the file"):
        assert "language" not in capability.tools_for(msg).capabilities, msg


# --- translate_text ------------------------------------------------------
def test_translate_needs_both_text_and_language():
    assert "Nothing to translate" in _call("translate_text", text="", target_language="fr")
    assert "Which language" in _call("translate_text", text="hello", target_language="")


def test_translate_reports_failure_honestly_under_local_only(monkeypatch):
    """Translating INTO a language needs the cloud model. With local-only
    privacy it must say so, not fake a translation."""
    from reyes_agent import config
    from reyes_agent.language import translate as translate_mod

    monkeypatch.setattr(config, "LANGUAGE_PRIVACY", "LOCAL_ONLY", raising=False)
    translate_mod.reset_for_tests()
    out = _call("translate_text", text="Open the door", target_language="French")
    assert "couldn't translate" in out.lower() or "in French" in out
    translate_mod.reset_for_tests()


# --- explain_language ----------------------------------------------------
def test_explain_identifies_language_and_meaning():
    out = _call("explain_language", text="Wetin dey happen?")
    assert "pcm" in out.lower() or "pidgin" in out.lower()
    assert "happening" in out.lower()


def test_explain_says_uncertain_rather_than_inventing():
    out = _call("explain_language", text="xyzzy plugh")
    assert "uncertain" in out.lower()


def test_explain_reports_a_non_latin_script():
    out = _call("explain_language", text="مرحبا")
    assert "Arabic" in out


# --- remember_phrase -----------------------------------------------------
def test_remember_phrase_stores_and_is_used(tmp_path):
    from reyes_agent.language import memory

    memory.reset_for_tests(tmp_path / "phrases.sqlite")
    out = _call("remember_phrase", phrase="bring it out",
                meaning="give me the full output now")
    assert "bring it out" in out
    # And it actually takes effect through the engine.
    text, applied = memory.get_memory().apply("bring it out")
    assert text == "give me the full output now"
    assert applied == ["bring it out"]


def test_remember_phrase_rejects_empty_or_identical():
    assert "need both" in _call("remember_phrase", phrase="x", meaning="").lower()
    assert "same" in _call("remember_phrase", phrase="same", meaning="same").lower()


# --- language_diagnostics ------------------------------------------------
def test_diagnostics_status_does_not_overclaim():
    out = _call("language_diagnostics")
    assert "Language engine:" in out
    assert "universal" not in out.lower() or "No claim" in out


def test_diagnostics_traces_a_specific_input():
    out = _call("language_diagnostics", text="Abeg open Chrome")
    assert "English meaning" in out
    assert "chrome" in out.lower()
