"""Live news as a brain tool -- current, ranked, de-duplicated, cited.

Wraps `news_engine` (fetch -> dedupe -> rank by recency + source quality) and
formats the result the way the brief asks (numbered headlines with source +
publication time), keeping the links so a follow-up like "open number 2" can be
carried out with the browser tools. Never invents headlines: an empty fetch says
so plainly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from reyes_agent.tools import register


def _when(published: str | None, now: datetime) -> str:
    if not published:
        return "date unknown"
    try:
        dt = datetime.fromisoformat(published)
    except (TypeError, ValueError):
        return "date unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = (now - dt).total_seconds() / 3600.0
    if age_h < 1:
        return f"{max(1, int(age_h * 60))} min ago"
    if age_h < 24:
        return f"{int(age_h)}h ago"
    return dt.strftime("%d %b, %H:%M UTC")


@register(
    name="live_news",
    description="Get CURRENT news on a topic, ranked newest-first with source "
                "quality and de-duplicated across outlets. Use for 'latest X "
                "news', 'what's happening today', 'any tech news'. Returns numbered "
                "stories with sources and links; a follow-up like 'open number 2' "
                "can then be opened with the browser.",
    input_schema={"type": "object", "properties": {
        "topic": {"type": "string", "description": "Topic/keywords, e.g. 'OpenAI', "
                  "'Nigeria', 'football'. Empty for top headlines."},
        "limit": {"type": "integer", "description": "How many stories (default 6)."},
    }, "required": []},
)
def live_news(topic: str = "", limit: int = 6) -> str:
    from reyes_agent import news_engine

    now = datetime.now(timezone.utc)
    result = news_engine.live_news(str(topic or ""), int(limit or 6), now=now)
    articles = result.get("articles") or []
    if not articles:
        return result.get("note", "No current headlines came back.")

    label = (f"LATEST {topic.strip().upper()} NEWS" if topic.strip()
             else "LATEST HEADLINES")
    lines = [label, ""]
    for i, art in enumerate(articles, 1):
        src = art.get("source") or "source unknown"
        corrob = art.get("corroboration", 1)
        also = f" (+{corrob - 1} more outlet{'s' if corrob > 2 else ''})" if corrob > 1 else ""
        lines.append(f"{i}. {art['title']}")
        lines.append(f"   Source: {src}{also} · Published: {_when(art.get('published'), now)}")
        if art.get("link"):
            lines.append(f"   Link: {art['link']}")
    lines.append("")
    lines.append(result.get("note", ""))

    # Same workspace panel as get_news, so headlines get a readable UI panel.
    try:
        from reyes_agent import notification_bus

        notification_bus.publish({"type": "workspace_news", "topic": label,
                                  "headlines": [{"title": a["title"], "link": a.get("link", ""),
                                                 "source": a.get("source", "")} for a in articles]})
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)
