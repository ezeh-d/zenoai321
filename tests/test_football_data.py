"""Contracts for the football-data.org adapter + grounded ratings (MOCKED -- no
network, so the free-tier quota is never touched by tests)."""

from __future__ import annotations

from reyes_agent.sports import ratings as rt
from reyes_agent.sports.providers import football_data as fd
from reyes_agent.sports.providers.football_data import FootballDataProvider


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response, count=None):
        self._response = response
        self.calls = 0

    def get(self, url, headers=None, timeout=0):
        self.calls += 1
        return self._response


_STANDINGS = {"standings": [{"type": "TOTAL", "table": [
    {"position": 1, "team": {"id": 5, "shortName": "Bayern", "name": "FC Bayern"},
     "playedGames": 30, "points": 80, "won": 25, "draw": 5, "lost": 0,
     "goalsFor": 90, "goalsAgainst": 25},
    {"position": 2, "team": {"id": 3, "shortName": "Leverkusen", "name": "Bayer Leverkusen"},
     "playedGames": 30, "points": 70, "won": 22, "draw": 4, "lost": 4,
     "goalsFor": 70, "goalsAgainst": 35},
]}]}


def test_available_reflects_key():
    assert FootballDataProvider(api_key="k").available() is True
    assert FootballDataProvider(api_key="").available() is False


def test_health_states():
    assert FootballDataProvider(api_key="").health()["status"] == fd.AUTH_REQUIRED
    p = FootballDataProvider(api_key="k", session=_Session(_Resp(429)))
    assert p.health()["status"] == fd.RATE_LIMITED
    p2 = FootballDataProvider(api_key="k", session=_Session(_Resp(401)))
    assert p2.health()["status"] == fd.AUTH_REQUIRED


def test_get_caches_within_ttl():
    sess = _Session(_Resp(200, _STANDINGS))
    p = FootballDataProvider(api_key="k", session=sess, cache_ttl=100.0)
    p.standings("BL1")
    p.standings("BL1")                       # same path -> served from cache
    assert sess.calls == 1


def test_standings_and_find_team():
    p = FootballDataProvider(api_key="k", session=_Session(_Resp(200, _STANDINGS)))
    table = p.standings("Bundesliga")
    assert table[0]["team"] == "Bayern" and table[0]["goals_for"] == 90
    assert p.find_team("bayern")["team_id"] == 5


def test_matches_parse():
    payload = {"matches": [{"id": 1, "status": "SCHEDULED", "utcDate": "2026-08-30",
                            "homeTeam": {"id": 5, "shortName": "Bayern"},
                            "awayTeam": {"id": 9, "shortName": "Stuttgart"},
                            "score": {"fullTime": {"home": None, "away": None}},
                            "competition": {"name": "Bundesliga"}}]}
    p = FootballDataProvider(api_key="k", session=_Session(_Resp(200, payload)))
    ms = p.team_matches(5, "SCHEDULED")
    assert ms[0]["home"] == "Bayern" and ms[0]["away"] == "Stuttgart"


# --- ratings bridge ---------------------------------------------------------
class _FakeProvider:
    """A provider whose data comes from canned tables (no network)."""
    def __init__(self, standings, results, played=30):
        self._standings = standings
        self._results = results

    def standings(self, competition="BL1", season=""):
        return self._standings

    def find_team(self, name, competition="BL1", season=""):
        want = name.casefold()
        for r in self._standings:
            if want in r["team"].casefold():
                return r
        return None

    def recent_results(self, competition="BL1", limit=60, season=""):
        return self._results


def _rows():
    return [
        {"position": 1, "team_id": 5, "team": "Bayern", "played": 30,
         "goals_for": 90, "goals_against": 25},
        {"position": 2, "team_id": 3, "team": "Leverkusen", "played": 30,
         "goals_for": 70, "goals_against": 35},
    ]


def test_build_elo_from_results():
    book = rt.build_elo([
        {"home": "Bayern", "away": "Leverkusen", "home_goals": 3, "away_goals": 0},
        {"home": "Bayern", "away": "Leverkusen", "home_goals": 2, "away_goals": 1},
    ])
    assert book.rating("Bayern") > book.rating("Leverkusen")


def test_grounded_prediction_favours_stronger_team():
    prov = _FakeProvider(_rows(), [
        {"home": "Bayern", "away": "Leverkusen", "home_goals": 3, "away_goals": 1}])
    pred = rt.grounded_prediction("Bayern", "Leverkusen", prov)
    assert pred is not None
    d = pred.as_dict()
    assert d["probabilities"]["home_win"] > d["probabilities"]["away_win"]
    assert d["expected_goals"]["home"] > d["expected_goals"]["away"]
    assert "grounded" in pred.reasons[0]


def test_grounded_prediction_none_when_team_missing():
    prov = _FakeProvider(_rows(), [])
    assert rt.grounded_prediction("Bayern", "NonexistentFC", prov) is None
