"""Anime and manga tools: know a series, read a page, track a shelf.

The knowledge comes from AniList's free public API (no key). The reading comes
from ZENO's vision model, which understands a manga/manhwa page -- art and
dialogue, in Japanese, Korean or English -- the way OCR cannot. The shelf is
local. None of it fetches copyrighted chapters from anywhere.
"""

from __future__ import annotations

import io

from reyes_agent.tools import register


def _line(s) -> str:
    bits = [f"{s.title}"]
    if s.english and s.english != s.title:
        bits.append(f"({s.english})")
    tag = s.flavour
    meta = [tag]
    if s.year:
        meta.append(str(s.year))
    if s.score:
        meta.append(f"{s.score}/100")
    if s.kind == "ANIME" and s.episodes:
        meta.append(f"{s.episodes} eps")
    if s.kind == "MANGA" and s.chapters:
        meta.append(f"{s.chapters} ch")
    if s.status:
        meta.append(s.status.lower().replace("_", " "))
    return f"{' '.join(bits)} -- {', '.join(meta)}"


@register(
    name="anime_search",
    description=(
        "Search for an anime or manga/manhwa by name and return real details "
        "from AniList: titles, type, score, status, episode/chapter counts, "
        "genres. Use for 'what is Chainsaw Man', 'find that manhwa Solo "
        "Leveling'. Set kind to 'anime' or 'manga' to narrow it, or leave "
        "blank for both."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The series name to search for."},
            "kind": {"type": "string", "description": "'anime', 'manga', or blank for both."},
        },
        "required": ["query"],
    },
)
def anime_search(query: str, kind: str = "") -> str:
    from reyes_agent.anime import catalog

    if not str(query or "").strip():
        return "What series should I look up?"
    try:
        results = catalog.search(query, kind=kind, limit=6)
    except RuntimeError as exc:
        return f"Couldn't search AniList: {exc}"
    if not results:
        return f"Nothing on AniList matched '{query}'."
    lines = [_line(s) for s in results]
    return f"Found {len(results)} for '{query}':\n" + "\n".join(f"- {l}" for l in lines)


@register(
    name="anime_info",
    description=(
        "Get the full details and synopsis of one specific anime or manga/"
        "manhwa. Use when the owner wants to know what a series is about, its "
        "score, how many episodes/chapters, or whether it's finished."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The exact-ish series name."},
            "kind": {"type": "string", "description": "'anime' or 'manga' to disambiguate."},
        },
        "required": ["title"],
    },
)
def anime_info(title: str, kind: str = "") -> str:
    from reyes_agent.anime import catalog

    try:
        series = catalog.details(title, kind=kind)
    except RuntimeError as exc:
        return f"Couldn't reach AniList: {exc}"
    if series is None:
        return f"Nothing on AniList matched '{title}'."
    d = series.as_dict()
    header = _line(series)
    genres = ", ".join(d["genres"]) or "—"
    native = f"\nNative title: {series.native}" if series.native else ""
    return (f"{header}{native}\n"
            f"Genres: {genres}\n"
            f"AniList: {d['url']}\n\n"
            f"{d['synopsis'] or 'No synopsis on file.'}")


@register(
    name="anime_recommend",
    description=(
        "Recommend series similar to one the owner names, using AniList's "
        "community recommendations. Use for 'something like Vinland Saga', "
        "'what should I read after Solo Leveling'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The series to base recommendations on."},
            "kind": {"type": "string", "description": "'anime' or 'manga' to narrow."},
        },
        "required": ["title"],
    },
)
def anime_recommend(title: str, kind: str = "") -> str:
    from reyes_agent.anime import catalog

    try:
        base, recs = catalog.recommendations(title, kind=kind)
    except RuntimeError as exc:
        return f"Couldn't reach AniList: {exc}"
    if base is None:
        return f"Nothing on AniList matched '{title}'."
    if not recs:
        return f"AniList has no community recommendations for {base.title} yet."
    lines = "\n".join(f"- {_line(s)}" for s in recs)
    return f"Because you liked {base.title}, AniList suggests:\n{lines}"


