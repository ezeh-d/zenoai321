"""Regression evidence for the terminal-independent ZENO Anywhere runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
import uuid


ROOT = Path(__file__).resolve().parents[1]


class _Exited:
    returncode = 7

    @staticmethod
    def poll() -> int:
        return 7


class _Alive:
    returncode = None

    @staticmethod
    def poll() -> None:
        return None


def test_owned_child_crash_enters_bounded_backoff(monkeypatch) -> None:
    from reyes_agent.remote_access import anywhere

    monkeypatch.setattr(anywhere, "_now", lambda: 100.0)
    monkeypatch.setattr(anywhere, "_log", lambda *_args, **_kwargs: None)
    child = anywhere.Child("test", ["ignored"], proc=_Exited(), owned=True)
    assert child.reap_failure() is True
    assert child.proc is None
    assert child.restarts == 1
    assert child.next_try > 100.0
    assert child.reap_failure() is False, "one exit must not be counted repeatedly"


def test_live_tunnel_refreshes_rendezvous_without_busy_polling(monkeypatch, tmp_path) -> None:
    from reyes_agent.remote_access import anywhere, rendezvous

    now = [100.0]
    calls: list[str] = []
    monkeypatch.setattr(anywhere, "_now", lambda: now[0])
    monkeypatch.setattr(anywhere, "URL_FILE", tmp_path / "current_url.txt")
    monkeypatch.setattr(rendezvous, "configured", lambda: True)
    monkeypatch.setattr(rendezvous, "publish",
                        lambda url: (calls.append(url) is None, "HTTP 200"))
    supervisor = anywhere.Supervisor()
    supervisor.url = "https://current.trycloudflare.com"
    supervisor.tunnel.proc = _Alive()
    supervisor.tunnel.owned = True
    supervisor.tunnel_verified = True

    supervisor.ensure_tunnel()
    supervisor.ensure_tunnel()
    assert calls == [supervisor.url]
    now[0] += anywhere.PUBLISH_EVERY_S + 1
    supervisor.ensure_tunnel()
    assert calls == [supervisor.url, supervisor.url]


def test_fresh_tunnel_gets_propagation_grace_before_recycling(monkeypatch) -> None:
    from reyes_agent.remote_access import anywhere

    assert anywhere.URL_TIMEOUT_S >= 60
    assert anywhere.TUNNEL_READY_GRACE_S == 60
    assert anywhere.TUNNEL_FAILED_PROBES >= 3


def test_status_requires_public_verification(monkeypatch, tmp_path) -> None:
    from reyes_agent.remote_access import anywhere

    monkeypatch.setattr(anywhere, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(anywhere, "server_healthy", lambda: True)
    monkeypatch.setattr(anywhere, "internet_up", lambda: True)
    supervisor = anywhere.Supervisor()
    supervisor.url = "https://announced-only.trycloudflare.com"
    supervisor.tunnel.proc = _Alive()
    supervisor.write_status()
    state = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert state["state"] == "DEGRADED"
    assert state["tunnel"]["process_running"] is True
    assert state["tunnel"]["verified"] is False


def test_dead_tunnel_cannot_retain_verified_status(monkeypatch, tmp_path) -> None:
    from reyes_agent.remote_access import anywhere

    monkeypatch.setattr(anywhere, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(anywhere, "server_healthy", lambda: True)
    monkeypatch.setattr(anywhere, "internet_up", lambda: True)
    supervisor = anywhere.Supervisor()
    supervisor.url = "https://stale.trycloudflare.com"
    supervisor.tunnel_verified = True

    supervisor.write_status()

    state = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert state["state"] == "DEGRADED"
    assert state["tunnel"]["process_running"] is False
    assert state["tunnel"]["verified"] is False


def test_local_server_restart_does_not_recycle_tunnel(monkeypatch) -> None:
    from reyes_agent.remote_access import anywhere

    supervisor = anywhere.Supervisor()
    supervisor.url = "https://healthy-tunnel.trycloudflare.com"
    supervisor.tunnel.proc = _Alive()
    supervisor.tunnel.owned = True
    supervisor.tunnel_verified = True
    supervisor.tunnel_probe_failures = 2
    stopped: list[bool] = []
    monkeypatch.setattr(supervisor.tunnel, "stop", lambda: stopped.append(True))
    monkeypatch.setattr(
        anywhere, "tunnel_reachable",
        lambda _url: (_ for _ in ()).throw(AssertionError("probe must be skipped")),
    )

    supervisor.verify_public_path(local_server_ok=False)

    assert stopped == []
    assert supervisor.url.endswith(".trycloudflare.com")
    assert supervisor.tunnel_probe_failures == 0
    assert supervisor.tunnel_verified is False


def test_rendezvous_clear_is_authenticated_and_uses_delete(monkeypatch) -> None:
    from reyes_agent.remote_access import rendezvous

    seen = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_request(request, **_kwargs):
        seen["method"] = request.method
        seen["authorization"] = request.headers.get("Authorization")
        return Response()

    monkeypatch.setattr(rendezvous, "_entry", lambda: "https://zeno.example")
    monkeypatch.setattr(rendezvous, "_secret", lambda: "fixture-secret")
    monkeypatch.setattr(rendezvous.urllib.request, "urlopen", open_request)
    assert rendezvous.clear()[0] is True
    assert seen == {"method": "DELETE", "authorization": "Bearer fixture-secret"}


def test_single_instance_guard_refuses_a_duplicate(tmp_path) -> None:
    from reyes_agent.remote_access import anywhere

    name = "Local\\ZENOAnywhereTest-" + uuid.uuid4().hex
    lock_file = tmp_path / "supervisor.lock"
    first = anywhere._SingleInstance(name=name, lock_file=lock_file)
    duplicate = anywhere._SingleInstance(name=name, lock_file=lock_file)
    assert first.acquire() is True
    try:
        assert duplicate.acquire() is False
    finally:
        duplicate.release()
        first.release()


def test_startup_task_is_hidden_bounded_and_restartable() -> None:
    from tools import zeno_anywhere_startup

    xml = zeno_anywhere_startup.task_xml(user_id="TEST\\Owner")
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml
    assert "<RestartOnFailure><Interval>PT1M</Interval><Count>999</Count>" in xml
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml
    assert "<Hidden>true</Hidden>" in xml
    assert '<Arguments>-S "' in xml
    assert str(zeno_anywhere_startup.BOOTSTRAP) in xml
    assert "TOKEN" not in xml and "SECRET" not in xml


def test_legacy_cli_delegates_to_the_one_startup_task(monkeypatch) -> None:
    from reyes_agent.remote_access import anywhere
    from tools import zeno_anywhere_startup

    monkeypatch.setattr(zeno_anywhere_startup, "status", lambda: (True, "installed"))
    calls: list[bool] = []
    running = iter((False, False, True))
    monkeypatch.setattr(zeno_anywhere_startup, "start",
                        lambda: (calls.append(True) is None, "scheduled start"))
    monkeypatch.setattr(anywhere, "supervisor_running", lambda: next(running))
    monkeypatch.setattr(anywhere.time, "sleep", lambda _seconds: None)
    assert anywhere.autostart_installed() is True
    assert anywhere._start_registered_task() == (
        True, "ZENO Anywhere started through Task Scheduler.")
    assert calls == [True]


def test_netlify_rendezvous_has_dependency_auth_and_expiry_contracts() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@netlify/blobs"] == "11.0.1"
    source = (ROOT / "netlify" / "functions" / "endpoint.mjs").read_text("utf-8")
    for contract in ("timingSafeEqual", "MAX_AGE_MS", 'req.method === "DELETE"',
                     'store.delete("url")'):
        assert contract in source


def test_public_launcher_rejects_stale_rendezvous_records() -> None:
    source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "data.stale" in source
    assert "Date.now() - updated <= 120000" in source
    assert "trycloudflare\\.com" in source
