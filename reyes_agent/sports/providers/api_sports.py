"""API-Sports adapter -- live in-play scores across MANY sports.

One key (x-apisports-key, read from the gitignored .env) covers football,
basketball, baseball, hockey, rugby, American football, volleyball, handball and
Formula 1, each on its own host. Free tier = 100 requests/day, so live results
are cached briefly and shared across every interface. Honest health states; the
key is never logged.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

# Per-sport API hosts.
_SPORT_HOSTS = {
    "football": "v3.football.api-sports.io",
    "basketball": "v1.basketball.api-sports.io",
    "baseball": "v1.baseball.api-sports.io",
    "hockey": "v1.hockey.api-sports.io",
    "rugby": "v1.rugby.api-sports.io",
    "american-football": "v1.american-football.api-sports.io",
    "volleyball": "v1.volleyball.api-sports.io",
    "handball": "v1.handball.api-sports.io",
    "formula-1": "v1.formula-1.api-sports.io",
}
# Football uses /fixtures; the rest use /games.
_LIVE_PATH = {"football": "/fixtures?live=all"}
_DEFAULT_LIVE = "/games?live=all"

# Aliases so "soccer"/"nba"/"f1" resolve.
_ALIASES = {"soccer": "football", "nba": "basketball", "mlb": "baseball",
            "nhl": "hockey", "nfl": "american-football", "f1": "formula-1",
            "formula1": "formula-1"}

AVAILABLE = "AVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
RATE_LIMITED = "RATE_LIMITED"
NO_COVERAGE = "NO_COVERAGE"
UNAVAILABLE = "UNAVAILABLE"

SPORTS = tuple(_SPORT_HOSTS)


def normalise_sport(sport: str) -> str:
    s = str(sport or "").strip().casefold().replace(" ", "-")
    return _ALIASES.get(s, s)


class ApiSportsProvider:
    def __init__(self, api_key: str | None = None, *, cache_ttl: float = 25.0,
                 session: Any = None) -> None:
        if api_key is None:
            try:
                from reyes_agent import config  # noqa: F401  (loads .env)
            except Exception:  # noqa: BLE001
                pass
            api_key = os.environ.get("API_SPORTS_KEY", "")
        self._key = (api_key or "").strip()
        self._ttl = float(cache_ttl)
        self._session = session
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def available(self) -> bool:
        return bool(self._key)

    def supported(self, sport: str) -> bool:
        return normalise_sport(sport) in _SPORT_HOSTS

    def _client(self):
        if self._session is not None:
            return self._session
        import requests

        return requests

    def _get(self, sport: str, path: str, *, now: float | None = None) -> tuple[str, Any]:
        if not self._key:
            return AUTH_REQUIRED, None
        sport = normalise_sport(sport)
        host = _SPORT_HOSTS.get(sport)
        if not host:
            return NO_COVERAGE, None
        key = f"{host}{path}"
        now = now if now is not None else time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] > now:
                return AVAILABLE, hit[1]
        try:
            resp = self._client().get(f"https://{host}{path}",
                                      headers={"x-apisports-key": self._key}, timeout=15)
        except Exception:  # noqa: BLE001
            return UNAVAILABLE, None
        code = getattr(resp, "status_code", 0)
        if code == 429:
            return RATE_LIMITED, None
        if code in (401, 403):
            return AUTH_REQUIRED, None
        if code != 200:
            return UNAVAILABLE, None
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return UNAVAILABLE, None
        with self._lock:
            self._cache[key] = (now + self._ttl, data)
        return AVAILABLE, data

    def status(self) -> dict[str, Any]:
        """Account/quota status (cheap; football host)."""
        if not self._key:
            return {"provider": "api-sports", "status": AUTH_REQUIRED}
        state, data = self._get("football", "/status")
        out: dict[str, Any] = {"provider": "api-sports", "status": state}
        if state == AVAILABLE and isinstance(data, dict):
            resp = data.get("response", {})
            out["plan"] = (resp.get("subscription") or {}).get("plan")
            reqs = resp.get("requests") or {}
            out["requests"] = {"used": reqs.get("current"), "limit": reqs.get("limit_day")}
        return out

    def live_raw(self, sport: str) -> tuple[str, list[dict[str, Any]]]:
        sport = normalise_sport(sport)
        if sport not in _SPORT_HOSTS:
            return NO_COVERAGE, []
        path = _LIVE_PATH.get(sport, _DEFAULT_LIVE)
        state, data = self._get(sport, path)
        if state != AVAILABLE or not isinstance(data, dict):
            return state, []
        return AVAILABLE, data.get("response", []) or []


_instance: ApiSportsProvider | None = None
_lock = threading.Lock()


def get_provider() -> ApiSportsProvider:
    global _instance
    with _lock:
        if _instance is None:
            _instance = ApiSportsProvider()
        return _instance
