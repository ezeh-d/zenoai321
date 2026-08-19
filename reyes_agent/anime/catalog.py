"""AniList as ZENO's anime/manga knowledge source.

WHY ANILIST
-----------
Free, public, GraphQL, and needs no API key for reads -- so ZENO can answer
"what is Chainsaw Man about" or "recommend something like Vinland Saga" with
real data and nothing to configure. Manhwa and manhua are covered too: they
are manga with countryOfOrigin KR/CN, which this surfaces plainly.

This module fetches FACTS about series. It never fetches the copyrighted
pages themselves -- reading a chapter is the owner showing ZENO an image they
already have (see reader.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_ENDPOINT = "https://graphql.anilist.co"
_TIMEOUT = 15.0

_MEDIA_FIELDS = """
  id
  title { romaji english native }
  format
  status
  countryOfOrigin
  episodes
  chapters
  volumes
  averageScore
  genres
  description(asHtml: false)
  siteUrl
  startDate { year }
"""


@dataclass
class Series:
    id: int
    title: str
    english: str
    native: str
    kind: str            # ANIME or MANGA
    format: str
    status: str
    origin: str          # JP / KR / CN
    episodes: int | None
    chapters: int | None
    score: int | None
    genres: tuple[str, ...]
    synopsis: str
    url: str
    year: int | None = None

    @property
    def flavour(self) -> str:
        """Manhwa/manhua vs manga vs anime, from format + origin."""
        if self.kind == "ANIME":
            return "anime"
        return {"KR": "manhwa", "CN": "manhua"}.get(self.origin, "manga")

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "english": self.english,
                "native": self.native, "kind": self.kind, "type": self.flavour,
                "format": self.format, "status": self.status,
                "episodes": self.episodes, "chapters": self.chapters,
                "score": self.score, "genres": list(self.genres),
                "year": self.year, "url": self.url,
                "synopsis": _clean(self.synopsis)}


def _clean(text: str, limit: int = 700) -> str:
    out = re.sub(r"<[^>]+>", "", str(text or "")).replace("&mdash;", "-")
    out = re.sub(r"\s+", " ", out).strip()
    return out[:limit] + ("..." if len(out) > limit else "")


def _series(node: dict[str, Any]) -> Series:
    title = node.get("title") or {}
    date = node.get("startDate") or {}
    return Series(
        id=int(node.get("id", 0)),
        title=title.get("romaji") or title.get("english") or "?",
        english=title.get("english") or "",
        native=title.get("native") or "",
        kind=node.get("type") or ("ANIME" if node.get("episodes") is not None else "MANGA"),
        format=node.get("format") or "",
        status=node.get("status") or "",
        origin=node.get("countryOfOrigin") or "",
        episodes=node.get("episodes"),
        chapters=node.get("chapters"),
        score=node.get("averageScore"),
        genres=tuple(node.get("genres") or ()),
        synopsis=node.get("description") or "",
        url=node.get("siteUrl") or "",
        year=date.get("year"),
    )


def _query(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """One POST to AniList. Raises RuntimeError with a plain message on failure."""
    import requests

    try:
        resp = requests.post(_ENDPOINT, json={"query": query, "variables": variables},
                             timeout=_TIMEOUT, headers={"Accept": "application/json"})
    except requests.RequestException as exc:
        raise RuntimeError(f"couldn't reach AniList: {exc}") from exc
    if resp.status_code == 429:
        raise RuntimeError("AniList is rate-limiting; try again in a moment")
    if resp.status_code >= 400:
        raise RuntimeError(f"AniList returned HTTP {resp.status_code}")
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "AniList error"))
    return payload.get("data") or {}


def search(name: str, *, kind: str = "", limit: int = 5) -> list[Series]:
    """Find series by name. kind='' searches both anime and manga."""
    variables: dict[str, Any] = {"search": str(name or "").strip(),
                                 "perPage": max(1, min(limit, 15))}
    kind = (kind or "").strip().upper()
    typed = kind in {"ANIME", "MANGA"}
    if typed:
        variables["type"] = kind
    query = f"""
    query ($search: String, $perPage: Int{', $type: MediaType' if typed else ''}) {{
      Page(perPage: $perPage) {{
        media(search: $search,{' type: $type,' if typed else ''} sort: SEARCH_MATCH) {{
          type {_MEDIA_FIELDS}
        }}
      }}
    }}"""
    data = _query(query, variables)
    return [_series(n) for n in (data.get("Page", {}).get("media") or [])]


def details(name: str, *, kind: str = "") -> Series | None:
    results = search(name, kind=kind, limit=1)
    return results[0] if results else None


def recommendations(name: str, *, kind: str = "",
                    limit: int = 6) -> tuple[Series | None, list[Series]]:
    """The best-matching series, plus what AniList recommends alongside it."""
    kind = (kind or "").strip().upper()
    typed = kind in {"ANIME", "MANGA"}
    variables: dict[str, Any] = {"search": str(name or "").strip()}
    if typed:
        variables["type"] = kind
    query = f"""
    query ($search: String{', $type: MediaType' if typed else ''}) {{
      Media(search: $search,{' type: $type,' if typed else ''} sort: SEARCH_MATCH) {{
        type {_MEDIA_FIELDS}
        recommendations(sort: RATING_DESC, perPage: {max(1, min(limit, 12))}) {{
          nodes {{ mediaRecommendation {{ type {_MEDIA_FIELDS} }} }}
        }}
      }}
    }}"""
    data = _query(query, variables)
    node = data.get("Media")
    if not node:
        return None, []
    base = _series(node)
    recs = [_series(r["mediaRecommendation"])
            for r in (node.get("recommendations", {}).get("nodes") or [])
            if r.get("mediaRecommendation")]
    return base, recs


def trending(*, kind: str = "ANIME", limit: int = 8) -> list[Series]:
    kind = (kind or "ANIME").strip().upper()
    if kind not in {"ANIME", "MANGA"}:
        kind = "ANIME"
    query = f"""
    query ($perPage: Int, $type: MediaType) {{
      Page(perPage: $perPage) {{
        media(type: $type, sort: TRENDING_DESC) {{ type {_MEDIA_FIELDS} }}
      }}
    }}"""
    data = _query(query, {"perPage": max(1, min(limit, 20)), "type": kind})
    return [_series(n) for n in (data.get("Page", {}).get("media") or [])]
