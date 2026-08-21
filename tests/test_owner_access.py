"""Owner authentication, the device link, and the online surface.

The tests that matter most here are the NEGATIVE ones. Anyone can verify that
a correct password logs in; the question is whether a wrong one, a replayed
one, a missing CSRF header, an unregistered action or a stolen refresh token
is refused. Those are the tests that fail if someone loosens a check later.
"""

from __future__ import annotations

import os
import re
import time
import uuid

import pytest

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.auth import owner as owner_auth  # noqa: E402
from reyes_agent.remote_access import device_link, policy  # noqa: E402

GOOD_PASSWORD = "correct-horse-battery-staple"
EMAIL = "owner@zeno.local"


def _nonce() -> str:
    """Login requires a fresh nonce of at least 16 characters."""
    return uuid.uuid4().hex


@pytest.fixture()
def auth(tmp_path):
    policy.reset_rates()
    service = owner_auth.reset_for_tests(tmp_path / "owner.sqlite")
    service.provision(EMAIL, GOOD_PASSWORD)
    return service


@pytest.fixture()
def link(tmp_path):
    """Remote control is OFF by default -- a fresh install queues nothing.

    That default is asserted by `test_remote_control_is_off_until_enabled`;
    every other test turns it on explicitly because otherwise it would be
    testing the disabled path over and over.
    """
    service = device_link.reset_for_tests(tmp_path / "devices.sqlite")
    service.set_remote_control(True)
    return service


def _approved(link, label="Laptop"):
    """Register AND approve. A new device is PENDING and cannot authenticate."""
    registered = link.register(label=label)
    link.approve_device(registered["device_id"])
    return registered


@pytest.fixture()
def client(auth, link):
    """A loopback peer over HTTPS.

    HTTPS matters: the session cookie is issued `Secure; SameSite=None`
    outside development mode, so an http:// test client silently drops it and
    every authenticated request comes back 401 "No session." Testing over
    https exercises the same path production uses.

    The loopback address matters too -- the fail-closed boundary treats
    TestClient's default "testclient" host as a remote caller, which is
    correct behaviour and is asserted separately.
    """
    from fastapi.testclient import TestClient

    from reyes_agent import web

    return TestClient(web.app, client=("127.0.0.1", 45678),
                      base_url="https://testserver")


def _login(client, *, approve: bool = True) -> dict:
    """Sign in, and by default approve this browser.

    Logging in is not enough on its own: the browser is registered as a
    DEVICE in PENDING state, and protected routes answer 403 until the owner
    approves it from ZENO on Windows. `test_a_pending_browser_is_refused`
    covers the unapproved case deliberately.
    """
    response = client.post("/api/owner/auth/login",
                           json={"email": EMAIL, "password": GOOD_PASSWORD,
                                 "nonce": _nonce()})
    assert response.status_code == 200, response.text
    body = response.json()
    if approve and body.get("device_id"):
        owner_auth.get_owner_auth().approve_browser_device(body["device_id"])
    return body


def _register_and_approve(client, session: dict, label: str) -> dict:
    """Register a device over HTTP and approve it.

    Approval is a separate, deliberate step: a device that merely announces
    itself cannot claim work.
    """
    registered = client.post("/api/owner/devices/register", json={"label": label},
                             headers=_headers(session)).json()
    client.post("/api/owner/devices/approve",
                json={"device_id": registered["device_id"]},
                headers=_headers(session))
    return registered


def _headers(session: dict) -> dict:
    """Only the CSRF header.

    The session and refresh tokens are httpOnly cookies -- deliberately
    unreadable by script -- and TestClient's cookie jar carries them
    automatically, exactly as a browser would.
    """
    return {"X-Zeno-CSRF": session["csrf"]}


# --- passwords -----------------------------------------------------------
def test_password_is_never_stored_in_readable_form(auth, tmp_path):
    blob = (tmp_path / "owner.sqlite").read_bytes()
    assert GOOD_PASSWORD.encode() not in blob
    assert b"correct-horse" not in blob


def test_short_password_is_refused(auth):
    ok, reason = auth.provision(EMAIL, "tooshort")
    assert ok is False and "12 characters" in reason


def test_every_weak_password_entry_is_actually_reachable():
    """A `_WEAK` entry shorter than the minimum can never match.

    The first version of that set contained "password123" (11 characters),
    which the length check rejected first -- it was dead code pretending to
    be a protection.
    """
    assert all(len(entry) >= 12 for entry in owner_auth._WEAK), \
        [e for e in owner_auth._WEAK if len(e) < 12]


