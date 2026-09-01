"""Universal Media Intelligence engine -- logic verified without audio hardware.

The GSMTC reader and pycaw are monkeypatched, so these check the ORCHESTRATION:
session normalisation, conversational target resolution, event emission, the
panel/mini-card shape, refcounted speech ducking, and graceful degradation.
The live OS path (real Spotify play/pause/read-back/album-art) was verified
separately against the running machine.
"""

from __future__ import annotations

import os

import pytest

from reyes_agent.media import sessions as S
from reyes_agent.media import events as E
from reyes_agent.media import manager as M


def _snap(app_id, status="playing", title="Song", artist="Artist", **kw):
    return S.MediaSnapshot(app_id=app_id, source=S.friendly_source(app_id),
                           status=status, title=title, artist=artist, **kw)


# --- friendly source naming -------------------------------------------------
@pytest.mark.parametrize("app_id,expected", [
    ("Spotify.exe", "spotify"),
    ("chrome.exe", "chrome"),
    ("msedge.exe", "edge"),
    ("vlc.exe", "vlc"),
])
def test_friendly_source_known(app_id, expected):
    assert S.friendly_source(app_id) == expected


def test_friendly_source_unknown_falls_back_lowercased():
    # an unrecognised Store AUMID degrades to a lowercased, path/exe-stripped id
    assert S.friendly_source("SomeApp.exe") == "someapp"
    assert S.friendly_source("") == "media"


# --- snapshot normalisation -------------------------------------------------
def test_snapshot_to_dict_has_label_and_flags():
    s = _snap("Spotify.exe", status="paused", position_s=12.0, duration_s=100.0,
              can_pause=True)
    d = s.to_dict()
    assert d["source"] == "spotify" and d["playing"] is False
    assert "Spotify" in d["label"] and "paused" in d["label"]
    assert d["position_s"] == 12.0 and d["can_pause"] is True


# --- MediaPanelState --------------------------------------------------------
def test_panel_state_active_prefers_the_os_current():
    st = E.MediaPanelState.from_snapshots(
        [_snap("chrome.exe", status="paused"), _snap("Spotify.exe")], "Spotify.exe")
    assert st.active["app_id"] == "Spotify.exe"


def test_panel_state_active_falls_back_to_a_playing_session():
    st = E.MediaPanelState.from_snapshots(
        [_snap("chrome.exe", status="paused"), _snap("Spotify.exe", status="playing")],
        None)
    assert st.active["app_id"] == "Spotify.exe"


def test_mini_card_is_compact_and_present_when_something_plays():
    st = E.MediaPanelState.from_snapshots([_snap("Spotify.exe")], "Spotify.exe")
    card = st.mini_card()
    assert card["title"] == "Song" and card["artist"] == "Artist"
    assert card["playing"] is True
    assert set(card) >= {"source", "title", "artist", "status", "playing", "art_path"}


def test_mini_card_is_none_when_nothing_plays():
    st = E.MediaPanelState.from_snapshots([], None)
    assert st.mini_card() is None
    assert st.to_dict()["any_playing"] is False


# --- MediaEventBus ----------------------------------------------------------
def test_event_bus_delivers_and_unsubscribes():
    bus = E.MediaEventBus()
    seen = []
    off = bus.subscribe(lambda e: seen.append(e.type))
    bus.publish(E.STATE, {"x": 1})
    assert seen == [E.STATE]
    off()
    bus.publish(E.STATE, {"x": 2})
    assert seen == [E.STATE]            # no delivery after unsubscribe


def test_event_bus_isolates_a_bad_subscriber():
    bus = E.MediaEventBus()
    good = []
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe(lambda e: good.append(e.type))
    bus.publish(E.TRACK_CHANGED, {})   # must not raise
    assert good == [E.TRACK_CHANGED]


def test_event_bus_keeps_bounded_history():
    bus = E.MediaEventBus(history=3)
    for i in range(5):
        bus.publish(E.STATE, {"i": i})
    recent = bus.recent(10)
    assert len(recent) == 3 and recent[-1]["payload"]["i"] == 4


# --- MediaManager: target resolution ---------------------------------------
@pytest.fixture()
def two_sessions(monkeypatch):
    snaps = [_snap("Spotify.exe", status="playing"),
             _snap("chrome.exe", status="paused", title="Video", artist="")]
    monkeypatch.setattr(S, "snapshot_sessions", lambda: (snaps, "Spotify.exe"))
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setattr(S, "fetch_album_art", lambda *a, **k: "")  # no real GSMTC
    return snaps


