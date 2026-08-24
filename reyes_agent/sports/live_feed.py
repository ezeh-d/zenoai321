"""LiveFeedEngine -- one normalized live-score surface over many sports.

Turns each sport's differently-shaped API-Sports payload into ONE LiveGame model
so the phone, laptop, voice and orb all read the same normalized feed from a
single cached fetch (Pack 7 #1, #6, #27, #76). Health is honest per sport
(LIVE/NO_COVERAGE/RATE_LIMITED/AUTH_REQUIRED); nothing is invented -- an empty
feed says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reyes_agent.sports.providers import api_sports as aps


@dataclass
class LiveGame:
    sport: str
    league: str
    home: str
    away: str
    home_score: int | None
    away_score: int | None
    status: str
    clock: str
    provider: str = "api-sports"

    def as_dict(self) -> dict[str, Any]:
        return {"sport": self.sport, "league": self.league,
                "home": self.home, "away": self.away,
                "home_score": self.home_score, "away_score": self.away_score,
                "status": self.status, "clock": self.clock, "provider": self.provider}


def _score(value: Any) -> int | None:
    """A score may arrive as an int, or a dict like {'total': 88} / nested."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        for key in ("total", "points", "score"):
            if isinstance(value.get(key), (int, float)):
                return int(value[key])
    return None


def _team(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("name") or node.get("team") or "")
    return str(node or "")


def normalize(sport: str, game: dict[str, Any]) -> LiveGame | None:
    """Map one raw game (football 'fixture' shape OR generic 'games' shape)."""
    try:
        sport = aps.normalise_sport(sport)
        league = str((game.get("league") or {}).get("name", "")) if isinstance(game.get("league"), dict) else ""
        teams = game.get("teams") or {}
        home, away = _team(teams.get("home")), _team(teams.get("away"))
        if "fixture" in game:                       # football
            fixture = game.get("fixture") or {}
            st = fixture.get("status") or {}
            goals = game.get("goals") or {}
            return LiveGame(sport, league, home, away,
                            _score(goals.get("home")), _score(goals.get("away")),
                            str(st.get("short", "")),
                            f"{st.get('elapsed', '')}'" if st.get("elapsed") is not None else "")
        scores = game.get("scores") or {}           # generic games
        st = game.get("status") or {}
        clock = str(st.get("timer") or st.get("clock") or st.get("elapsed") or "")
        return LiveGame(sport, league, home, away,
                        _score(scores.get("home")), _score(scores.get("away")),
                        str(st.get("short") or st.get("long") or ""), clock)
    except Exception:  # noqa: BLE001 -- one odd record can't sink the feed
        return None


class LiveFeedEngine:
    def __init__(self, provider: aps.ApiSportsProvider | None = None) -> None:
        self._provider = provider or aps.get_provider()

    def live(self, sport: str = "football") -> dict[str, Any]:
        sport = aps.normalise_sport(sport)
        if not self._provider.available():
            return {"status": aps.AUTH_REQUIRED, "sport": sport, "games": [],
                    "note": "No API-Sports key configured."}
        if not self._provider.supported(sport):
            return {"status": aps.NO_COVERAGE, "sport": sport, "games": [],
                    "note": f"'{sport}' is not covered."}
        state, raw = self._provider.live_raw(sport)
        if state != aps.AVAILABLE:
            return {"status": state, "sport": sport, "games": [],
                    "note": f"live {sport} feed is {state}."}
        games = [g.as_dict() for g in (normalize(sport, r) for r in raw) if g is not None]
        return {"status": "LIVE" if games else aps.AVAILABLE, "sport": sport,
                "count": len(games), "games": games,
                "note": "" if games else f"No live {sport} matches right now."}

    def supported_sports(self) -> list[str]:
        return list(aps.SPORTS)


_instance: LiveFeedEngine | None = None


def get_engine() -> LiveFeedEngine:
    global _instance
    if _instance is None:
        _instance = LiveFeedEngine()
    return _instance
