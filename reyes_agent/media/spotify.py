"""Spotify Web API client -- OAuth 2.0 with PKCE, no client secret.

This unlocks the operations GSMTC can't do: search a song by name and play it,
start a playlist, move playback to another device, read rich now-playing data.
It is OPTIONAL -- ZENO controls Spotify perfectly well through Windows media
sessions without it. This adds reach when the user connects their account.

SECURITY
--------
- PKCE flow: there is NO client secret to store or leak (that's the point of
  PKCE for a desktop app). Only the public client id is configured.
- Tokens (access + refresh) are cached OUTSIDE the repo, under
  %LOCALAPPDATA%\\ZENO\\spotify_token.json, and are never logged or printed.
- Nothing here is committed with real credentials; see .env.example.

CONFIG (all via environment / .env)
- SPOTIFY_CLIENT_ID     : the app's public client id (required to connect)
- SPOTIFY_REDIRECT_URI  : registered redirect, default http://127.0.0.1:8766/callback
- SPOTIFY_SCOPES        : optional override of the requested scopes

DEGRADES: with no client id, available() is False and every op returns a clear
"connect Spotify first" result -- callers fall back to the Windows path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from typing import Any

_AUTH_BASE = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API = "https://api.spotify.com/v1"
# The desktop web surface (web.py) binds 127.0.0.1:8765 and hosts the callback
# route, so linking is one click with no extra server. Register this EXACT URI
# in the Spotify app dashboard.
_DEFAULT_REDIRECT = "http://127.0.0.1:8765/api/media/spotify/callback"
_DEFAULT_SCOPES = ("user-read-playback-state user-modify-playback-state "
                   "user-read-currently-playing")


def _result(ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    out = {"ok": bool(ok), "detail": detail}
    out.update(extra)
    return out


def _token_path() -> str:
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
            or os.path.expanduser("~"))
    path = os.path.join(base, "ZENO")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass
    return os.path.join(path, "spotify_token.json")


class SpotifyClient:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._client_id = (os.environ.get("SPOTIFY_CLIENT_ID") or "").strip()
        self._redirect = (os.environ.get("SPOTIFY_REDIRECT_URI")
                          or _DEFAULT_REDIRECT).strip()
        self._scopes = (os.environ.get("SPOTIFY_SCOPES") or _DEFAULT_SCOPES).strip()
        self._tok: dict[str, Any] = {}
        self._pending: dict[str, str] = {}   # verifier/state during auth
        self._load_tokens()

    # -- config / status ---------------------------------------------------
    def available(self) -> bool:
        """We CAN connect (a client id is configured)."""
        return bool(self._client_id)

    def connected(self) -> bool:
        """We HAVE a usable (or refreshable) token."""
        with self._lock:
            return bool(self._tok.get("access_token") or self._tok.get("refresh_token"))

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available(),
            "connected": self.connected(),
            "redirect_uri": self._redirect,
            "scopes": self._scopes.split(),
            "token_cached": os.path.exists(_token_path()),
        }

    # -- token persistence -------------------------------------------------
    def _load_tokens(self) -> None:
        try:
            with open(_token_path(), "r", encoding="utf-8") as fh:
                self._tok = json.load(fh) or {}
        except Exception:  # noqa: BLE001 -- no cache yet is normal
            self._tok = {}

    def _save_tokens(self) -> None:
        try:
            with open(_token_path(), "w", encoding="utf-8") as fh:
                json.dump(self._tok, fh)
        except Exception:  # noqa: BLE001
            pass

    # -- OAuth PKCE --------------------------------------------------------
    @staticmethod
    def _b64url(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def begin_auth(self) -> dict[str, Any]:
        """Start the PKCE flow. Returns the URL the user must open to authorize."""
        if not self.available():
            return _result(False, "SPOTIFY_CLIENT_ID not set")
        verifier = self._b64url(secrets.token_bytes(64))
        challenge = self._b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        state = secrets.token_urlsafe(16)
        with self._lock:
            self._pending = {"verifier": verifier, "state": state}
        from urllib.parse import urlencode
        url = _AUTH_BASE + "?" + urlencode({
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "scope": self._scopes,
            "state": state,
        })
        return _result(True, "open this URL to authorize Spotify",
                       authorize_url=url, state=state)

    def complete_auth(self, code: str, state: str | None = None) -> dict[str, Any]:
        """Exchange the redirect's ?code= for tokens."""
        import requests
        with self._lock:
            verifier = self._pending.get("verifier", "")
            expected_state = self._pending.get("state", "")
        if not verifier:
            return _result(False, "no auth in progress; call begin_auth first")
        if state is not None and expected_state and state != expected_state:
            return _result(False, "state mismatch -- possible CSRF, aborted")
        try:
            resp = requests.post(_TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect,
                "client_id": self._client_id,
                "code_verifier": verifier,
            }, timeout=15)
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"token request failed: {exc}")
        if resp.status_code != 200:
            return _result(False, f"token exchange rejected ({resp.status_code})")
        self._store_token_response(resp.json())
        with self._lock:
            self._pending = {}
        return _result(True, "Spotify connected")

    def _store_token_response(self, data: dict[str, Any]) -> None:
        with self._lock:
            if "access_token" in data:
                self._tok["access_token"] = data["access_token"]
                self._tok["expires_at"] = time.time() + int(data.get("expires_in", 3600)) - 30
            if data.get("refresh_token"):
                self._tok["refresh_token"] = data["refresh_token"]
            self._save_tokens()

    def _refresh(self) -> bool:
        import requests
        with self._lock:
            refresh = self._tok.get("refresh_token")
        if not refresh:
            return False
        try:
            resp = requests.post(_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": self._client_id,
            }, timeout=15)
        except Exception:  # noqa: BLE001
            return False
        if resp.status_code != 200:
            return False
        self._store_token_response(resp.json())
        return True

    def _access_token(self) -> str | None:
        with self._lock:
            tok = self._tok.get("access_token")
            exp = float(self._tok.get("expires_at", 0))
        if tok and time.time() < exp:
            return tok
        if self._refresh():
            with self._lock:
                return self._tok.get("access_token")
        return None

    # -- Web API ops -------------------------------------------------------
    def _headers(self) -> dict[str, str] | None:
        tok = self._access_token()
        return {"Authorization": f"Bearer {tok}"} if tok else None

    def _require(self) -> dict[str, Any] | None:
        if not self.available():
            return _result(False, "Spotify not configured (set SPOTIFY_CLIENT_ID)")
        if not self.connected():
            return _result(False, "Spotify not connected -- run begin_auth to link the account")
        if self._headers() is None:
            return _result(False, "Spotify token expired and could not refresh -- reconnect")
        return None

    def now_playing(self) -> dict[str, Any]:
        guard = self._require()
        if guard:
            return guard
        import requests
        try:
            resp = requests.get(f"{_API}/me/player", headers=self._headers(), timeout=10)
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"request failed: {exc}")
        if resp.status_code == 204:
            return _result(True, "nothing playing on Spotify", playing=False)
        if resp.status_code != 200:
            return _result(False, f"Spotify API {resp.status_code}")
        data = resp.json() or {}
        item = data.get("item") or {}
        return _result(True, "ok", playing=bool(data.get("is_playing")),
                       title=item.get("name", ""),
                       artist=", ".join(a.get("name", "") for a in item.get("artists", [])),
                       device=(data.get("device") or {}).get("name", ""))

    def search_track(self, query: str) -> dict[str, Any]:
        guard = self._require()
        if guard:
            return guard
        import requests
        try:
            resp = requests.get(f"{_API}/search", headers=self._headers(),
                                params={"q": query, "type": "track", "limit": 1},
                                timeout=10)
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"search failed: {exc}")
        if resp.status_code != 200:
            return _result(False, f"search API {resp.status_code}")
        items = (((resp.json() or {}).get("tracks") or {}).get("items") or [])
        if not items:
            return _result(False, f"no track found for '{query}'")
        t = items[0]
        return _result(True, "found", uri=t.get("uri"), title=t.get("name"),
                       artist=", ".join(a.get("name", "") for a in t.get("artists", [])))

    def play_query(self, query: str) -> dict[str, Any]:
        found = self.search_track(query)
        if not found.get("ok"):
            return found
        import requests
        try:
            resp = requests.put(f"{_API}/me/player/play", headers=self._headers(),
                                json={"uris": [found["uri"]]}, timeout=10)
        except Exception as exc:  # noqa: BLE001
            return _result(False, f"play failed: {exc}")
        if resp.status_code in (200, 202, 204):
            return _result(True, f"playing {found['title']} by {found['artist']}",
                           title=found["title"], artist=found["artist"])
        if resp.status_code == 404:
            return _result(False, "no active Spotify device -- open Spotify first")
        return _result(False, f"play API {resp.status_code}")


_client: SpotifyClient | None = None
_client_lock = threading.Lock()


def get_spotify_client() -> SpotifyClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = SpotifyClient()
    return _client
