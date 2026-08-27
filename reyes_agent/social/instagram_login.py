"""Instagram authentication + token lifecycle, via the CURRENT Meta API.

This is "Instagram API with Instagram Login" (NOT the retired Basic Display,
and NOT the Facebook-Login-with-a-linked-Page flow). It logs the ZENO
professional account in directly and returns an Instagram User access token.

Verified against Meta's documentation (Aug 2026):

    authorize   GET  https://www.instagram.com/oauth/authorize   (Business Login)
                     ?client_id=&redirect_uri=&response_type=code&scope=&state=
    code->token POST https://api.instagram.com/oauth/access_token
                     client_id, client_secret, grant_type=authorization_code,
                     redirect_uri, code   -> {access_token, user_id, permissions}
    long-lived  GET  https://graph.instagram.com/access_token
                     ?grant_type=ig_exchange_token&client_secret=&access_token=
                     -> {access_token, token_type, expires_in}   (60 days)
    refresh     GET  https://graph.instagram.com/refresh_access_token
                     ?grant_type=ig_refresh_token&access_token=
    profile     GET  https://graph.instagram.com/<ver>/me
                     ?fields=user_id,username,account_type,...

WHAT IS AND IS NOT SECRET
-------------------------
The App Secret and the access token are secrets: read through the credential
store (security/secrets/manager.py), never from a committed file, and NEVER
written to a log. The App ID and redirect URI are configuration.

FAILURE IS A RETURN VALUE, NOT A CRASH
--------------------------------------
`handle_callback` never raises: an OAuth redirect that goes wrong must show
the owner a clear message, not take a web server (or ZENO) down with it. Every
internal helper raises a typed `InstagramLoginError` carrying a category, and
the orchestration turns that into a structured, masked result.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from reyes_agent import config
from reyes_agent.social import store as social_store

log = logging.getLogger("zeno.instagram")

# Token/id are stored under these keys in the credential store; the adapter
# reads the SAME keys, so authenticating here makes publishing work with no
# further wiring.
TOKEN_KEY = "INSTAGRAM_ACCESS_TOKEN"
ACCOUNT_ID_KEY = "INSTAGRAM_BUSINESS_ACCOUNT_ID"

# Error categories -- each maps to one of the failures the brief asks about.
MISSING_APP_ID = "missing_app_id"
MISSING_APP_SECRET = "missing_app_secret"
MISSING_REDIRECT_URI = "missing_redirect_uri"
INVALID_CODE = "invalid_code"
INVALID_TOKEN = "invalid_token"
MISSING_PERMISSION = "missing_permission"
NOT_PROFESSIONAL = "not_professional"
RATE_LIMITED = "rate_limited"
NETWORK = "network"
API_ERROR = "api_error"
OAUTH_DENIED = "oauth_denied"


class InstagramLoginError(RuntimeError):
    """A login/token failure with a machine-readable category. The message is
    safe to show a human; it never contains a token."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "category": self.category, "error": self.message}


# --------------------------------------------------------------------------
# secrets + masking
# --------------------------------------------------------------------------
def _secret(name: str) -> str:
    """Credential store first, environment second. Never logged either way."""
    try:
        from reyes_agent.security.secrets import manager
        value = manager.get(name, "")
        if value:
            return value
    except Exception:  # noqa: BLE001 -- a broken store must degrade, not crash
        pass
    return os.environ.get(name, "").strip()


def _store_secret(name: str, value: str) -> None:
    """Write to the OS credential store when available, else leave it to .env.
    Persisting a token is best-effort: a machine with no keyring still works
    for the current process (the value is also held in memory by callers)."""
    try:
        from reyes_agent.security.secrets import manager
        ok, _detail = manager.put(name, value)
        if not ok:
            # No keyring here. Fall back to the process environment so the
            # rest of THIS run can publish; the owner is told to persist it.
            os.environ[name] = value
    except Exception:  # noqa: BLE001
        os.environ[name] = value


def mask(token: str) -> str:
    """A token reduced to something safe to print: last 4 chars only."""
    token = str(token or "")
    if not token:
        return "(none)"
    if len(token) <= 4:
        return "****"
    return f"****{token[-4:]}"


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class _AppConfig:
    app_id: str
    app_secret: str
    redirect_uri: str
    scopes: str
    authorize_base: str   # www.instagram.com  -- the authorization window
    oauth_base: str       # api.instagram.com  -- the code->token exchange
    graph_base: str
    version: str


