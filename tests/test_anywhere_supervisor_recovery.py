"""ZENO Anywhere: persistence, recovery and the rendezvous.

The tests that matter are the RECOVERY ones -- backoff grows, a restart storm
trips the breaker, and a dead supervisor reads as OFFLINE not a stale ONLINE.
Those are the behaviours that decide whether ZENO is actually reachable the
morning after a crash, and they are exercised with a controllable clock so
they are fast and deterministic.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.remote_access import anywhere, rendezvous  # noqa: E402


@pytest.fixture()
def clock(monkeypatch):
    """A controllable clock, so backoff and staleness are deterministic."""
    state = {"t": 1_000_000.0}
    monkeypatch.setattr(anywhere, "_now", lambda: state["t"])
    return state


# --- recovery policy -----------------------------------------------------
def test_backoff_grows_then_is_capped(clock):
    child = anywhere.Child("tunnel", ["x"])
    delays = []
    for _ in range(8):
        before = clock["t"]
        child.note_failure()
        delays.append(child.next_try - before)
        clock["t"] += 1000        # jump past the wait so the next one records
    # Monotonic up to the cap, and never above BACKOFF_MAX_S.
    assert delays[0] < delays[1] < delays[2]
    assert max(delays) <= anywhere.BACKOFF_MAX_S


def test_a_restart_storm_trips_the_breaker(clock):
    child = anywhere.Child("server", ["x"])
    for _ in range(anywhere.BREAKER_FAILURES):
        child.note_failure()
    # After the storm, the next attempt is pushed a full cooldown away, not a
    # few seconds -- this is what stops an unfixable child from being
    # relaunched hundreds of times a minute.
    assert child.next_try - clock["t"] >= anywhere.BREAKER_COOLDOWN_S - 1
    assert child.may_try() is False


def test_may_try_respects_the_next_try_time(clock):
    child = anywhere.Child("tunnel", ["x"])
    child.note_failure()
    assert child.may_try() is False
    clock["t"] += anywhere.BACKOFF_MAX_S + 1
    assert child.may_try() is True


# --- status honesty ------------------------------------------------------
def test_status_is_offline_when_the_supervisor_never_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(anywhere, "STATUS_FILE", tmp_path / "nope.json")
    data = anywhere.read_status()
    assert data["state"] == "OFFLINE"


def test_a_stale_status_file_reads_stale_not_online(tmp_path, monkeypatch):
    """A supervisor that died leaves its last ONLINE status behind. Reporting
    that as ONLINE would be a lie -- an old file must read STALE."""
    import json
    import time

    status = tmp_path / "status.json"
    status.write_text(json.dumps({"state": "ONLINE",
                                  "updated": time.time() - 10_000}), encoding="utf-8")
    monkeypatch.setattr(anywhere, "STATUS_FILE", status)
    assert anywhere.read_status()["state"] == "STALE"


def test_a_fresh_status_file_reads_through(tmp_path, monkeypatch):
    import json
    import time

    status = tmp_path / "status.json"
    status.write_text(json.dumps({"state": "ONLINE", "updated": time.time(),
                                  "server": {"ok": True}, "tunnel": {"ok": True}}),
                      encoding="utf-8")
    monkeypatch.setattr(anywhere, "STATUS_FILE", status)
    assert anywhere.read_status()["state"] == "ONLINE"


def test_format_status_renders_the_offline_and_online_shapes():
    offline = anywhere.format_status({"state": "OFFLINE", "reason": "not running"})
    assert "OFFLINE" in offline and "zenoai321.netlify.app" in offline
    online = anywhere.format_status({
        "state": "ONLINE", "server": {"ok": True, "port": 8768, "owned": True, "restarts": 0},
        "tunnel": {"ok": True, "url": "https://x.trycloudflare.com", "restarts": 1},
        "internet": True, "public_entry": "https://zenoai321.netlify.app", "uptime_s": 3720})
    assert "ONLINE" in online and "1h 2m" in online and "trycloudflare" in online


# --- health probes fail safe ---------------------------------------------
def test_probes_fail_safe_rather_than_raise():
    # A probe that raised would crash the monitor loop. An unreachable target
    # must come back False. (server_healthy is not asserted here because a real
    # ZENO server may legitimately be running on 8768 during development -- it
    # is only asserted to return a bool.)
    assert anywhere.tunnel_reachable("", timeout=1) is False
    assert anywhere.tunnel_reachable("https://definitely-not-real-xyz.trycloudflare.com",
                                     timeout=2) is False
    assert isinstance(anywhere.server_healthy(timeout=1), bool)


# --- rendezvous ----------------------------------------------------------
def test_publish_skips_cleanly_without_a_secret(monkeypatch):
    monkeypatch.setattr(rendezvous, "_secret", lambda: "")
    ok, msg = rendezvous.publish("https://x.trycloudflare.com")
    assert ok is False
    assert "secret" in msg.lower()


def test_publish_posts_with_the_bearer_secret(monkeypatch):
    captured = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = req.data
        return _Resp()

    monkeypatch.setattr(rendezvous, "_secret", lambda: "s3cr3t-value")
    monkeypatch.setattr(rendezvous.urllib.request, "urlopen", fake_urlopen)
    ok, _msg = rendezvous.publish("https://abc.trycloudflare.com")
    assert ok is True
    assert captured["url"].endswith("/api/endpoint")
    assert captured["auth"] == "Bearer s3cr3t-value"
    assert b"abc.trycloudflare.com" in captured["body"]


def test_configured_reflects_the_secret(monkeypatch):
    monkeypatch.setattr(rendezvous, "_secret", lambda: "")
    assert rendezvous.configured() is False
    monkeypatch.setattr(rendezvous, "_secret", lambda: "x")
    assert rendezvous.configured() is True


# --- auto-start ----------------------------------------------------------
def test_startup_task_points_at_the_project_and_the_supervisor():
    from tools import zeno_anywhere_startup

    body = zeno_anywhere_startup.task_xml(user_id="TEST\\Owner")
    assert str(zeno_anywhere_startup.BOOTSTRAP) in body
    assert str(zeno_anywhere_startup.ROOT) in body
    assert "IgnoreNew" in body
    # No secret, token or password ever belongs in the task definition.
    for forbidden in ("password", "ANYWHERE_SECRET", "RENDEZVOUS_SECRET"):
        assert forbidden.lower() not in body.lower()


def test_provision_module_never_puts_a_password_on_the_command_line():
    """The password path is getpass, not argv -- so it never reaches shell
    history or the process list."""
    import inspect

    from reyes_agent.auth import provision

    source = inspect.getsource(provision)
    assert "getpass" in source
    assert "sys.argv" not in source     # never read the password from argv
