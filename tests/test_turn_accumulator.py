"""Segmenter turn accumulation: hold an unfinished sentence and merge it with
the next clip, with a grace window. Verified by simulating the exact transcript
sequence a live mic produces (injected clock -- no audio hardware needed)."""

from __future__ import annotations

import pytest

from reyes_agent.conversation.realtime import TurnAccumulator


def test_a_complete_command_commits_immediately():
    acc = TurnAccumulator(grace_s=2.0)
    r = acc.feed("open spotify", now=0.0)
    assert r["commit"] is True and r["text"] == "open spotify"


def test_incomplete_then_continuation_within_grace_merges():
    # "open spotify and" [0.0]  ...short pause...  "play jazz" [1.0]
    acc = TurnAccumulator(grace_s=2.0)
    r1 = acc.feed("open spotify and", now=0.0)
    assert r1["commit"] is False and acc.pending() == "open spotify and"
    r2 = acc.feed("play jazz", now=1.0)
    assert r2["commit"] is True and r2["text"] == "open spotify and play jazz"
    assert acc.pending() == ""


def test_three_way_accumulation():
    acc = TurnAccumulator(grace_s=2.0)
    # each fragment ends on a dangling connector -> held until the sentence lands
    assert acc.feed("open the document catherine sent to", now=0.0)["commit"] is False
    assert acc.feed("me earlier and", now=0.5)["commit"] is False
    r = acc.feed("put it beside chrome", now=1.0)
    assert r["commit"] is True
    assert r["text"] == "open the document catherine sent to me earlier and put it beside chrome"


def test_stale_fragment_is_dropped_not_glued_to_a_new_sentence():
    acc = TurnAccumulator(grace_s=2.0)
    acc.feed("open spotify and", now=0.0)          # then the owner wandered off
    r = acc.feed("what time is it", now=6.0)        # much later, unrelated
    assert r["commit"] is True and r["text"] == "what time is it"
    assert "dropped" in r["reason"]


def test_flush_commits_a_pending_fragment_on_idle():
    acc = TurnAccumulator(grace_s=2.0)
    acc.feed("open spotify and", now=0.0)
    f = acc.flush(now=1.0)
    assert f["commit"] is True and f["text"] == "open spotify and"
    assert acc.flush(now=2.0)["commit"] is False    # nothing left


def test_never_holds_an_overlong_fragment():
    acc = TurnAccumulator(grace_s=2.0, max_chars=10)
    r = acc.feed("tell me about the and", now=0.0)   # incomplete but too long
    assert r["commit"] is True                        # committed rather than held


def test_empty_transcript_keeps_pending():
    acc = TurnAccumulator(grace_s=2.0)
    acc.feed("open spotify and", now=0.0)
    r = acc.feed("", now=0.5)
    assert r["commit"] is False and acc.pending() == "open spotify and"


def test_remote_mic_imports_with_the_wire():
    import reyes_agent.remote_mic.runtime as rt  # noqa: F401
    from reyes_agent.conversation.realtime import get_turn_accumulator
    assert get_turn_accumulator() is not None
