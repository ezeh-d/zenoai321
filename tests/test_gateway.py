"""The Cloudflare tunnel gateway, and the boundary that keeps it safe.

The gateway is mocked -- no real tunnel is opened in a test. The point is
ZENO's own logic: it captures the public URL, it refuses to report a running
gateway with no URL, and -- most important -- the boundary exposes only the
owner app and phone surface through it, never the desktop API or social.
"""

from __future__ import annotations

import os
import subprocess

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.remote_access import boundary, tunnel  # noqa: E402


class _FakeProc:
    """A cloudflared that prints a quick-tunnel URL then stays 'running'."""

    def __init__(self, lines, alive=True):
        self.stdout = iter(lines)
        self._alive = alive

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self._alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._alive = False


# --- the boundary: the part that actually protects the machine -----------
def test_the_owner_app_is_reachable_through_the_tunnel():
    for path in ("/app", "/app/sw.js", "/api/owner/auth/login", "/api/owner/status"):
        assert boundary.remote_path_allowed(path) is True, path


def test_the_desktop_api_is_never_reachable_through_the_tunnel():
    for path in ("/api/chat", "/api/agents", "/api/tts", "/api/build/tasks"):
        assert boundary.remote_path_allowed(path) is False, path


def test_social_control_stays_closed_through_the_tunnel():
    for path in ("/api/social/dashboard", "/api/social/kill", "/api/social/publish"):
        assert boundary.remote_path_allowed(path) is False, path


def test_a_tunnelled_request_is_classified_remote_not_loopback():
    """cloudflared adds cf-connecting-ip; if the boundary missed it, every
    tunnelled request would look like loopback and get the full desktop API."""
    assert boundary.is_forwarded_remote({"cf-connecting-ip": "8.8.8.8"}) is True
    assert boundary.is_forwarded_remote({"x-forwarded-for": "8.8.8.8"}) is True


# --- the gateway ---------------------------------------------------------
def test_it_captures_the_public_url(monkeypatch):
    lines = [
        "2026-08-19 INF Thank you for trying Cloudflare Tunnel.\n",
        "2026-08-19 INF |  https://calm-forest-1234.trycloudflare.com   |\n",
        "2026-08-19 INF Connection registered\n",
    ]
    monkeypatch.setattr(tunnel.Gateway, "available", lambda self: True)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc(lines))

    gw = tunnel.reset_for_tests()
    state = gw.start(port=8768)
    assert state.running is True
    assert state.url == "https://calm-forest-1234.trycloudflare.com"
    assert state.mode == "quick"
    gw.stop()


def test_no_url_means_no_running_gateway(monkeypatch):
    """If cloudflared never prints a URL, the gateway must report failure --
    not a running tunnel with no address ('it said it worked')."""
    monkeypatch.setattr(tunnel.Gateway, "available", lambda self: True)
    monkeypatch.setattr(tunnel, "_QUICK_TIMEOUT_S", 0.3)
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: _FakeProc(["INF starting\n"]))

    gw = tunnel.reset_for_tests()
    state = gw.start(port=8768)
    assert state.url == ""
    assert state.running is False
    assert "did not produce a URL" in state.error


def test_missing_cloudflared_is_reported_plainly(monkeypatch):
    monkeypatch.setattr(tunnel.Gateway, "available", lambda self: False)
    gw = tunnel.reset_for_tests()
    state = gw.start()
    assert state.running is False
    assert "cloudflared" in state.error.lower()


def test_named_mode_needs_a_config(monkeypatch):
    monkeypatch.setattr(tunnel.Gateway, "available", lambda self: True)
    monkeypatch.delenv("ZENO_CLOUDFLARE_TUNNEL_CONFIG", raising=False)
    gw = tunnel.reset_for_tests()
    state = gw.start(mode="named")
    assert state.running is False
    assert "named mode needs" in state.error
