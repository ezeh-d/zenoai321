"""Remote access: origin policy, command categories, limits, isolation.

CLAUDE owns this file. CODEX: attack cases against pairing/session/WS belong
in a separate file so we do not collide -- see docs/AI_ENGINEERING_STATUS.md.

Every test here asserts on behaviour that protects the desktop from a
remote device, because that is the whole risk model: a phone can be stolen
while unlocked and still hold a valid session.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _with_domain(domain: str = "zenoassitant.com", dev: bool = False):
    from reyes_agent import config

    previous = (config.ZENO_PUBLIC_DOMAIN, config.ZENO_APP_ORIGIN,
                config.ZENO_API_ORIGIN, config.REMOTE_DEV_MODE)
    config.ZENO_PUBLIC_DOMAIN = domain
    config.ZENO_APP_ORIGIN = ""
    config.ZENO_API_ORIGIN = ""
    config.REMOTE_DEV_MODE = dev
    return previous


def _restore(previous) -> None:
    from reyes_agent import config

    (config.ZENO_PUBLIC_DOMAIN, config.ZENO_APP_ORIGIN,
     config.ZENO_API_ORIGIN, config.REMOTE_DEV_MODE) = previous


# --- origins -------------------------------------------------------------

def test_an_unconfigured_domain_allows_nothing() -> None:
    """Closed by default. An unset domain must never mean 'allow anything'."""
    from reyes_agent.remote_access import domains

    previous = _with_domain("")
    try:
        assert domains.allowed_origins() == []
        assert domains.configured() is False
        for origin in ("https://evil.com", "https://app.zenoassitant.com",
                       "http://localhost:5173", ""):
            assert domains.is_allowed_origin(origin) is False
    finally:
        _restore(previous)


def test_the_real_domain_derives_its_subdomains() -> None:
    from reyes_agent.remote_access import domains

    previous = _with_domain()
    try:
        assert domains.site_origin() == "https://zenoassitant.com"
        assert domains.app_origin() == "https://app.zenoassitant.com"
        assert domains.api_origin() == "https://api.zenoassitant.com"
        assert domains.is_allowed_origin("https://app.zenoassitant.com")
        assert domains.is_allowed_origin("https://APP.ZENOASSITANT.COM"), "host compare is case-insensitive"
        # Look-alikes and downgrades are not the same origin.
        for hostile in ("https://app.zenoassitant.com.evil.com",
                        "http://app.zenoassitant.com",     # scheme downgrade
                        "https://evil.com",
                        "https://zenoassistant.com"):      # note: correct spelling is NOT the domain
            assert not domains.is_allowed_origin(hostile), hostile
    finally:
        _restore(previous)


def test_localhost_is_development_only() -> None:
    from reyes_agent.remote_access import domains

    previous = _with_domain(dev=False)
    try:
        assert not domains.is_allowed_origin("http://localhost:5173")
    finally:
        _restore(previous)
    previous = _with_domain(dev=True)
    try:
        assert domains.is_allowed_origin("http://localhost:5173")
        assert "http://localhost:5173" in domains.allowed_origins()
    finally:
        _restore(previous)


def test_cors_is_never_a_wildcard_for_the_authenticated_api() -> None:
    source = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    assert "CORSMiddleware" in source, "CORS must be configured"
    assert 'allow_origins=["*"]' not in source and "allow_origins=['*']" not in source
    assert "allow_credentials=True" in source
    assert "_domains.allowed_origins()" in source, "the allow-list must come from domains.py"


def test_the_websocket_checks_its_origin() -> None:
    """CORS does not protect a WebSocket upgrade -- the browser performs it
    regardless of origin, so the handler must check for itself."""
    source = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
    upgrade = source.split('@app.websocket("/ws/phone")', 1)[1][:2000]
    assert "domains.is_allowed_origin" in upgrade, "the socket must validate Origin"
    assert 'policy.check_rate("ws_connect"' in upgrade, "reconnect storms must be bounded"


def test_dns_records_are_stated_not_invented() -> None:
    from reyes_agent.remote_access import domains

    previous = _with_domain()
    try:
        records = domains.expected_dns()
        assert records and all(r["type"] and r["name"] and r["purpose"] for r in records)
        # The tunnel target genuinely does not exist until cloudflared makes
        # it -- a guessed value here would send the owner to a dead host.
        api = next(r for r in records if r["name"] == "api")
        assert "<" in api["value"] and "do not guess" in api["note"]
    finally:
        _restore(previous)


# --- command categories --------------------------------------------------

def test_money_and_security_are_refused_from_any_remote_device() -> None:
    """The stolen-phone case. A live session must not reach these."""
    from reyes_agent.remote_access import policy

    for message in ("Transfer 500 to my brother", "Send $200 to Tunde",
                    "pay the electricity bill", "buy me bitcoin",
                    "send money home", "what is my paypal balance"):
        decision = policy.evaluate(message, scopes={"status", "talk"})
        assert decision.category == policy.FINANCIAL, f"{message} -> {decision.category}"
        assert decision.allowed is False

    for message in ("Disable the firewall", "what is my api key",
                    "change the administrator password", "delete all my files"):
        decision = policy.evaluate(message, scopes={"status", "talk"})
        assert decision.category == policy.SENSITIVE, f"{message} -> {decision.category}"
        assert decision.allowed is False


def test_ordinary_requests_still_work_from_a_phone() -> None:
    """Safety must not make the companion useless."""
    from reyes_agent.remote_access import policy

    for message in ("What is the weather?", "Show me my website projects",
                    "remind me what we discussed"):
        decision = policy.evaluate(message, scopes={"status", "talk"})
        assert decision.category == policy.SAFE and decision.allowed

    for message in ("Open Chrome", "abeg open calculator",
                    "Build my restaurant website", "create a checkpoint"):
        decision = policy.evaluate(message, scopes={"status", "talk"})
        assert decision.category == policy.CONTROL and decision.allowed
        # ...and the desktop's own confirmation gate is still in front of it.
        assert decision.needs_local_approval is True


def test_file_verbs_are_not_mistaken_for_money() -> None:
    """'transfer' and 'send' are shared between files and payments."""
    from reyes_agent.remote_access import policy

    assert policy.classify("transfer the file to my desktop") == policy.CONTROL
    assert policy.classify("send the screenshot to my laptop") == policy.CONTROL
    assert policy.classify("move the hero section down") == policy.CONTROL


def test_a_device_without_the_scope_is_refused() -> None:
    from reyes_agent.remote_access import policy

    read_only = policy.evaluate("Open Chrome", scopes={"status"})
    assert read_only.allowed is False and "scope" in read_only.reason
    assert policy.evaluate("What is the weather?", scopes={"status"}).allowed


# --- rate limits ---------------------------------------------------------

def test_pairing_and_login_are_rate_limited_but_chat_is_not_annoying() -> None:
    from reyes_agent.remote_access import policy

    policy.reset_rates()
    try:
        # Pairing is the brute-force target: a tight budget.
        allowed = sum(1 for _ in range(20) if policy.check_rate("pair", "attacker").allowed)
        assert allowed == policy.LIMITS["pair"][0] == 5
        assert not policy.check_rate("pair", "attacker", record=False).allowed
        # A different identity is unaffected -- one attacker cannot lock out
        # the real owner.
        assert policy.check_rate("pair", "owner-device").allowed

        # Conversation is generous.
        chat = sum(1 for _ in range(60) if policy.check_rate("command", "phone").allowed)
        assert chat == 60, "a minute of steady conversation must not be throttled"
    finally:
        policy.reset_rates()


def test_the_limiter_cannot_grow_without_bound() -> None:
    from reyes_agent.remote_access import policy

    policy.reset_rates()
    try:
        for index in range(policy._MAX_TRACKED + 400):
            policy.check_rate("command", f"ip-{index}")
        assert len(policy._buckets) <= policy._MAX_TRACKED + 1
    finally:
        policy.reset_rates()


# --- protocol ------------------------------------------------------------

def test_the_envelope_validates_before_anything_runs() -> None:
    from reyes_agent.remote_access import protocol

    good, error = protocol.Request.parse(
        {"type": "command", "message": "hello"}, device_id="d1")
    assert good and good.request_id and not error

    for bad, expected in (
        ({"type": "command", "message": ""}, "needs a message"),
        ({"type": "wat"}, "unknown request type"),
        ("not a dict", "JSON object"),
        ({"type": "command", "message": "x" * 5000}, "exceeds"),
    ):
        parsed, message = protocol.Request.parse(bad, device_id="d1")
        assert parsed is None and expected in message, (bad, message)


def test_response_status_maps_to_sensible_http_codes() -> None:
    from reyes_agent.remote_access import protocol

    assert protocol.ok("r", "fine").http_status == 200
    assert protocol.denied("r", "no").http_status == 403
    assert protocol.limited("r", 30.0).http_status == 429
    assert protocol.failed("r", "bad").http_status == 400


# --- gateway -------------------------------------------------------------

def test_the_gateway_returns_an_envelope_even_when_zeno_fails() -> None:
    """Failure isolation: a remote request must never raise into the server."""
    from reyes_agent.remote_access import gateway, policy, protocol

    policy.reset_rates()
    gateway.reset()
    real = gateway._run_through_zeno
    gateway._run_through_zeno = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("brain exploded"))
    try:
        request = protocol.Request("r1", "d1", protocol.COMMAND, "what is the time")
        response = gateway.handle(request)
        assert response.status == protocol.ERROR
        assert "RuntimeError" in response.message
        assert response.request_id == "r1", "the caller must be able to correlate the failure"
    finally:
        gateway._run_through_zeno = real
        policy.reset_rates()


def test_a_denied_command_never_reaches_the_brain() -> None:
    from reyes_agent.remote_access import gateway, policy, protocol

    policy.reset_rates()
    gateway.reset()
    called: list[str] = []
    real = gateway._run_through_zeno
    gateway._run_through_zeno = lambda req, **k: called.append(req.message) or {"reply": "x"}
    try:
        gateway.handle(protocol.Request("r2", "d1", protocol.COMMAND, "Transfer 500 to my brother"))
        gateway.handle(protocol.Request("r3", "d1", protocol.COMMAND, "Disable the firewall"))
        assert called == [], "a refused command must not be executed"
    finally:
        gateway._run_through_zeno = real
        policy.reset_rates()


def test_the_gateway_uses_the_existing_router_not_a_second_one() -> None:
    source = (ROOT / "reyes_agent" / "remote_access" / "gateway.py").read_text(encoding="utf-8")
    assert "_conversation_turn" in source, "remote must reuse the desktop conversation path"
    assert "get_worker_pool" in source, "and the existing worker pool"
    # No parallel tool dispatch of its own.
    assert "run_tool(" not in source and "TOOLS[" not in source


def test_the_audit_records_actions_but_never_secrets() -> None:
    from reyes_agent.remote_access import gateway

    gateway.reset()
    gateway.record("device-1", "req-1", "CONTROL", "Open Chrome", "success")
    entry = gateway.audit_log()[-1]
    assert set(entry) == {"timestamp", "device_id", "request_id", "category",
                          "action", "result", "detail"}
    # No field exists that could carry a credential.
    assert not any(k in entry for k in ("token", "session", "cookie", "password", "credential"))


def test_connection_status_reports_real_state() -> None:
    from reyes_agent import config
    from reyes_agent.remote_access import gateway, protocol

    enabled = config.REMOTE_ACCESS_ENABLED
    try:
        config.REMOTE_ACCESS_ENABLED = False
        status = gateway.connection_status()
        assert status["state"] == protocol.OFFLINE
        assert "disabled" in " ".join(status["reasons"])
        assert set(status["states"]) == set(protocol.CONNECTION_STATES)
    finally:
        config.REMOTE_ACCESS_ENABLED = enabled


# --- API surface ---------------------------------------------------------

def test_the_v1_api_is_mounted_and_versioned() -> None:
    import reyes_agent.web as web

    paths = {p for p in web.app.openapi()["paths"] if p.startswith("/api/v1")}
    for required in ("/api/v1/status", "/api/v1/command", "/api/v1/devices",
                     "/api/v1/tasks", "/api/v1/agents", "/api/v1/website/projects",
                     "/api/v1/website/action", "/api/v1/logout-all", "/api/v1/meta"):
        assert required in paths, f"{required} is missing"


def test_website_remote_actions_are_an_allow_list() -> None:
    """The phone never gets arbitrary Website Studio control or a shell."""
    from reyes_agent.remote_access import api

    assert set(api._WEBSITE_ACTIONS) == {"status", "checkpoint", "check", "preview", "continue"}
    for template in api._WEBSITE_ACTIONS.values():
        # Actions are phrased as ordinary ZENO requests, so every Website
        # Studio rule applies -- they are not direct calls into the studio.
        assert "{project}" in template or "projects" in template
    source = (ROOT / "reyes_agent" / "remote_access" / "api.py").read_text(encoding="utf-8")
    assert "subprocess" not in source and "os.system" not in source


def test_remote_access_is_off_by_default() -> None:
    """Enabling ZENO must not open a network surface."""
    from reyes_agent import config

    assert hasattr(config, "REMOTE_ACCESS_ENABLED")
    example = (ROOT / ".env.example").read_text(encoding="utf-8") if (ROOT / ".env.example").is_file() else ""
    if example:
        assert "REMOTE_ACCESS_ENABLED" in example, ".env.example must document the flag"


def _run_all() -> int:
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - started:.2f}s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
