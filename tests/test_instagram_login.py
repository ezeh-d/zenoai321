"""Instagram API with Instagram Login: OAuth, tokens, publishing, safety.

These tests never touch the network. Every HTTP call goes through one seam
(`instagram_login._request` for the auth module, `adapter._request` for the
adapter), which the tests replace with a router over canned responses. Secret
storage is redirected to an in-memory dict so nothing reaches the real keyring.
"""

from __future__ import annotations

import json

import pytest

from reyes_agent.social import instagram_login as il
from reyes_agent.social import store as social_store
from reyes_agent.social.adapters import reset_adapters_for_tests


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture()
def store(tmp_path):
    fresh = social_store.reset_store_for_tests(tmp_path / "social.db")
    reset_adapters_for_tests()
    yield fresh
    social_store.reset_store_for_tests(None)
    reset_adapters_for_tests()


@pytest.fixture()
def vault(monkeypatch):
    """App config + a stand-in for the credential store, all in memory."""
    data = {
        "INSTAGRAM_APP_ID": "APP123",
        "INSTAGRAM_APP_SECRET": "app-secret-xyz",
        "INSTAGRAM_REDIRECT_URI": "https://demo.trycloudflare.com/auth/instagram/callback",
    }
    monkeypatch.setattr(il, "_secret", lambda name: data.get(name, ""))
    monkeypatch.setattr(il, "_store_secret",
                        lambda name, value: data.__setitem__(name, value))
    return data


def _router(**responses):
    """Build a fake _request that routes by the distinctive part of each URL."""
    def fake(url, data=None):
        if data is not None:                       # POST = code exchange
            return responses["code"]
        if "ig_exchange_token" in url:
            return responses["long"]
        if "ig_refresh_token" in url:
            return responses.get("refresh", {})
        return responses["profile"]               # GET on the user node
    return fake


_GOOD = dict(
    code={"access_token": "SHORT-tok", "user_id": "17841400000",
          "permissions": "instagram_business_basic,instagram_business_content_publish"},
    long={"access_token": "LONG-TOKEN-WXYZ", "token_type": "bearer",
          "expires_in": 5184000},
    profile={"user_id": "17841400000", "username": "meetzeno.ai",
             "account_type": "CREATOR", "name": "ZENO"},
)


# --------------------------------------------------------------------------
# authorization URL
# --------------------------------------------------------------------------
def test_authorize_url_uses_business_login_window_and_scopes(vault):
    # Business Login's authorization window is on www.instagram.com; only the
    # token exchange is on api.instagram.com.
    url = il.authorize_url(state="s123")
    assert url.startswith("https://www.instagram.com/oauth/authorize?")
    assert "client_id=APP123" in url
    assert "response_type=code" in url
    assert "instagram_business_basic" in url
    assert "instagram_business_content_publish" in url
    assert "state=s123" in url
    # The old Basic Display / Facebook-login markers must be gone.
    assert "graph.facebook.com" not in url
    assert "api.instagram.com" not in url


def test_token_exchange_still_uses_api_host(vault, monkeypatch):
    # The fix must NOT move the token exchange off api.instagram.com.
    seen = {}

    def capture(url, data=None):
        seen["url"] = url
        return _GOOD["code"]
    monkeypatch.setattr(il, "_request", capture)
    il.exchange_code("AUTH-CODE")
    assert seen["url"].startswith("https://api.instagram.com/oauth/access_token")


def test_authorize_url_errors_clearly_when_app_id_missing(monkeypatch):
    monkeypatch.setattr(il, "_secret", lambda name: "")
    monkeypatch.setattr(il.config, "INSTAGRAM_APP_ID", "")
    with pytest.raises(il.InstagramLoginError) as exc:
        il.authorize_url()
    assert exc.value.category == il.MISSING_APP_ID


# --------------------------------------------------------------------------
# token exchange
# --------------------------------------------------------------------------
def test_exchange_code_returns_short_token(vault, monkeypatch):
    monkeypatch.setattr(il, "_request", _router(**_GOOD))
    result = il.exchange_code("AUTH-CODE")
    assert result["access_token"] == "SHORT-tok"
    assert result["user_id"] == "17841400000"


def test_exchange_code_missing_code_is_invalid_code(vault):
    with pytest.raises(il.InstagramLoginError) as exc:
        il.exchange_code("")
    assert exc.value.category == il.INVALID_CODE


def test_long_lived_token_exchange(vault, monkeypatch):
    monkeypatch.setattr(il, "_request", _router(**_GOOD))
    result = il.long_lived_token("SHORT-tok")
    assert result["access_token"] == "LONG-TOKEN-WXYZ"
    assert result["expires_in"] == 5184000