def _app_config(*, require_secret: bool = True) -> _AppConfig:
    """Gather config, raising a specific error for the FIRST missing piece so
    the owner fixes exactly one thing at a time."""
    app_id = (_secret("INSTAGRAM_APP_ID") or config.INSTAGRAM_APP_ID).strip()
    redirect_uri = (_secret("INSTAGRAM_REDIRECT_URI")
                    or config.INSTAGRAM_REDIRECT_URI).strip()
    app_secret = _secret("INSTAGRAM_APP_SECRET").strip()

    if not app_id:
        raise InstagramLoginError(
            MISSING_APP_ID, "INSTAGRAM_APP_ID is not set. Add your Instagram "
            "App ID (Meta App Dashboard) to .env or the credential store.")
    if not redirect_uri:
        raise InstagramLoginError(
            MISSING_REDIRECT_URI, "INSTAGRAM_REDIRECT_URI is not set. It must "
            "match the redirect URI registered in the Meta App Dashboard "
            "exactly (e.g. the Cloudflare tunnel + /auth/instagram/callback).")
    if require_secret and not app_secret:
        raise InstagramLoginError(
            MISSING_APP_SECRET, "INSTAGRAM_APP_SECRET is not set. Store it in "
            "the credential store (never commit it).")

    return _AppConfig(
        app_id=app_id, app_secret=app_secret, redirect_uri=redirect_uri,
        scopes=config.INSTAGRAM_SCOPES,
        authorize_base=config.INSTAGRAM_AUTHORIZE_BASE,
        oauth_base=config.INSTAGRAM_OAUTH_BASE,
        graph_base=config.INSTAGRAM_GRAPH_BASE,
        version=config.INSTAGRAM_API_VERSION)


def configured() -> bool:
    """Is there enough config to START the flow? Cheap; no network."""
    try:
        _app_config(require_secret=False)
        return True
    except InstagramLoginError:
        return False


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
_TIMEOUT_S = 30.0


def _raise_for_meta_error(status: int, body: dict[str, Any]) -> None:
    """Translate a Meta error body into a categorised InstagramLoginError.
    Handles both the OAuth shape ({error_type, code, error_message}) and the
    Graph shape ({error:{message,type,code,error_subcode}})."""
    graph = body.get("error") if isinstance(body.get("error"), dict) else {}
    message = (graph.get("message")
               or body.get("error_message")
               or body.get("error_description")
               or (body.get("error") if isinstance(body.get("error"), str) else "")
               or f"HTTP {status}")
    code = graph.get("code") or body.get("code")
    low = str(message).lower()

    if status == 429 or code in (4, 17, 32, 613) or "rate limit" in low:
        raise InstagramLoginError(RATE_LIMITED,
                                  f"Instagram rate limit reached: {message}")
    if "permission" in low or "scope" in low or code in (10, 200, 203):
        raise InstagramLoginError(MISSING_PERMISSION,
                                  f"Instagram permission missing: {message}")
    if "authorization code" in low or "expired" in low or "code" in low and status == 400:
        raise InstagramLoginError(INVALID_CODE,
                                  f"Authorization code rejected: {message}")
    if "access token" in low or "session" in low or code in (190,):
        raise InstagramLoginError(INVALID_TOKEN,
                                  f"Access token invalid: {message}")
    raise InstagramLoginError(API_ERROR, f"Instagram API error: {message}")


def _read_json(resp: Any) -> dict[str, Any]:
    try:
        return json.loads(resp.read().decode("utf-8") or "{}")
    except (ValueError, OSError):
        return {}


def _request(url: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """One HTTP call. `data` -> POST form; otherwise GET. Returns parsed JSON,
    raises a categorised InstagramLoginError on any failure."""
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, method="POST")
    else:
        req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return _read_json(resp)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            payload = {}
        _raise_for_meta_error(exc.code, payload)
        return {}  # unreachable; _raise_for_meta_error always raises
    except urllib.error.URLError as exc:
        raise InstagramLoginError(
            NETWORK, f"Could not reach Instagram ({exc.reason}). Check the "
            "network and try again.") from None
    except Exception as exc:  # noqa: BLE001
        raise InstagramLoginError(NETWORK, f"Instagram request failed: "
                                  f"{type(exc).__name__}") from None


