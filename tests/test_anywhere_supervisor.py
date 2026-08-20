"""ZENO Anywhere supervisor internals: recovery, status honesty, rendezvous.

Separate from test_zeno_anywhere.py (which covers the auth/device contracts)
so the two sessions working on ZENO Anywhere do not collide on one test file.
The focus here is the plumbing that keeps ZENO reachable: backoff, the
restart-storm breaker, the hairpin-tolerant health check, and a dead
supervisor reading as OFFLINE rather than a stale ONLINE.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.remote_access import anywhere, rendezvous  # noqa: E402


@pytest.fixture()
def clock(monkeypatch):
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
        clock["t"] += 1000
    assert delays[0] < delays[1] < delays[2]
    assert max(delays) <= anywhere.BACKOFF_MAX_S


def test_a_restart_storm_trips_the_breaker(clock):
    child = anywhere.Child("server", ["x"])
    for _ in range(anywhere.BREAKER_FAILURES):
        child.note_failure()
    assert child.next_try - clock["t"] >= anywhere.BREAKER_COOLDOWN_S - 1
    assert child.may_try() is False


# --- status honesty ------------------------------------------------------
def test_a_stale_status_file_reads_stale_not_online(tmp_path, monkeypatch):
    import json
    import time

    status = tmp_path / "status.json"
    status.write_text(json.dumps({"state": "ONLINE",
                                  "updated": time.time() - 10_000}), encoding="utf-8")
    monkeypatch.setattr(anywhere, "STATUS_FILE", status)
    assert anywhere.read_status()["state"] == "STALE"


def test_no_status_file_reads_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(anywhere, "STATUS_FILE", tmp_path / "nope.json")
    assert anywhere.read_status()["state"] == "OFFLINE"


# --- the hairpin-tolerant tunnel health check ----------------------------
def test_tunnel_is_healthy_when_the_log_last_shows_a_registration(tmp_path):
    """A home router that cannot hairpin makes the public probe fail even
    while phones connect. cloudflared's log is the reliable local truth."""
    log = tmp_path / "cf.log"
    log.write_text(
        '{"level":"info","message":"Starting tunnel"}\n'
        '{"level":"info","message":"Registered tunnel connection connIndex=0"}\n'
        '{"level":"info","message":"Registered tunnel connection connIndex=1"}\n',
        encoding="utf-8")
    assert anywhere.tunnel_connection_healthy(log) is True


def test_tunnel_is_unhealthy_when_the_log_last_shows_a_loss(tmp_path):
    log = tmp_path / "cf.log"
    log.write_text(
        '{"level":"info","message":"Registered tunnel connection connIndex=0"}\n'
        '{"level":"warn","message":"Lost connection with the edge"}\n',
        encoding="utf-8")
    assert anywhere.tunnel_connection_healthy(log) is False


def test_a_missing_cloudflared_log_is_unhealthy_not_a_crash(tmp_path):
    assert anywhere.tunnel_connection_healthy(tmp_path / "absent.log") is False


# --- rendezvous ----------------------------------------------------------
def test_publish_skips_cleanly_without_a_secret(monkeypatch):
    monkeypatch.setattr(rendezvous, "_secret", lambda: "")
    ok, msg = rendezvous.publish("https://x.trycloudflare.com")
    assert ok is False and "secret" in msg.lower()


def test_publish_sends_the_bearer_secret_and_the_url(monkeypatch):
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
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = req.data
        return _Resp()

    monkeypatch.setattr(rendezvous, "_secret", lambda: "s3cr3t")
    monkeypatch.setattr(rendezvous.urllib.request, "urlopen", fake_urlopen)
    ok, _ = rendezvous.publish("https://abc.trycloudflare.com")
    assert ok is True
    assert captured["auth"] == "Bearer s3cr3t"
    assert b"abc.trycloudflare.com" in captured["body"]


# --- auto-start + provisioning safety ------------------------------------
def test_scheduled_task_targets_the_supervisor_and_holds_no_secret():
    from tools import zeno_anywhere_startup

    body = zeno_anywhere_startup.task_xml(user_id="TEST\\Owner")
    assert str(zeno_anywhere_startup.BOOTSTRAP) in body
    assert str(zeno_anywhere_startup.ROOT) in body
    assert "IgnoreNew" in body and "RestartOnFailure" in body
    for forbidden in ("password", "ANYWHERE_SECRET", "RENDEZVOUS_SECRET"):
        assert forbidden.lower() not in body.lower()


def test_provision_reads_the_password_with_getpass_never_argv():
    import inspect

    from reyes_agent.auth import provision

    source = inspect.getsource(provision)
    assert "getpass" in source and "sys.argv" not in source