# --------------------------------------------------------------------------
# profile lookup + professional check
# --------------------------------------------------------------------------
def test_profile_lookup_returns_identity(vault, monkeypatch):
    monkeypatch.setattr(il, "_request", _router(**_GOOD))
    data = il.fetch_profile("LONG-TOKEN-WXYZ", "17841400000")
    assert data["username"] == "meetzeno.ai"
    assert data["account_type"] == "CREATOR"


def test_profile_rejects_a_personal_account(vault, monkeypatch):
    bad = dict(_GOOD, profile={"user_id": "1", "username": "someone",
                               "account_type": "PERSONAL"})
    monkeypatch.setattr(il, "_request", _router(**bad))
    with pytest.raises(il.InstagramLoginError) as exc:
        il.fetch_profile("tok", "1")
    assert exc.value.category == il.NOT_PROFESSIONAL


# --------------------------------------------------------------------------
# the callback orchestration
# --------------------------------------------------------------------------
def test_callback_success_connects_and_persists(vault, store, monkeypatch):
    monkeypatch.setattr(il, "_request", _router(**_GOOD))
    result = il.handle_callback(code="AUTH-CODE")
    assert result["ok"] is True
    assert result["username"] == "meetzeno.ai"
    # token persisted to the (in-memory) credential store, long-lived one won.
    assert vault["INSTAGRAM_ACCESS_TOKEN"] == "LONG-TOKEN-WXYZ"
    assert vault["INSTAGRAM_BUSINESS_ACCOUNT_ID"] == "17841400000"
    # connection status reflects it.
    status = il.connection_status()
    assert status["connected"] is True
    assert status["line"] == "Instagram connected: @meetzeno.ai"
    # and the social account row was written.
    account = store.account(social_store.INSTAGRAM)
    assert account["connected"] is True and account["username"] == "meetzeno.ai"


def test_callback_missing_code_reports_invalid_code(vault, store):
    result = il.handle_callback(code="")
    assert result["ok"] is False
    assert result["category"] == il.INVALID_CODE


def test_callback_oauth_error_is_reported_not_raised(vault, store):
    result = il.handle_callback(error="access_denied",
                                error_description="The user denied your request")
    assert result["ok"] is False
    assert result["category"] == il.OAUTH_DENIED
    assert "denied" in result["error"].lower()


def test_callback_permission_error_surfaces(vault, store, monkeypatch):
    def fake(url, data=None):
        if data is not None:
            return _GOOD["code"]
        if "ig_exchange_token" in url:
            return _GOOD["long"]
        raise il.InstagramLoginError(il.MISSING_PERMISSION,
                                     "instagram_business_content_publish missing")
    monkeypatch.setattr(il, "_request", fake)
    result = il.handle_callback(code="AUTH-CODE")
    assert result["ok"] is False
    assert result["category"] == il.MISSING_PERMISSION


def test_callback_api_failure_does_not_crash(vault, store, monkeypatch):
    def boom(url, data=None):
        raise il.InstagramLoginError(il.API_ERROR, "Instagram API error: down")
    monkeypatch.setattr(il, "_request", boom)
    result = il.handle_callback(code="AUTH-CODE")
    assert result["ok"] is False
    assert result["category"] == il.API_ERROR


# --------------------------------------------------------------------------
# token never leaks
# --------------------------------------------------------------------------
def test_mask_only_shows_last_four():
    assert il.mask("LONG-TOKEN-WXYZ") == "****WXYZ"
    assert il.mask("") == "(none)"
    assert il.mask("ab") == "****"


def test_full_token_never_appears_in_a_callback_result(vault, store, monkeypatch):
    monkeypatch.setattr(il, "_request", _router(**_GOOD))
    result = il.handle_callback(code="AUTH-CODE")
    blob = json.dumps(result)
    assert "LONG-TOKEN-WXYZ" not in blob
    assert "SHORT-tok" not in blob
    assert result["token"] == "****WXYZ"


# --------------------------------------------------------------------------
# not-configured: ZENO keeps running
# --------------------------------------------------------------------------
def test_not_configured_is_safe(monkeypatch, store):
    monkeypatch.setattr(il, "_secret", lambda name: "")
    monkeypatch.setattr(il.config, "INSTAGRAM_APP_ID", "")
    monkeypatch.setattr(il.config, "INSTAGRAM_REDIRECT_URI", "")
    assert il.configured() is False
    status = il.connection_status()
    assert status["connected"] is False
    # A stray callback with no config must return an error, not raise.
    result = il.handle_callback(code="whatever")
    assert result["ok"] is False