def test_resolve_explicit_source_wins(two_sessions):
    mgr = M.MediaManager()
    assert mgr.resolve_target("turn chrome down") == "chrome.exe"
    assert mgr.resolve_target("spotify") == "Spotify.exe"


def test_resolve_it_uses_the_current_session(two_sessions):
    mgr = M.MediaManager()
    assert mgr.resolve_target("pause it") == "Spotify.exe"


def test_resolve_single_session_is_unambiguous(monkeypatch):
    monkeypatch.setattr(S, "snapshot_sessions",
                        lambda: ([_snap("vlc.exe")], "vlc.exe"))
    monkeypatch.setattr(S, "available", lambda: True)
    assert M.MediaManager().resolve_target("that thing") == "vlc.exe"


# --- MediaManager: describe / status ---------------------------------------
def test_describe_reports_whats_playing(two_sessions):
    text = M.MediaManager().describe()
    assert "spotify" in text.lower()


def test_status_command_returns_state_and_summary(two_sessions):
    out = M.MediaManager().command("status")
    assert out["ok"] and "state" in out
    assert out["state"]["active"]["app_id"] == "Spotify.exe"


# --- MediaManager: transport dispatch + events ------------------------------
def test_transport_command_dispatches_and_emits(monkeypatch):
    snaps = [_snap("Spotify.exe", status="playing")]
    monkeypatch.setattr(S, "snapshot_sessions", lambda: (snaps, "Spotify.exe"))
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setattr(S, "fetch_album_art", lambda *a, **k: "")
    calls = {}

    def fake_control(verb, *, app_id=None, position_s=0.0):
        calls["verb"] = verb
        calls["app_id"] = app_id
        return True
    monkeypatch.setattr(S, "control_session", fake_control)

    mgr = M.MediaManager()
    events = []
    mgr._bus.subscribe(lambda e: events.append(e.type))
    out = mgr.command("pause", reference="it")

    assert out["ok"] and calls["verb"] == "pause" and calls["app_id"] == "Spotify.exe"
    assert out["action"] == "pause" and out["target"] == "Spotify.exe"
    assert E.STATE in events              # a state event was published


def test_unknown_action_is_rejected_cleanly(two_sessions):
    out = M.MediaManager().command("frobnicate")
    assert out["ok"] is False and "unknown" in out["detail"]


# --- degradation ------------------------------------------------------------
def test_no_sessions_degrades_to_nothing_playing(monkeypatch):
    monkeypatch.setattr(S, "snapshot_sessions", lambda: ([], None))
    monkeypatch.setattr(S, "available", lambda: True)
    assert "Nothing" in M.MediaManager().describe()