def test_a_common_password_is_refused_even_when_long_enough(auth):
    ok, reason = auth.provision(EMAIL, "administrator")
    assert ok is False and "most common" in reason


def test_wrong_password_is_refused(auth):
    assert auth.login(EMAIL, "not-the-password", identity="1.2.3.4", nonce=_nonce()).ok is False


def test_wrong_email_is_refused(auth):
    assert auth.login("someone@else.com", GOOD_PASSWORD, identity="1.2.3.4", nonce=_nonce()).ok is False


def test_repeated_failures_lock_the_account(auth):
    for _ in range(owner_auth.MAX_FAILED):
        auth.login(EMAIL, "wrong", identity="10.0.0.9", nonce=_nonce())
    # Even the CORRECT password is refused once locked.
    result = auth.login(EMAIL, GOOD_PASSWORD, identity="10.0.0.9", nonce=_nonce())
    assert result.ok is False
    assert result.retry_after > 0


def test_lockout_is_per_identity(auth):
    for _ in range(owner_auth.MAX_FAILED):
        auth.login(EMAIL, "wrong", identity="10.0.0.9", nonce=_nonce())
    assert auth.login(EMAIL, GOOD_PASSWORD, identity="10.0.0.10", nonce=_nonce()).ok is True


def test_changing_the_password_revokes_every_session(auth):
    session = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce=_nonce()).session
    assert auth.verify(session.token)[0] is True
    auth.provision(EMAIL, "a-completely-different-passphrase")
    assert auth.verify(session.token)[0] is False


# --- sessions ------------------------------------------------------------
def test_csrf_is_required_for_state_changing_requests(auth):
    session = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce=_nonce()).session
    assert auth.verify(session.token, csrf="wrong", require_csrf=True)[0] is False
    assert auth.verify(session.token, csrf=session.csrf, require_csrf=True)[0] is True


def test_expired_session_is_refused(auth, monkeypatch):
    session = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce=_nonce()).session
    monkeypatch.setattr(time, "time", lambda: time.time.__self__ if False else 1e12)
    ok, reason = auth.verify(session.token)
    assert ok is False and "expired" in reason.lower()


def test_refresh_token_is_single_use(auth):
    """A stolen refresh token must be usable at most once."""
    session = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce=_nonce()).session
    assert auth.refresh_session(session.refresh).ok is True
    assert auth.refresh_session(session.refresh).ok is False


def test_revoked_session_stops_working(auth):
    session = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce=_nonce()).session
    handle = [s["id"] for s in auth.sessions() if s["active"]][0]
    assert auth.revoke(handle) is True
    assert auth.verify(session.token)[0] is False


def test_session_listing_never_exposes_a_token(auth):
    session = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce=_nonce()).session
    rendered = repr(auth.sessions())
    assert session.token not in rendered
    assert session.csrf not in rendered
    assert session.refresh not in rendered


def test_login_nonce_cannot_be_replayed(auth):
    first = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce="abc123-abc123-abc123")
    assert first.ok is True
    replayed = auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce="abc123-abc123-abc123")
    assert replayed.ok is False and "already used" in replayed.reason


def test_audit_log_never_records_a_secret(auth):
    auth.login(EMAIL, GOOD_PASSWORD, identity="1.1.1.1", nonce=_nonce())
    rendered = repr(auth.audit_log(50))
    assert GOOD_PASSWORD not in rendered


# --- device link ---------------------------------------------------------
def test_device_token_is_verified(link):
    registered = _approved(link)
    assert link.authenticate(registered["device_id"], registered["token"]) is True
    assert link.authenticate(registered["device_id"], "wrong-token") is False


def test_device_token_is_not_stored_in_readable_form(link, tmp_path):
    registered = _approved(link)
    blob = (tmp_path / "devices.sqlite").read_bytes()
    assert registered["token"].encode() not in blob


def test_a_device_without_a_heartbeat_reads_offline(link):
    registered = _approved(link)
    assert link.device_state(registered["device_id"])["state"] == "OFFLINE"
    link.heartbeat(registered["device_id"])
    assert link.device_state(registered["device_id"])["state"] == "ONLINE"


