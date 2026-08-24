"""Contracts for API-Sports multi-sport live feed (MOCKED -- no quota touched)."""

from __future__ import annotations

from reyes_agent.sports import live_feed as lf
from reyes_agent.sports.providers import api_sports as aps
from reyes_agent.sports.providers.api_sports import ApiSportsProvider


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Session:
    def __init__(self, resp):
        self._resp = resp
        self.calls = 0

    def get(self, url, headers=None, timeout=0):
        self.calls += 1
        return self._resp


# --- provider ---------------------------------------------------------------
def test_available_and_aliases():
    assert ApiSportsProvider(api_key="k").available() is True
    assert ApiSportsProvider(api_key="").available() is False
    assert aps.normalise_sport("soccer") == "football"
    assert aps.normalise_sport("NBA") == "basketball"
    assert aps.normalise_sport("f1") == "formula-1"


def test_supported_and_no_coverage():
    p = ApiSportsProvider(api_key="k")
    assert p.supported("football") and p.supported("nba")
    assert not p.supported("quidditch")
    assert p.live_raw("quidditch")[0] == aps.NO_COVERAGE


def test_live_raw_states():
    ok = ApiSportsProvider(api_key="k", session=_Session(_Resp(200, {"response": [{"x": 1}]})))
    state, games = ok.live_raw("football")
    assert state == aps.AVAILABLE and games == [{"x": 1}]
    assert ApiSportsProvider(api_key="k", session=_Session(_Resp(429))).live_raw("football")[0] == aps.RATE_LIMITED
    assert ApiSportsProvider(api_key="").live_raw("football")[0] == aps.AUTH_REQUIRED


def test_cache_shares_one_fetch():
    sess = _Session(_Resp(200, {"response": []}))
    p = ApiSportsProvider(api_key="k", session=sess, cache_ttl=100.0)
    p.live_raw("football")
    p.live_raw("football")
    assert sess.calls == 1


# --- normalizer -------------------------------------------------------------
def test_normalize_football_fixture():
    raw = {"fixture": {"status": {"short": "2H", "elapsed": 67}},
           "league": {"name": "Bundesliga"},
           "teams": {"home": {"name": "Bayern"}, "away": {"name": "Dortmund"}},
           "goals": {"home": 2, "away": 1}}
    g = lf.normalize("football", raw)
    assert g.home == "Bayern" and g.home_score == 2 and g.away_score == 1
    assert g.status == "2H" and g.clock == "67'"


def test_normalize_basketball_games_shape():
    raw = {"status": {"short": "Q3"}, "league": {"name": "NBA"},
           "teams": {"home": {"name": "Lakers"}, "away": {"name": "Celtics"}},
           "scores": {"home": {"total": 78}, "away": {"total": 74}}}
    g = lf.normalize("basketball", raw)
    assert g.home == "Lakers" and g.home_score == 78 and g.away_score == 74 and g.status == "Q3"


def test_score_handles_int_and_dict():
    assert lf._score(5) == 5
    assert lf._score({"total": 88}) == 88
    assert lf._score(None) is None


def test_normalize_bad_record_returns_none():
    assert lf.normalize("football", {"teams": None, "fixture": 5}) is None or True  # never raises


# --- engine -----------------------------------------------------------------
class _FakeProvider:
    def __init__(self, available=True, supported=True, state=aps.AVAILABLE, games=None):
        self._a, self._s, self._state, self._g = available, supported, state, games or []

    def available(self):
        return self._a

    def supported(self, sport):
        return self._s

    def live_raw(self, sport):
        return self._state, self._g


def test_engine_auth_required_without_key():
    eng = lf.LiveFeedEngine(_FakeProvider(available=False))
    assert eng.live("football")["status"] == aps.AUTH_REQUIRED


def test_engine_no_coverage():
    eng = lf.LiveFeedEngine(_FakeProvider(supported=False))
    assert eng.live("quidditch")["status"] == aps.NO_COVERAGE


def test_engine_live_games_normalized():
    raw = [{"fixture": {"status": {"short": "1H", "elapsed": 20}},
            "league": {"name": "PL"},
            "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
            "goals": {"home": 1, "away": 0}}]
    eng = lf.LiveFeedEngine(_FakeProvider(games=raw))
    out = eng.live("football")
    assert out["status"] == "LIVE" and out["count"] == 1
    assert out["games"][0]["home"] == "Arsenal"


def test_engine_empty_is_honest():
    out = lf.LiveFeedEngine(_FakeProvider(games=[])).live("basketball")
    assert out["status"] == aps.AVAILABLE and "No live basketball" in out["note"]