def test_spotify_adapter_unconfigured_is_not_available(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    from reyes_agent.media.adapters import SpotifyAdapter
    a = SpotifyAdapter()
    assert a.available() is False
    res = a.play_query("anything")
    assert res["ok"] is False


# --- refcounted speech ducking ---------------------------------------------
def test_duck_refcount_composes_mic_and_speech(monkeypatch):
    import audio_control as ac
    # neutralise the real pycaw work; test only the refcount accounting
    monkeypatch.setattr(ac, "_load_audio_utilities", lambda: (None, None))
    # reset module state
    ac._duck_refcount = 0
    ac._ducked = False
    ac._saved_sessions = []

    os.environ["ZENO_DUCK_ON_SPEAK"] = "1"
    from reyes_agent.media.ducking import duck_for_speech, unduck_after_speech
    ac.duck_music(0.2)                       # mic
    assert ac.duck_depth() == 1
    duck_for_speech()                        # speech
    assert ac.duck_depth() == 2
    unduck_after_speech()                    # speech releases
    assert ac.duck_depth() == 1              # still held by mic
    ac.restore_music()                       # mic releases
    assert ac.duck_depth() == 0


def test_speak_duck_gate_off_is_a_noop(monkeypatch):
    import audio_control as ac
    ac._duck_refcount = 0
    os.environ["ZENO_DUCK_ON_SPEAK"] = "0"
    from reyes_agent.media.ducking import duck_for_speech
    assert duck_for_speech() is False
    assert ac.duck_depth() == 0
    os.environ["ZENO_DUCK_ON_SPEAK"] = "1"   # restore for other tests


# --- live poller (external changes -> events) ------------------------------
def test_poll_tick_emits_only_on_track_change(monkeypatch):
    box = {"snaps": [_snap("Spotify.exe", title="A")]}
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setattr(S, "snapshot_sessions",
                        lambda: (box["snaps"], "Spotify.exe"))
    monkeypatch.setattr(S, "fetch_album_art", lambda *a, **k: "")

    mgr = M.MediaManager()
    events = []
    mgr._bus.subscribe(lambda e: events.append(e.type))

    assert mgr.poll_tick() is True          # first tick sets the baseline
    baseline = len(events)
    assert mgr.poll_tick() is False         # same track -> nothing emitted
    assert len(events) == baseline
    box["snaps"] = [_snap("Spotify.exe", title="B")]
    assert mgr.poll_tick() is True          # track changed -> emit
    assert E.TRACK_CHANGED in events


def test_live_watcher_refcount_starts_and_stops_poller(monkeypatch):
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setattr(S, "snapshot_sessions", lambda: ([], None))
    mgr = M.MediaManager()
    mgr._poll_interval = 0.05
    assert mgr._poll_thread is None
    mgr.add_live_watcher()
    mgr.add_live_watcher()                  # second watcher, same thread
    assert mgr._poll_thread is not None and mgr._poll_thread.is_alive()
    assert mgr.status()["live_watchers"] == 2
    mgr.remove_live_watcher()
    assert mgr._poll_thread is not None      # one watcher still holds it
    mgr.remove_live_watcher()
    assert mgr._poll_refs == 0               # last watcher gone -> poller released


# --- resilience: the media-key safety net + degradation --------------------
def test_windows_adapter_uses_gsmtc_when_it_succeeds(monkeypatch):
    from reyes_agent.media.adapters import WindowsMediaAdapter
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setattr(S, "control_session", lambda *a, **k: True)
    a = WindowsMediaAdapter()
    monkeypatch.setattr(a, "_media_key_fallback",
                        lambda verb: {"ok": False, "detail": "must not be called"})
    res = a.command("pause", app_id="Spotify.exe")
    assert res["ok"] and res["method"] == "gsmtc"


def test_windows_adapter_falls_back_to_media_keys_when_gsmtc_rejects(monkeypatch):
    from reyes_agent.media.adapters import WindowsMediaAdapter
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setattr(S, "control_session", lambda *a, **k: False)   # OS said no
    a = WindowsMediaAdapter()
    called = {}

    def fake_fb(verb):
        called["verb"] = verb
        return {"ok": True, "detail": "media key", "method": "media_key"}
    monkeypatch.setattr(a, "_media_key_fallback", fake_fb)
    res = a.command("pause", app_id="Spotify.exe")
    assert called["verb"] == "pause" and res["ok"]


def test_windows_adapter_uses_media_keys_when_gsmtc_absent(monkeypatch):
    from reyes_agent.media.adapters import WindowsMediaAdapter
    monkeypatch.setattr(S, "available", lambda: False)   # no winsdk at all
    a = WindowsMediaAdapter()
    called = {}

    def fake_fb(verb):
        called["verb"] = verb
        return {"ok": True}
    monkeypatch.setattr(a, "_media_key_fallback", fake_fb)
    a.command("next")
    assert called["verb"] == "next"


def test_seek_has_no_media_key_and_degrades(monkeypatch):
    from reyes_agent.media.adapters import WindowsMediaAdapter
    monkeypatch.setattr(S, "available", lambda: True)
    monkeypatch.setattr(S, "control_session", lambda *a, **k: False)
    res = WindowsMediaAdapter().command("seek", position_s=30)
    assert res["ok"] is False           # nothing accepted it; no key for seek


def test_app_volume_without_pycaw_degrades(monkeypatch):
    from reyes_agent.media.adapters import SystemAudioAdapter
    a = SystemAudioAdapter()
    monkeypatch.setattr(a, "available", lambda: False)
    res = a.set_app_volume("Spotify.exe", 0.5)
    assert res["ok"] is False and "pycaw" in res["detail"]


def test_snapshot_degrades_when_gsmtc_unavailable(monkeypatch):
    monkeypatch.setattr(S, "available", lambda: False)
    snaps, current = S.snapshot_sessions()
    assert snaps == [] and current is None