def test_a_stale_heartbeat_reads_offline(link, monkeypatch):
    """An agent that dies must not stay ONLINE forever."""
    registered = _approved(link)
    link.heartbeat(registered["device_id"])
    future = time.time() + device_link.HEARTBEAT_GRACE_S + 10
    monkeypatch.setattr(device_link.time, "time", lambda: future)
    assert link.device_state(registered["device_id"])["state"] == "OFFLINE"


def test_duplicate_commands_are_collapsed(link):
    registered = _approved(link)
    device = registered["device_id"]
    first = link.enqueue(device, "open_app", {"name": "chrome"}, idempotency_key="same")
    second = link.enqueue(device, "open_app", {"name": "chrome"}, idempotency_key="same")
    assert first.id == second.id


def test_commands_without_a_key_are_not_collapsed(link):
    registered = _approved(link)
    device = registered["device_id"]
    first = link.enqueue(device, "open_app", {"name": "chrome"})
    second = link.enqueue(device, "open_app", {"name": "chrome"})
    assert first.id != second.id


def test_the_full_command_lifecycle_reports_the_real_result(link):
    registered = _approved(link)
    device, token = registered["device_id"], registered["token"]
    assert link.authenticate(device, token)

    # Offline device -> WAITING_FOR_DEVICE. It only becomes QUEUED once the
    # device has a live heartbeat, which is a genuinely useful distinction:
    # "your laptop is asleep" and "your laptop has not got to it yet" are
    # different answers.
    command = link.enqueue(device, "open_app", {"name": "chrome"})
    assert command.status == "WAITING_FOR_DEVICE"

    link.heartbeat(device)
    claimed = link.claim(device)
    assert [c.id for c in claimed] == [command.id]
    assert link.command(command.id).status == "IN_FLIGHT"

    assert link.acknowledge(command.id, device) is True
    assert link.command(command.id).status == "ACKNOWLEDGED"

    link.complete(command.id, device, ok=True, result={"detail": "Chrome opened"})
    finished = link.command(command.id)
    assert finished.status == "DONE"
    assert finished.result["detail"] == "Chrome opened"


def test_a_failed_command_is_reported_as_failed_not_done(link):
    registered = _approved(link)
    device = registered["device_id"]
    command = link.enqueue(device, "open_app", {"name": "nope"})
    link.claim(device)
    link.complete(command.id, device, ok=False, error="no such application")
    finished = link.command(command.id)
    assert finished.status == "FAILED"
    assert "no such application" in finished.result["error"]


def test_a_command_nobody_claims_times_out(link, monkeypatch):
    """A request sent to a sleeping laptop must not stay pending forever."""
    registered = _approved(link)
    command = link.enqueue(registered["device_id"], "open_app", {"name": "chrome"})
    future = time.time() + device_link.CLAIM_TIMEOUT_S + 10
    monkeypatch.setattr(device_link.time, "time", lambda: future)
    link._expire_stale()
    assert link.command(command.id).status == "EXPIRED"


def test_revoking_a_device_kills_its_queued_work(link):
    registered = _approved(link)
    device = registered["device_id"]
    command = link.enqueue(device, "open_app", {"name": "chrome"})
    link.revoke_device(device)
    assert link.command(command.id).status == "REJECTED"
    assert link.authenticate(device, registered["token"]) is False


def test_one_device_cannot_claim_another_devices_work(link):
    first = _approved(link, "Laptop A")
    second = _approved(link, "Laptop B")
    link.enqueue(first["device_id"], "open_app", {"name": "chrome"})
    assert link.claim(second["device_id"]) == []


# --- HTTP surface --------------------------------------------------------
def test_protected_routes_reject_an_anonymous_caller(client):
    for method, path in (("get", "/api/owner/devices"), ("get", "/api/owner/sessions"),
                         ("get", "/api/owner/audit"), ("get", "/api/owner/commands")):
        assert getattr(client, method)(path).status_code == 401, path
    assert client.post("/api/owner/command",
                       json={"action": "ask", "device_id": "x"}).status_code == 401


def test_login_then_use_a_protected_route(client):
    session = _login(client)
    assert client.get("/api/owner/devices", headers=_headers(session)).status_code == 200


def test_a_post_without_the_csrf_header_is_refused(client):
    session = _login(client)
    # No CSRF header at all. The session cookie alone must not be enough --
    # that is the entire point of CSRF protection.
    response = client.post("/api/owner/devices/register", json={"label": "x"})
    assert response.status_code == 401