@register(
    name="anime_trending",
    description=(
        "Show what anime or manga is trending on AniList right now. Use for "
        "'what's popular', 'what should I watch this season'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "'anime' (default) or 'manga'."},
        },
    },
)
def anime_trending(kind: str = "anime") -> str:
    from reyes_agent.anime import catalog

    try:
        results = catalog.trending(kind=kind, limit=8)
    except RuntimeError as exc:
        return f"Couldn't reach AniList: {exc}"
    if not results:
        return "AniList returned nothing trending right now."
    what = "manga/manhwa" if str(kind).lower().startswith("m") else "anime"
    return f"Trending {what} now:\n" + "\n".join(f"- {_line(s)}" for s in results)


@register(
    name="read_manga_page",
    description=(
        "READ and understand a manga or manhwa PAGE: the dialogue in the "
        "right order, who says what, and what happens -- translating Japanese "
        "or Korean text if needed. Give a 'path' to an image file, or omit it "
        "to read what's on screen (a webtoon in the browser). Set 'format' to "
        "manga (right-to-left), manhwa (vertical scroll), manhua, comic, or "
        "auto. Reads pages the owner already has; it does not download "
        "chapters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Image file to read. Omit to read the screen."},
            "format": {"type": "string", "description": "manga / manhwa / manhua / comic / auto."},
            "focus": {"type": "string", "description": "Optional: a specific question about the page."},
        },
    },
)
def read_manga_page(path: str = "", format: str = "auto", focus: str = "") -> str:
    from reyes_agent.anime import reader

    image_bytes = b""
    source = ""
    if str(path or "").strip():
        from pathlib import Path

        target = Path(path.strip())
        if not target.exists():
            return f"No file at {target}."
        try:
            image_bytes = target.read_bytes()
            source = str(target)
        except OSError as exc:
            return f"Couldn't read {target}: {exc}"
    else:
        try:
            import pyautogui

            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=88)
            image_bytes = buf.getvalue()
            source = "the screen"
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't capture the screen: {exc}"

    result = reader.read_page(image_bytes, fmt=format, focus=focus)
    if not result.ok:
        return f"Couldn't read the page: {result.detail}"
    return f"Reading {source} as {result.fmt}:\n\n{result.text}"


@register(
    name="track_series",
    description=(
        "Record what the owner is watching or reading and how far along they "
        "are, so ZENO can pick it up later. Use for 'I'm on episode 12 of "
        "Frieren', 'add Solo Leveling to my reading list', 'I finished "
        "Berserk'. Status: watching, reading, completed, on_hold, dropped, "
        "planned."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The series name."},
            "kind": {"type": "string", "description": "'anime' or 'manga'."},
            "status": {"type": "string", "description": "watching/reading/completed/on_hold/dropped/planned."},
            "progress": {"type": "integer", "description": "Episode or chapter number reached."},
            "total": {"type": "integer", "description": "Total episodes/chapters, if known."},
            "note": {"type": "string", "description": "Optional note."},
        },
        "required": ["title", "kind"],
    },
)
def track_series(title: str, kind: str, status: str = "", progress: int | None = None,
                 total: int | None = None, note: str = "") -> str:
    from reyes_agent.anime import library

    ok = library.get_shelf().track(title, kind, status=status, progress=progress,
                                   total=total, note=note)
    if not ok:
        return "I need at least a title and whether it's anime or manga."
    entry = library.get_shelf().get(title, kind)
    if entry is None:
        return "Saved."
    d = entry.as_dict()
    return f"Tracked: {d['title']} — {d['status']}, {d['progress']}."


@register(
    name="my_shelf",
    description=(
        "List what the owner is watching and reading, with their progress. "
        "Use for 'what am I watching', 'where was I in Solo Leveling', 'my "
        "reading list'. Filter by status (e.g. watching) or kind (anime/"
        "manga) if asked."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter: watching/reading/completed/etc."},
            "kind": {"type": "string", "description": "Filter: 'anime' or 'manga'."},
        },
    },
)
def my_shelf(status: str = "", kind: str = "") -> str:
    from reyes_agent.anime import library

    entries = library.get_shelf().shelf(status=status, kind=kind)
    if not entries:
        return "Your shelf is empty. Tell me what you're watching or reading and I'll track it."
    lines = []
    for e in entries:
        d = e.as_dict()
        note = f" — {d['note']}" if d["note"] else ""
        lines.append(f"- {d['title']} ({d['type']}): {d['status']}, {d['progress']}{note}")
    return "On your shelf:\n" + "\n".join(lines)