# --------------------------------------------------------------------------
# publishing through the governed adapter (container -> publish -> verify)
# --------------------------------------------------------------------------
@pytest.fixture()
def live_adapter(store, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TESTTOKEN")
    monkeypatch.setenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "17841400000")
    monkeypatch.setenv("ZENO_SOCIAL_INSTAGRAM_ENABLED", "true")
    monkeypatch.setenv("SOCIAL_DRY_RUN", "false")
    monkeypatch.setenv("SOCIAL_AUTOMATION_KILL_SWITCH", "false")
    from reyes_agent.social.adapters.instagram import InstagramAPIAdapter
    return InstagramAPIAdapter()


def test_image_container_created_then_published_and_verified(live_adapter, monkeypatch):
    calls = []

    def fake(path, params=None, method="GET"):
        calls.append((path, method))
        if path.endswith("/media") and method == "POST":
            assert params.get("image_url", "").startswith("https://")
            return {"id": "CONTAINER-1"}
        if path.endswith("/media_publish") and method == "POST":
            assert params.get("creation_id") == "CONTAINER-1"
            return {"id": "POST-99"}
        return {"id": "POST-99", "permalink": "https://instagram.com/p/POST-99",
                "username": "meetzeno.ai", "account_type": "CREATOR"}

    monkeypatch.setattr(live_adapter, "_request", fake)
    result = live_adapter.publish({"media_url": "https://cdn.example/x.jpg",
                                   "media_type": "image", "caption": "test"})
    assert result.ok and result.verified
    assert result.post_id == "POST-99"
    # the two-step really happened
    assert ("17841400000/media", "POST") in calls
    assert ("17841400000/media_publish", "POST") in calls


def test_local_path_is_refused_before_the_container_call(live_adapter, monkeypatch):
    # _do_publish must reject a local path BEFORE it tries to create a media
    # container -- Meta fetches media from a URL, so a local path can never work
    # and saying so early beats a confusing 400. (publish() runs the auth guard
    # first, which is a separate network call; this asserts the media check.)
    def fake(*a, **k):
        raise AssertionError("no container call should happen for a local path")
    monkeypatch.setattr(live_adapter, "_request", fake)
    result = live_adapter._do_publish({"media_path": r"C:\Users\me\pic.jpg",
                                       "media_type": "image"})
    assert result.ok is False
    assert "local file" in result.error or "media_url" in result.error


def test_failed_api_request_is_reported_not_raised(live_adapter, monkeypatch):
    def fake(path, params=None, method="GET"):
        if path.endswith("/media") and method == "POST":
            raise RuntimeError("Instagram API: Application does not have permission")
        return {"id": "17841400000", "username": "meetzeno.ai",
                "account_type": "CREATOR"}
    monkeypatch.setattr(live_adapter, "_request", fake)
    result = live_adapter.publish({"media_url": "https://cdn.example/x.jpg",
                                   "media_type": "image"})
    assert result.ok is False
    assert "permission" in result.error.lower()


def test_dry_run_prepares_but_never_calls_the_network(store, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TESTTOKEN")
    monkeypatch.setenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "17841400000")
    monkeypatch.setenv("ZENO_SOCIAL_INSTAGRAM_ENABLED", "true")
    monkeypatch.setenv("SOCIAL_DRY_RUN", "true")
    from reyes_agent.social.adapters.instagram import InstagramAPIAdapter
    adapter = InstagramAPIAdapter()

    def fake(*a, **k):
        raise AssertionError("dry run must not reach the network")
    monkeypatch.setattr(adapter, "_request", fake)
    result = adapter.publish({"media_url": "https://cdn.example/x.jpg",
                              "media_type": "image"})
    assert result.simulated is True and result.status == "SIMULATED"


# --------------------------------------------------------------------------
# tools registered; existing ones intact
# --------------------------------------------------------------------------
def test_new_tools_registered_without_regressing_existing():
    import reyes_agent.tools.social_tools  # noqa: F401 -- registers them
    from reyes_agent.tools import TOOLS

    assert "social_connect" in TOOLS
    assert "social_publish_media" in TOOLS
    # existing social tools still present
    for name in ("social_status", "social_publish", "social_setup",
                 "social_health", "social_control"):
        assert name in TOOLS


def test_publish_media_refuses_without_owner_approval():
    import reyes_agent.tools.social_tools  # noqa: F401
    from reyes_agent.tools import TOOLS
    out = TOOLS["social_publish_media"].func(
        platform="instagram", image_url="https://cdn.example/x.jpg",
        owner_approved=False)
    assert "owner_approved is false" in out.lower() or "refused" in out.lower()


def test_publish_media_refuses_a_local_path(store):
    import reyes_agent.tools.social_tools  # noqa: F401
    from reyes_agent.tools import TOOLS
    out = TOOLS["social_publish_media"].func(
        platform="instagram", image_url=r"C:\pic.jpg", owner_approved=True)
    assert "https" in out.lower()