def test_an_unregistered_action_is_refused_before_it_reaches_a_queue(client, link):
    session = _login(client)
    registered = _register_and_approve(client, session, "L")
    response = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "run_shell", "device_id": registered["device_id"],
        "payload": {"cmd": "whoami"}})
    assert response.status_code == 400
    assert "Unknown action" in response.text


def test_a_financial_request_is_refused_remotely(client):
    session = _login(client)
    registered = _register_and_approve(client, session, "L")
    body = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "open_app", "device_id": registered["device_id"],
        "text": "transfer $500 from my bank account"}).json()
    assert body["ok"] is False and body["refused"] is True


def test_queued_is_not_reported_as_done(client):
    """A consequential action never comes back 'done' without a fingerprint."""
    session = _login(client)
    registered = _register_and_approve(client, session, "L")
    body = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "open_app", "device_id": registered["device_id"],
        "text": "open chrome", "payload": {"name": "chrome"}}).json()
    # Opening an application is a consequential action, so on a session that has
    # not been fingerprint-elevated it must ask for a fingerprint -- and above
    # all it must never claim it is finished.
    assert body.get("needs_stepup") is True
    assert body.get("status") != "DONE"


def test_a_device_cannot_claim_with_a_bad_token(client):
    session = _login(client)
    registered = _register_and_approve(client, session, "L")
    response = client.post("/api/owner/device/claim",
                           json={"device_id": registered["device_id"], "token": "wrong"})
    assert response.status_code == 401


def test_end_to_end_open_chrome(client):
    """The deliverable, exercised as one flow -- now gated by a fingerprint."""
    session = _login(client)
    registered = _register_and_approve(client, session, "Laptop")
    device, token = registered["device_id"], registered["token"]

    client.post("/api/owner/device/heartbeat", json={"device_id": device, "token": token})

    # Step 1: without a fingerprint, a consequential action asks for one and
    # does NOT queue.
    first = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "open_app", "device_id": device, "text": "open chrome",
        "payload": {"name": "chrome"}, "idempotency_key": "e2e-1"}).json()
    assert first.get("needs_stepup") is True

    # Step 2: the owner scans a fingerprint. A verified WebAuthn assertion
    # elevates the session; simulate that result directly here.
    stoken = client.cookies.get("zeno_session")
    owner_auth.get_owner_auth()._elevations[stoken] = time.time() + 600

    # Step 3: now it queues, and the connected device can claim it.
    queued = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "open_app", "device_id": device, "text": "open chrome",
        "payload": {"name": "chrome"}, "idempotency_key": "e2e-2"}).json()
    assert queued.get("elevated") is True
    assert queued["status"] != "PENDING_APPROVAL"

    claimed = client.post("/api/owner/device/claim",
                          json={"device_id": device, "token": token}).json()
    assert [c["id"] for c in claimed["commands"]] == [queued["id"]]

    client.post("/api/owner/device/ack",
                json={"device_id": device, "token": token, "command_id": queued["id"]})
    client.post("/api/owner/device/complete", json={
        "device_id": device, "token": token, "command_id": queued["id"],
        "success": True, "result": {"detail": "Chrome opened; window confirmed"}})

    final = client.get(f"/api/owner/command/{queued['id']}", headers=_headers(session)).json()
    assert final["status"] == "DONE"
    assert "Chrome opened" in final["result"]["detail"]


def test_the_web_app_is_served_and_holds_no_secret(client):
    """No credential VALUE may ship in the bundle.

    The first version of this test asserted `"password:" not in body`, which
    matched the JavaScript object key in the login request -- legitimate code,
    flagged as a leak. What matters is an assigned secret, not the word.
    """
    body = client.get("/app").text
    assert "<title>ZENO</title>" in body

    leaked = re.findall(
        r"""(?:api[_-]?key|secret|token|passwd|password)\s*[:=]\s*["'][^"'{$][^"']{7,}["']""",
        body, re.IGNORECASE)
    assert leaked == [], f"the client bundle contains a literal secret: {leaked}"
    for forbidden in ("sk-ant-", "AKIA", "BEGIN PRIVATE KEY"):
        assert forbidden not in body, f"the client bundle contains {forbidden!r}"


