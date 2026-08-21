"""Fingerprint step-up and trusted-owner auto-approve.

The phone controls the laptop through the SAME brain and tool registry as the
desktop. What used to make consequential actions feel "unavailable" from the
phone was the approval gate routing the owner back to the PC. These tests pin
the replacement: a fingerprint (WebAuthn) step-up elevates the session, and
while elevated ordinary control/communication tools run instead of queuing --
but a denylist of arbitrary-execution, irreversible, public and security tools
NEVER auto-runs, so a phone unlock can't fire something catastrophic.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent import confirmation  # noqa: E402
from reyes_agent.auth import owner as owner_auth  # noqa: E402


# --- confirmation.owner_auto_approve ---------------------------------------

def test_auto_approve_is_context_scoped():
    assert confirmation.auto_approve_active() == ""
    with confirmation.owner_auto_approve("phone"):
        assert confirmation.auto_approve_active() == "phone"
    # It must not leak past the context.
    assert confirmation.auto_approve_active() == ""


def test_denylist_blocks_dangerous_families_only():
    allow = confirmation.remote_auto_run_allowed
    # Ordinary control / communication the owner asked to work from the phone.
    for name in ["open_app", "close_app", "browser_open", "browser_click",
                 "send_message", "send_slack_message", "send_telegram_message",
                 "type_message"]:
        assert allow(name) is True, name
    # Arbitrary execution, irreversible, public, money, security -- never.
    for name in ["run_command", "coding_execute", "device_execute", "phone_action",
                 "mcp_action", "skill_run", "delete_file", "move_file",
                 "forget_fact", "social_publish", "social_control",
                 "paid_work_set_pricing", "security_authorize", "security_lab"]:
        assert allow(name) is False, name


def test_consequential_tool_runs_only_when_elevated():
    import reyes_agent.tools as tools

    ran = {"n": 0}
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    name = "zzz_stepup_probe"
    if name not in tools.TOOLS:
        @tools.register(name=name, description="test-only", input_schema=schema,
                        requires_confirmation=True)
        def _probe(x: str = "hi") -> str:  # noqa: ANN001
            ran["n"] += 1
            return f"RAN:{x}"

    # No elevation: it queues for confirmation, it does NOT run.
    out = tools.run_tool(name, {"x": "a"})
    assert ran["n"] == 0
    assert "Queued as request" in out

    # Elevated: it runs now.
    with confirmation.owner_auto_approve("phone"):
        out2 = tools.run_tool(name, {"x": "b"})
    assert ran["n"] == 1
    assert out2 == "RAN:b"


def test_denylisted_tool_still_queues_even_when_elevated(monkeypatch):
    import reyes_agent.tools as tools

    ran = {"n": 0}
    schema = {"type": "object", "properties": {}}
    name = "zzz_stepup_danger"
    if name not in tools.TOOLS:
        @tools.register(name=name, description="test-only", input_schema=schema,
                        requires_confirmation=True)
        def _danger() -> str:
            ran["n"] += 1
            return "RAN"

    # Force the denylist to treat this probe as dangerous.
    monkeypatch.setattr(confirmation, "remote_auto_run_allowed",
                        lambda n: n != name)
    with confirmation.owner_auto_approve("phone"):
        out = tools.run_tool(name, {})
    assert ran["n"] == 0
    assert "Queued as request" in out


# --- owner session elevation ------------------------------------------------

def test_session_elevation_lifecycle(tmp_path):
    service = owner_auth.reset_for_tests(tmp_path / "owner.sqlite")
    service.provision("owner@zeno.local", "correct-horse-battery-staple")
    token = "sess-token-xyz"

    assert service.session_elevated(token) is False
    assert service.elevation_status(token)["elevated"] is False

    # A verified fingerprint would set this; simulate its effect.
    service._elevations[token] = time.time() + owner_auth.ELEVATION_TTL_S
    assert service.session_elevated(token) is True
    status = service.elevation_status(token)
    assert status["elevated"] is True and status["seconds_left"] > 0

    service.clear_elevation(token)
    assert service.session_elevated(token) is False


def test_expired_elevation_is_not_elevated(tmp_path):
    service = owner_auth.reset_for_tests(tmp_path / "owner.sqlite")
    service.provision("owner@zeno.local", "correct-horse-battery-staple")
    token = "sess-expired"
    service._elevations[token] = time.time() - 1  # already lapsed
    assert service.session_elevated(token) is False
    # And it is cleaned up, not left to accumulate.
    assert token not in service._elevations
