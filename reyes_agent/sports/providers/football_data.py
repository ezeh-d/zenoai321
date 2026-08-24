"""football-data.org adapter -- real fixtures, results and standings.

Free tier: ~10 requests/minute over a set of major competitions (Bundesliga,
Premier League, Champions League, La Liga, Serie A, ...). This caches every
response for a few minutes so the phone, laptop and voice share one fetch
(Pack 7 #27), and reports honest health rather than pretending coverage. The API
key is read from the environment (.env, gitignored); it is never logged.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

BASE = "https://api.football-data.org/v4"

# Honest health states (Pack 7 #69).
AVAILABLE = "AVAILABLE"
AUTH_REQUIRED = "AUTH_REQUIRED"
RATE_LIMITED = "RATE_LIMITED"
UNAVAILABLE = "UNAVAILABLE"

# A few well-known competition codes so callers can say "Bundesliga".
COMPETITIONS = {
    "bundesliga": "BL1", "premier league": "PL", "epl": "PL",
    "la liga": "PD", "serie a": "SA", "ligue 1": "FL1",
    "champions league": "CL", "ucl": "CL", "eredivisie": "DED",
    "primeira liga": "PPL", "championship": "ELC",
}


class FootballDataProvider:
    def __init__(self, api_key: str | None = None, *, cache_ttl: float = 300.0,
                 session: Any = None) -> None:
        # Importing config loads the gitignored .env; then read the key.
        if api_key is None:
            try:
                from reyes_agent import config  # noqa: F401  (triggers load_dotenv)
            except Exception:  # noqa: BLE001
                pass
            api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "")
        self._key = (api_key or "").strip()
        self._ttl = float(cache_ttl)
        self._session = session          # injectable for tests (must have .get)
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def available(self) -> bool:
        return bool(self._key)

    def _client(self):
        if self._session is not None:
            return self._session
        import requests

        return requests

    def _get(self, path: str, *, now: float | None = None) -> tuple[str, Any]:
        """Cached GET. Returns (health_state, json|None). Never raises."""
        if not self._key:
            return AUTH_REQUIRED, None
        now = now if now is not None else time.time()
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] > now:
                return AVAILABLE, hit[1]
        try:
            resp = self._client().get(f"{BASE}{path}",
                                      headers={"X-Auth-Token": self._key}, timeout=15)
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
            self._cache[path] = (now + self._ttl, data)
        return AVAILABLE, data

    def health(self) -> dict[str, Any]:
        if not self._key:
            return {"provider": "football-data.org", "status": AUTH_REQUIRED}
        state, _ = self._get("/competitions/BL1")
        return {"provider": "football-data.org", "status": state}

    # -- data ------------------------------------------------------------
    def competition_code(self, name: str) -> str:
        return COMPETITIONS.get(str(name or "").strip().casefold(), str(name or "").upper() or "BL1")

    def standings(self, competition: str = "BL1", season: str = "") -> list[dict[str, Any]]:
        code = self.competition_code(competition)
        path = f"/competitions/{code}/standings"
        if season:
            path += f"?season={season}"
        state, data = self._get(path)
        if state != AVAILABLE or not data:
            return []
        for group in data.get("standings", []):
            if group.get("type") == "TOTAL":
                return [self._row(r) for r in group.get("table", [])]
        groups = data.get("standings", [])
        return [self._row(r) for r in (groups[0].get("table", []) if groups else [])]

    @staticmethod
    def _row(r: dict[str, Any]) -> dict[str, Any]:
        team = r.get("team", {})
        return {"position": r.get("position"),
                "team_id": team.get("id"),
                "team": team.get("shortName") or team.get("name"),
                "played": r.get("playedGames"), "points": r.get("points"),
                "won": r.get("won"), "draw": r.get("draw"), "lost": r.get("lost"),
                "goals_for": r.get("goalsFor"), "goals_against": r.get("goalsAgainst")}

    def find_team(self, name: str, competition: str = "BL1", season: str = "") -> dict[str, Any] | None:
        want = str(name or "").strip().casefold()
        if not want:
            return None
        for row in self.standings(competition, season):
            tname = str(row.get("team", "")).casefold()
            if want in tname or tname in want or want.split()[0] in tname:
                return row
        return None

    def team_matches(self, team_id: int, status: str = "") -> list[dict[str, Any]]:
        path = f"/teams/{int(team_id)}/matches"
        if status:
            path += f"?status={status.upper()}"
        state, data = self._get(path)
        if state != AVAILABLE or not data:
            return []
        return [self._match(m) for m in data.get("matches", [])]

    def recent_results(self, competition: str = "BL1", limit: int = 60,
                       season: str = "") -> list[dict[str, Any]]:
        code = self.competition_code(competition)
        path = f"/competitions/{code}/matches?status=FINISHED"
        if season:
            path += f"&season={season}"
        state, data = self._get(path)
        if state != AVAILABLE or not data:
            return []
        return [self._match(m) for m in data.get("matches", [])][-max(1, limit):]

    @staticmethod
    def _match(m: dict[str, Any]) -> dict[str, Any]:
        score = m.get("score", {}).get("fullTime", {})
        return {"id": m.get("id"), "status": m.get("status"),
                "utc_date": m.get("utcDate"),
                "home": (m.get("homeTeam") or {}).get("shortName") or (m.get("homeTeam") or {}).get("name"),
                "away": (m.get("awayTeam") or {}).get("shortName") or (m.get("awayTeam") or {}).get("name"),
                "home_id": (m.get("homeTeam") or {}).get("id"),
                "away_id": (m.get("awayTeam") or {}).get("id"),
                "home_goals": score.get("home"), "away_goals": score.get("away"),
                "competition": (m.get("competition") or {}).get("name")}


_instance: FootballDataProvider | None = None
_lock = threading.Lock()


def get_provider() -> FootballDataProvider:
    global _instance
    with _lock:
        if _instance is None:
            _instance = FootballDataProvider()
        return _instance