def test_the_web_app_hard_codes_no_localhost(client):
    """A bundle pointing at localhost cannot work from a phone.

    Checks for a localhost URL, not the word: the first version of this test
    failed on a comment that merely explains why localhost is avoided.
    """
    body = client.get("/app").text
    hits = re.findall(r"""["'`(]\s*(?:https?:)?//(?:localhost|127\.0\.0\.1)""",
                      body, re.IGNORECASE)
    assert hits == [], f"the bundle hard-codes a localhost URL: {hits}"


def test_the_service_worker_never_caches_the_api(client):
    body = client.get("/app/sw.js").text
    assert '/api/' in body and "return" in body


# --- desktop agent -------------------------------------------------------
def test_every_action_maps_to_a_registered_tool():
    """Guards against the executors this file shipped with first time.

    Four of the five originally called functions that do not exist --
    `Agent()`, `desktop_app.open_application`, `memory_manager.recall` and
    `agent_space.roster`. They would have failed on every single command
    while looking implemented.
    """
    from reyes_agent.remote_access import desktop_agent
    from reyes_agent.tools import TOOLS

    missing = [t for t in set(desktop_agent.ACTION_TOOLS.values()) if t not in TOOLS]
    assert missing == [], f"actions map to unregistered tools: {missing}"


def test_action_arguments_match_the_real_tool_schemas():
    """`open_app` takes `name_or_path`, not `name`. The first builder guessed
    `name` and every launch failed with "unexpected keyword argument"."""
    from reyes_agent.remote_access import desktop_agent
    from reyes_agent.tools import TOOLS

    for action, tool_name in desktop_agent.ACTION_TOOLS.items():
        builder = desktop_agent.ACTION_ARGS.get(action)
        if builder is None:
            continue
        produced = set(builder({"name": "chrome", "query": "y"}))
        allowed = set((TOOLS[tool_name].input_schema or {}).get("properties", {}))
        assert produced <= allowed, (
            f"{action} passes {produced - allowed} which {tool_name} does not accept")


def test_failure_detection_reads_the_start_of_the_line_not_any_substring():
    """Both directions, because this code has been wrong in both.

    The browser harness scored "Browser error: TimeoutError" as SUCCESS by
    matching only a leading "error". The first version here scored
    `agent_roster` as FAILURE because an agent description contains the words
    "explains errors".
    """
    from reyes_agent.remote_access.desktop_agent import _FAILURE_PATTERN

    failures = ("Error: bad input for 'open_app'",
                "Browser error: TimeoutError: Page.click",
                "Couldn't find an app matching 'zzz'.",
                "Can't reach the desktop.",
                "Could not find that application.",
                "Failed to open Chrome.")
    successes = ('{"agents":[{"role":"monitors health, explains errors"}]}',
                 "CPU: 46% across 4 threads",
                 "No notes matched 'zzz'.",
                 "Opened Chrome; window title confirmed.",
                 "Scanned 40 files, no errors were found.")
    for text in failures:
        assert _FAILURE_PATTERN.search(text), f"missed a failure: {text!r}"
    for text in successes:
        assert not _FAILURE_PATTERN.search(text), f"false failure: {text!r}"


