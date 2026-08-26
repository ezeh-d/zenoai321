"""The terminal status dashboard renders (rich + plain) without crashing and
maps states to the right colours -- with a synthetic snapshot so the test does
not import the whole tool registry."""

from __future__ import annotations

from reyes_agent import status_dashboard as sd

_SNAPSHOT = {
    "status": {
        "tools": 300, "areas_connected": 2, "areas_total": 3,
        "areas": [
            {"label": "Desktop control", "area": "desktop", "connected": True, "tools": 13},
            {"label": "Voice", "area": "voice", "connected": True, "tools": 3},
            {"label": "Conversation", "area": "conversation", "connected": False, "tools": 0},
        ],
        "adapters": [
            {"name": "camera_vision", "category": "hardware", "status": "DISABLED"},
            {"name": "observability", "category": "external", "status": "AUTH_REQUIRED"},
        ],
        "quarantined": [],
        "proven_active": ["open_app"],
    },
    "hands": {
        "hands": {"keyboard": "READY", "mouse": "READY"},
        "communication": {"email": "READY", "sms": "NOT_CONNECTED"},
    },
    "mic": ("Microphone (USBAudio1.0)", "bold green"),
}


def test_status_style_mapping():
    assert sd._status_style("READY") == sd._OK
    assert sd._status_style("AVAILABLE") == sd._OK
    assert sd._status_style("AUTH_REQUIRED") == sd._WARN
    assert sd._status_style("NOT_CONNECTED") == sd._BAD
    assert sd._status_style("") == sd._BAD


def test_plain_render_has_key_facts(capsys):
    sd._render_plain(_SNAPSHOT)
    out = capsys.readouterr().out
    assert "ZENO" in out and "SYSTEM STATUS" in out
    assert "Desktop control" in out and "[+]" in out
    assert "[ ] Conversation" in out
    assert "USBAudio1.0" in out


def test_rich_render_does_not_crash():
    # rich is a dependency; this must complete for the synthetic snapshot.
    sd._render_rich(dict(_SNAPSHOT))


def test_render_falls_back_when_rich_unavailable(monkeypatch, capsys):
    # Force the rich path to blow up; render() must degrade to plain text.
    monkeypatch.setattr(sd, "_gather", lambda: _SNAPSHOT)
    monkeypatch.setattr(sd, "_render_rich", lambda data: (_ for _ in ()).throw(RuntimeError("no tty")))
    sd.render()
    out = capsys.readouterr().out
    assert "ZENO" in out and "Desktop control" in out


def test_mic_line_never_raises():
    name, style = sd._mic_line()
    assert isinstance(name, str) and isinstance(style, str)
