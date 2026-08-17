from __future__ import annotations

import time
import json
from pathlib import Path


def test_agent_space_uses_canonical_runtime_registry() -> None:
    from reyes_agent import agent_runtime, agent_space

    view = agent_space.snapshot(event_limit=10)
    assert view["master"]["id"] == "zeno"
    assert view["master"]["final_synthesizer"] is True
    assert [row["id"] for row in view["agents"]] == list(agent_runtime.AGENT_ROLES)
    assert view["summary"]["registered"] == len(agent_runtime.AGENT_ROLES)
    assert view["source"].startswith("agent_runtime + agent_teams")


def test_agent_space_never_exposes_sensitive_event_payload(monkeypatch) -> None:
    from reyes_agent import agent_space, event_bus

    monkeypatch.setattr(event_bus, "history", lambda **_kwargs: [{
        "id": 1, "ts": time.time(), "ts_human": "2026-08-12 12:00:00",
        "type": "agent.handoff", "source": "test", "correlation_id": "task-1",
        "payload": {
            "from": "zeno", "to": "stark", "agent": "stark", "task_id": "task-1",
            "task": "Check api_key=sk-1234567890abcdefghijkl and user@example.com",
            "private_prompt": "never display me", "authorization": "Bearer secret-token-value",
        },
    }])
    view = agent_space.snapshot(event_limit=10)
    encoded = repr(view["events"])
    assert "sk-123456" not in encoded
    assert "user@example.com" not in encoded
    assert "private_prompt" not in encoded
    assert "Bearer secret" not in encoded
    assert "[private]" in encoded


def test_agent_space_ignores_non_runtime_test_actors(monkeypatch) -> None:
    from reyes_agent import agent_space, event_bus

    monkeypatch.setattr(event_bus, "history", lambda **_kwargs: [{
        "id": 1, "ts": time.time(), "ts_human": "2026-08-12 12:00:00",
        "type": "agent.handoff", "source": "phase22-test", "correlation_id": "probe",
        "payload": {"from": "PHASE22", "to": "FAKE_AGENT", "task": "synthetic probe"},
    }])
    assert agent_space.snapshot(event_limit=10)["events"] == []


def test_phone_agent_projection_is_compact() -> None:
    from reyes_agent import agent_space

    view = agent_space.snapshot(event_limit=10, phone=True)
    assert view["agents"]
    assert "workers" not in view["agents"][0]
    assert "allowed_tools" not in view["agents"][0]
    assert set(view["agents"][0]) == {
        "id", "name", "color", "role", "state", "speaking", "routed",
        "active_task_count", "current_task", "healthy",
    }


def test_agent_space_frontends_share_one_api_and_stop_when_closed() -> None:
    root = Path(__file__).parents[1]
    dashboard = (root / "reyes_agent/static/index.html").read_text(encoding="utf-8")
    module = (root / "reyes_agent/static/agent_space.js").read_text(encoding="utf-8")
    phone = (root / "reyes_agent/static/phone.html").read_text(encoding="utf-8")
    mini = (root / "reyes_agent/static/agent_presence.js").read_text(encoding="utf-8")

    assert "ZENO Agent Space" in dashboard
    assert "data-agent-space-mode=\"flow\"" in dashboard
    assert 'agent_space.js?v=3' in dashboard
    assert "fetch('/api/agent-space?limit=70'" in module
    assert "clearInterval(state.timer)" in module
    assert "body.replaceChildren()" in module
    assert "request('/api/phone/agents')" in phone
    assert "ZENO coordinating" in mini


def test_phone_pwa_does_not_cache_authenticated_api() -> None:
    root = Path(__file__).parents[1]
    worker = (root / "reyes_agent/static/phone-sw.js").read_text(encoding="utf-8")
    manifest = (root / "reyes_agent/static/phone-manifest.json").read_text(encoding="utf-8")
    assert "url.pathname.startsWith('/api/')" in worker
    assert '"display": "standalone"' in manifest


def test_phone_command_enforces_remote_risk_policy_before_chat(monkeypatch) -> None:
    from starlette.requests import Request
    from reyes_agent import phone_security, web
    from reyes_agent.remote_access import policy

    class Security:
        @staticmethod
        def claim_command(_device_id, _command_id, _nonce):
            return True

    monkeypatch.setattr(phone_security, "get_phone_security", lambda: Security())
    monkeypatch.setattr(web, "chat", lambda _request: (_ for _ in ()).throw(
        AssertionError("blocked phone command reached ZENO chat")))
    policy.reset_rates()
    request = Request({"type": "http", "method": "POST", "path": "/api/phone/command",
                       "headers": [], "scheme": "http", "server": ("192.168.1.2", 8768),
                       "client": ("192.168.1.20", 50000)})
    command = web.PhoneCommandRequest(command_id="one", nonce="nonce-one",
                                      timestamp=time.time(), message="transfer 500 dollars")
    result = web.phone_command(command, request, session={
        "device_id": "phone-1", "scopes": json.dumps(["status", "talk"]),
    })
    assert result["blocked"] is True
    assert result["category"] == policy.FINANCIAL


def test_agent_space_voice_command_is_local_and_event_driven(monkeypatch) -> None:
    from reyes_agent import notification_bus, web

    events: list[dict] = []
    monkeypatch.setattr(notification_bus, "publish", events.append)
    reply = web._fast_local_reply("show me all your agents")
    assert reply is not None
    assert events == [{"type": "agent_space", "mode": "space", "focus": ""}]