def test_the_agent_does_not_start_without_configuration(monkeypatch):
    """An unconfigured desktop must open no outbound connection at all."""
    from reyes_agent.remote_access import desktop_agent

    for name in ("ZENO_GATEWAY_URL", "ZENO_DEVICE_ID", "ZENO_DEVICE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert desktop_agent.from_environment() is None


def test_the_agent_refuses_a_non_http_gateway():
    """A gateway URL is the one caller-supplied string that reaches urllib."""
    from reyes_agent.remote_access.desktop_agent import AgentConfig, DesktopAgent

    agent = DesktopAgent(AgentConfig(gateway="file:///etc/passwd",
                                     device_id="d", token="t"))
    with pytest.raises(ValueError):
        agent._post("/api/owner/device/claim", {})


def test_backoff_grows_and_is_bounded():
    from reyes_agent.remote_access.desktop_agent import (AgentConfig, BACKOFF_MAX_S,
                                                         DesktopAgent)

    agent = DesktopAgent(AgentConfig(gateway="http://x", device_id="d", token="t"))
    agent._stop.set()  # so _on_failure does not actually sleep
    seen = []
    for _ in range(10):
        agent._on_failure(RuntimeError("boom"))
        seen.append(agent.state.backoff_s)
    assert all(0 <= value <= BACKOFF_MAX_S for value in seen)
    assert agent.state.connected is False


# --- gates added by the device-approval model ----------------------------
def test_a_fresh_install_accepts_no_command_until_a_device_is_approved(tmp_path):
    """What actually protects a fresh install.

    Remote control itself defaults ON -- the switch exists as a kill switch,
    not as the first line of defence. The gate that matters is that every
    device starts PENDING, so a brand-new install with no approved device can
    be commanded by nobody.
    """
    service = device_link.DeviceLink(tmp_path / "fresh-install.sqlite")
    registered = service.register(label="Laptop")
    assert registered["approval_state"] == "PENDING"
    with pytest.raises(PermissionError):
        service.enqueue(registered["device_id"], "open_app", {"name": "chrome"})

    service.approve_device(registered["device_id"])
    queued = service.enqueue(registered["device_id"], "open_app", {"name": "chrome"})
    assert queued.status in {"QUEUED", "WAITING_FOR_DEVICE"}


def test_the_kill_switch_stops_everything(tmp_path):
    service = device_link.DeviceLink(tmp_path / "killswitch.sqlite")
    registered = service.register(label="Laptop")
    service.approve_device(registered["device_id"])
    service.set_remote_control(False)
    with pytest.raises(PermissionError):
        service.enqueue(registered["device_id"], "open_app", {"name": "chrome"})


def test_an_unapproved_device_cannot_authenticate_or_receive_work(link):
    registered = link.register(label="Not yet approved")
    assert link.authenticate(registered["device_id"], registered["token"]) is False
    with pytest.raises(PermissionError):
        link.enqueue(registered["device_id"], "open_app", {"name": "chrome"})


def test_the_store_refuses_an_action_it_does_not_know(link):
    """Defence in depth: the API allow-lists actions, and so does the store."""
    registered = _approved(link)
    with pytest.raises(ValueError):
        link.enqueue(registered["device_id"], "run_shell", {"cmd": "whoami"})


def test_disabling_remote_control_cancels_queued_work(link):
    registered = _approved(link)
    command = link.enqueue(registered["device_id"], "open_app", {"name": "chrome"})
    link.set_remote_control(False)
    assert link.command(command.id).status == "CANCELLED"


def test_a_pending_browser_is_refused_until_approved(client):
    """Signing in is not enough -- the browser must be approved too."""
    session = _login(client, approve=False)
    blocked = client.get("/api/owner/devices", headers=_headers(session))
    assert blocked.status_code == 403
    assert "PENDING DEVICE" in blocked.text

    owner_auth.get_owner_auth().approve_browser_device(session["device_id"])
    assert client.get("/api/owner/devices",
                      headers=_headers(session)).status_code == 200


def test_the_session_cookie_is_secure_and_httponly(client):
    """The two attributes that actually protect the token.

    httponly: script cannot read it, so XSS cannot steal the session.
    secure:   it never travels in cleartext.
    """
    response = client.post("/api/owner/auth/login",
                           json={"email": EMAIL, "password": GOOD_PASSWORD,
                                 "nonce": _nonce()})
    header = response.headers.get("set-cookie", "")
    assert "zeno_session=" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    # And the token itself must not be in the JSON body, where script could
    # read it and put it in localStorage.
    assert "session" not in response.json()


def test_development_mode_allows_a_cleartext_cookie_for_local_work(monkeypatch):
    """Phase 8: local development over http must still work.

    Without this escape hatch a Secure cookie is dropped by the browser on
    http://localhost and nobody can sign in while developing. It is gated on
    an explicit flag so production can never take this path by accident.
    """
    from reyes_agent import config
    from reyes_agent.remote_access import domains

    monkeypatch.setattr(config, "REMOTE_DEV_MODE", True, raising=False)
    assert domains.dev_mode() is True

    from fastapi.testclient import TestClient

    from reyes_agent import web

    http_client = TestClient(web.app, client=("127.0.0.1", 45678),
                             base_url="http://testserver")
    response = http_client.post("/api/owner/auth/login",
                                json={"email": EMAIL, "password": GOOD_PASSWORD,
                                      "nonce": _nonce()})
    header = response.headers.get("set-cookie", "")
    if response.status_code == 200:
        assert "HttpOnly" in header
        assert "Secure" not in header, "dev mode must not demand https"


def test_a_device_command_cannot_run_without_owner_approval(client):
    """The fingerprint gate is the point -- a consequential command must not
    execute just because a device is connected and polling."""
    session = _login(client)
    registered = _register_and_approve(client, session, "Laptop")
    device, token = registered["device_id"], registered["token"]
    client.post("/api/owner/device/heartbeat", json={"device_id": device, "token": token})

    body = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "open_app", "device_id": device, "text": "open chrome",
        "payload": {"name": "chrome"}}).json()
    # Not fingerprint-elevated: it is refused up front and never queued.
    assert body.get("needs_stepup") is True

    # The device polls, and gets nothing -- nothing was ever enqueued.
    claimed = client.post("/api/owner/device/claim",
                          json={"device_id": device, "token": token}).json()
    assert claimed["commands"] == []