# --------------------------------------------------------------------------
# OAuth steps
# --------------------------------------------------------------------------
def authorize_url(state: str = "") -> str:
    """The URL the owner opens to grant ZENO access to its own account.

    Business Login's authorization window is on www.instagram.com (NOT
    api.instagram.com, which is only the token-exchange host)."""
    cfg = _app_config(require_secret=False)
    params = {
        "client_id": cfg.app_id,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "scope": cfg.scopes,
    }
    if state:
        params["state"] = state
    return f"{cfg.authorize_base}/oauth/authorize?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    """Authorization code -> short-lived token. {access_token, user_id, ...}."""
    cfg = _app_config()
    if not str(code or "").strip():
        raise InstagramLoginError(INVALID_CODE, "No authorization code was "
                                  "provided to exchange.")
    result = _request(f"{cfg.oauth_base}/oauth/access_token", data={
        "client_id": cfg.app_id,
        "client_secret": cfg.app_secret,
        "grant_type": "authorization_code",
        "redirect_uri": cfg.redirect_uri,
        "code": str(code).strip(),
    })
    # Some API versions wrap the result in data:[{...}]; unwrap defensively.
    if not result.get("access_token") and isinstance(result.get("data"), list) and result["data"]:
        result = result["data"][0]
    if not result.get("access_token"):
        raise InstagramLoginError(INVALID_CODE,
                                  "Token exchange returned no access token.")
    return result


def long_lived_token(short_token: str) -> dict[str, Any]:
    """Short-lived (1h) -> long-lived (60d). {access_token, expires_in}."""
    cfg = _app_config()
    params = {
        "grant_type": "ig_exchange_token",
        "client_secret": cfg.app_secret,
        "access_token": short_token,
    }
    result = _request(f"{cfg.graph_base}/access_token?{urllib.parse.urlencode(params)}")
    if not result.get("access_token"):
        # Non-fatal: the short-lived token still works for an hour.
        raise InstagramLoginError(INVALID_TOKEN,
                                  "Long-lived token exchange returned nothing.")
    return result


def fetch_profile(token: str, ig_user_id: str = "me") -> dict[str, Any]:
    """Validate the token AND read the professional account identity."""
    cfg = _app_config(require_secret=False)
    node = str(ig_user_id or "me").strip() or "me"
    params = {
        "fields": "user_id,username,account_type,name,followers_count,media_count",
        "access_token": token,
    }
    data = _request(f"{cfg.graph_base}/{cfg.version}/{node}"
                    f"?{urllib.parse.urlencode(params)}")
    account_type = str(data.get("account_type") or "").upper()
    if account_type and account_type not in ("BUSINESS", "MEDIA_CREATOR",
                                             "CREATOR", "PROFESSIONAL"):
        raise InstagramLoginError(
            NOT_PROFESSIONAL, f"Connected account is '{account_type}', not a "
            "Professional (Business/Creator) account. Content publishing needs "
            "a Professional account.")
    return data


def refresh_long_lived_token() -> dict[str, Any]:
    """Refresh the stored 60-day token so a live account never lapses.
    Returns a masked status dict; never raises."""
    try:
        cfg = _app_config(require_secret=False)
        token = _secret(TOKEN_KEY)
        if not token:
            return {"ok": False, "error": "No stored token to refresh."}
        params = {"grant_type": "ig_refresh_token", "access_token": token}
        result = _request(f"{cfg.graph_base}/refresh_access_token"
                          f"?{urllib.parse.urlencode(params)}")
        new_token = result.get("access_token")
        if not new_token:
            return {"ok": False, "error": "Refresh returned no token."}
        expires_in = int(result.get("expires_in") or 0)
        _store_secret(TOKEN_KEY, new_token)
        _record_account(token_state="VALID",
                        token_expires=time.time() + expires_in if expires_in else None)
        log.info("Instagram token refreshed. Token status: valid (%s)", mask(new_token))
        return {"ok": True, "token": mask(new_token), "expires_in": expires_in}
    except InstagramLoginError as exc:
        return exc.as_dict()


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------
def _record_account(**fields: Any) -> None:
    try:
        social_store.get_store().upsert_account(social_store.INSTAGRAM, **fields)
    except Exception:  # noqa: BLE001 -- the DB must not break auth
        log.debug("Could not update the social account row", exc_info=False)


def store_credentials(token: str, ig_user_id: str, profile: dict[str, Any],
                      *, expires_in: int = 0, scopes: str = "") -> dict[str, Any]:
    """Persist the token (credential store) + identity (social DB). Returns a
    masked summary. The full token is never returned or logged."""
    _store_secret(TOKEN_KEY, token)
    _store_secret(ACCOUNT_ID_KEY, str(ig_user_id))
    username = str(profile.get("username") or "")
    account_type = str(profile.get("account_type") or "PROFESSIONAL").upper()
    _record_account(
        account_id=str(ig_user_id), username=username,
        display_name=str(profile.get("name") or ""),
        account_type=account_type, token_state="VALID",
        token_expires=(time.time() + expires_in) if expires_in else None,
        last_success=time.time(), last_error="", connected=1,
        scopes=[s for s in (scopes or config.INSTAGRAM_SCOPES).split(",") if s])
    log.info("Instagram connected: @%s  Token status: valid (%s)",
             username or "unknown", mask(token))
    return {
        "ok": True, "username": username, "account_id": str(ig_user_id),
        "account_type": account_type, "token": mask(token),
        "expires_in": expires_in,
    }


# --------------------------------------------------------------------------
# the callback orchestration -- never raises
# --------------------------------------------------------------------------
def handle_callback(*, code: str = "", error: str = "",
                    error_description: str = "", state: str = "") -> dict[str, Any]:
    """The whole redirect -> READY sequence, as a structured, masked result.

    code    -> short-lived token -> long-lived token -> profile (validation +
    identity + professional check) -> secure storage -> connected.

    Returns {"ok": True, "username": ...} on success, else a categorised
    error. It never raises: a bad redirect must not take the server down.
    """
    if error or error_description:
        detail = error_description or error or "authorization was denied"
        log.warning("Instagram authorization declined: %s", detail)
        return {"ok": False, "category": OAUTH_DENIED,
                "error": f"Instagram authorization was not granted: {detail}"}
    try:
        short = exchange_code(code)
        short_token = str(short.get("access_token"))
        ig_user_id = str(short.get("user_id") or "")
        granted = str(short.get("permissions") or "")

        # Upgrade to a 60-day token; if that step alone fails, keep going with
        # the short-lived one so a transient blip does not block the demo.
        token, expires_in = short_token, 3600
        try:
            longed = long_lived_token(short_token)
            token = str(longed.get("access_token") or short_token)
            expires_in = int(longed.get("expires_in") or 3600)
        except InstagramLoginError as exc:
            log.info("Long-lived exchange skipped (%s); using short-lived token",
                     exc.category)

        profile = fetch_profile(token, ig_user_id or "me")
        ig_user_id = ig_user_id or str(profile.get("user_id") or profile.get("id") or "")
        return store_credentials(token, ig_user_id, profile,
                                 expires_in=expires_in, scopes=granted)
    except InstagramLoginError as exc:
        _record_account(token_state="INVALID", last_error=exc.message[:200],
                        connected=0)
        log.warning("Instagram connection failed (%s): %s", exc.category, exc.message)
        return exc.as_dict()


# --------------------------------------------------------------------------
# status + disconnect (for the tools)
# --------------------------------------------------------------------------
def connection_status() -> dict[str, Any]:
    """Masked connection status. `line` is the spoken/printed one-liner."""
    account = social_store.get_store().account(social_store.INSTAGRAM)
    has_token = bool(_secret(TOKEN_KEY))
    if account and account.get("connected") and account.get("username"):
        username = account["username"]
        return {
            "ok": True, "connected": True, "username": username,
            "account_id": account.get("account_id", ""),
            "account_type": account.get("account_type", ""),
            "token_state": account.get("token_state", "VALID"),
            "token_expires": account.get("token_expires"),
            "has_token": has_token,
            "line": f"Instagram connected: @{username}",
        }
    return {
        "ok": True, "connected": False, "has_token": has_token,
        "configured": configured(),
        "line": ("Instagram not connected yet. "
                 + ("Ready to connect -- start the OAuth flow."
                    if configured() else
                    "Set INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET / "
                    "INSTAGRAM_REDIRECT_URI first.")),
    }


def disconnect() -> dict[str, Any]:
    """Forget the stored token/id and mark the account disconnected."""
    try:
        from reyes_agent.security.secrets import manager
        manager.forget(TOKEN_KEY)
        manager.forget(ACCOUNT_ID_KEY)
    except Exception:  # noqa: BLE001
        pass
    for key in (TOKEN_KEY, ACCOUNT_ID_KEY):
        os.environ.pop(key, None)
    _record_account(token_state="MISSING", connected=0, last_error="")
    return {"ok": True, "connected": False, "line": "Instagram disconnected."}