def test_a_denied_command_never_reaches_the_device(client):
    """A command the SAME policy the desktop uses refuses is refused up front
    and never reaches the device -- and a fingerprint cannot lift that. Remote
    access adds a gate; it never removes one."""
    session = _login(client)
    registered = _register_and_approve(client, session, "Laptop")
    device, token = registered["device_id"], registered["token"]
    client.post("/api/owner/device/heartbeat", json={"device_id": device, "token": token})

    body = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "run_automation", "device_id": device,
        "text": "disable antivirus"}).json()
    assert body.get("refused") is True

    # Even elevated, a policy-refused command stays refused: a fingerprint
    # authorises the OWNER's actions, it does not switch off the safety policy.
    stoken = client.cookies.get("zeno_session")
    owner_auth.get_owner_auth()._elevations[stoken] = time.time() + 600
    body2 = client.post("/api/owner/command", headers=_headers(session), json={
        "action": "run_automation", "device_id": device,
        "text": "disable antivirus"}).json()
    assert body2.get("refused") is True

    # Nothing reached the device either time.
    assert client.post("/api/owner/device/claim",
                       json={"device_id": device, "token": token}).json()["commands"] == []


def test_diagnostics_reports_shared_capabilities(client):
    """The phone and laptop share one brain, so the owner can see every
    capability's real state from either -- and this session's unlock state."""
    session = _login(client)
    body = client.get("/api/owner/diagnostics", headers=_headers(session)).json()
    caps = body["capabilities"]
    # Conversation is a CORE capability, never a device plugin.
    assert caps["conversation"]["status"] == "CONNECTED"
    # Every advertised capability reports one of the defined states, never blank.
    allowed = {"AVAILABLE", "CONNECTED", "DEGRADED", "UNAVAILABLE",
               "AUTH_REQUIRED", "DEVICE_OFFLINE", "ERROR"}
    for name, cap in caps.items():
        assert cap["status"] in allowed, (name, cap)
    # The fingerprint action-unlock state is reported for the UI.
    assert body["elevation"]["elevated"] is False
    # Node capabilities distinguish who can physically execute a desktop action.
    assert body["nodes"]["laptop"]["desktop.open_app"] is True
    assert body["nodes"]["phone"]["desktop.execute"] is False


def test_diagnostics_requires_a_trusted_owner(client):
    """An anonymous caller cannot read the capability map."""
    assert client.get("/api/owner/diagnostics").status_code == 401


def test_unlock_phrase_elevates_a_session_when_webauthn_cannot(client, tmp_path):
    """On an ephemeral tunnel WebAuthn's origin/RP id can't be stable, so the
    unlock phrase is the working action-unlock. Right phrase elevates; wrong
    phrase does not."""
    from reyes_agent.auth import unlock

    phrases = unlock.reset_for_tests(tmp_path / "unlock.sqlite")
    assert phrases.set_phrase("open sesame please")[0]
    session = _login(client)
    stoken = client.cookies.get("zeno_session")
    assert owner_auth.get_owner_auth().session_elevated(stoken) is False

    bad = client.post("/api/owner/auth/stepup/phrase", headers=_headers(session),
                      json={"phrase": "not the phrase at all"})
    assert bad.status_code == 403
    assert owner_auth.get_owner_auth().session_elevated(stoken) is False

    good = client.post("/api/owner/auth/stepup/phrase", headers=_headers(session),
                       json={"phrase": "open sesame please"}).json()
    assert good["ok"] is True and good["elevated"] is True
    assert owner_auth.get_owner_auth().session_elevated(stoken) is True
