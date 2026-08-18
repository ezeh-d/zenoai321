"""One honest view of ZENO's social presence.

THE RULE THIS MODULE EXISTS TO ENFORCE
--------------------------------------
Every number here came from a platform API call that was recorded in the
store, or it is absent. There is no default of 0 for "we never asked" --
0 followers and "not connected" are completely different facts, and a
dashboard that renders them identically is lying quietly.

So each block carries `available`, and when it is False the reason is
stated: NOT_CONFIGURED, AUTH_REQUIRED, disabled, or simply never collected.
The web client renders those words rather than a zero.
"""

from __future__ import annotations

import time
from typing import Any

from reyes_agent.social import control, store as social_store
from reyes_agent.social.adapters import all_adapters

UNAVAILABLE = "NOT AVAILABLE"


def _account_block(platform: str, store: social_store.SocialStore) -> dict[str, Any]:
    """One platform, and an explicit reason when there is nothing to show."""
    adapter = all_adapters().get(platform)
    account = store.account(platform) or {}
    block: dict[str, Any] = {
        "platform": platform,
        "enabled": control.platform_enabled(platform),
        "connected": bool(account.get("connected")),
        "username": account.get("username") or "",
        "token_state": account.get("token_state") or "NONE",
        "available": False,
        "reason": "",
    }

    if adapter is None:
        block["reason"] = f"no adapter for {platform}"
        return block
    if not block["enabled"]:
        block["reason"] = f"{platform} is disabled in the owner control panel"
        return block

    # The last snapshot this platform actually returned. Never synthesised.
    snapshots = store.account_snapshots(platform, limit=2)
    if not snapshots:
        block["reason"] = (
            f"no metrics have ever been collected from {platform}. "
            f"Connect the account, then run an analytics collection.")
        return block

    # store.account_snapshots returns OLDEST FIRST (it reverses its own DESC
    # query), so the newest reading is the last element. Reading index 0 as
    # "latest" reported a stale follower count and an inverted growth figure --
    # it would have shown a gain as a loss.
    latest = snapshots[-1]
    metrics = latest.get("metrics") or {}
    block["available"] = True
    block["collected_at"] = latest.get("collected_at")
    block["followers"] = metrics.get("followers", UNAVAILABLE)
    block["posts"] = metrics.get("posts", UNAVAILABLE)

    # Growth needs two points in time. One snapshot is a reading, not a trend.
    if len(snapshots) > 1:
        earlier = snapshots[-2]
        previous = (earlier.get("metrics") or {}).get("followers")
        current = metrics.get("followers")
        if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
            block["followers_gained"] = current - previous
            block["since"] = earlier.get("collected_at")
    return block


def _post_block(platform: str, store: social_store.SocialStore) -> dict[str, Any]:
    """Latest and best published post, judged only on recorded analytics."""
    published = store.list_content(status=social_store.PUBLISHED,
                                   platform=platform, limit=50)
    out: dict[str, Any] = {"published_count": len(published)}
    if not published:
        out["latest"] = None
        out["best"] = None
        out["reason"] = f"nothing has been published to {platform} yet"
        return out

    def _summary(item: dict[str, Any]) -> dict[str, Any]:
        analytics = store.latest_analytics(item["content_id"]) or {}
        metrics = analytics.get("metrics") or {}
        return {
            "content_id": item["content_id"],
            "title": item.get("title", ""),
            "category": item.get("category", ""),
            "post_url": item.get("post_url") or "",
            "published_at": item.get("published_at"),
            "views": metrics.get("views", UNAVAILABLE),
            "likes": metrics.get("likes", UNAVAILABLE),
            "comments": metrics.get("comments", UNAVAILABLE),
            "has_analytics": bool(metrics),
        }

    summaries = [_summary(item) for item in published]
    out["latest"] = max(summaries, key=lambda s: s.get("published_at") or 0)

    # "Best" requires a comparable number. Posts with no analytics are not
    # ranked as zero -- they are excluded, and that exclusion is reported.
    rankable = [s for s in summaries if isinstance(s.get("views"), (int, float))]
    if rankable:
        out["best"] = max(rankable, key=lambda s: s["views"])
    else:
        out["best"] = None
        out["reason"] = ("no published post has analytics yet, so none can be "
                         "called the best")
    return out


def _next_scheduled(platform: str,
                    store: social_store.SocialStore) -> dict[str, Any] | None:
    scheduled = store.list_content(status=social_store.SCHEDULED,
                                   platform=platform, limit=20)
    upcoming = [s for s in scheduled if s.get("scheduled_for")]
    if not upcoming:
        return None
    item = min(upcoming, key=lambda s: s["scheduled_for"])
    return {"content_id": item["content_id"], "title": item.get("title", ""),
            "scheduled_for": item["scheduled_for"]}


def platform_view(platform: str,
                  store: social_store.SocialStore | None = None) -> dict[str, Any]:
    store = store or social_store.get_store()
    view = _account_block(platform, store)
    view["posts_detail"] = _post_block(platform, store)
    view["next_scheduled"] = _next_scheduled(platform, store)
    return view


def content_view(store: social_store.SocialStore | None = None) -> dict[str, Any]:
    store = store or social_store.get_store()
    counts = store.counts()
    return {
        "ideas": counts.get(social_store.IDEA, 0),
        "drafts": sum(counts.get(s, 0) for s in (
            social_store.RESEARCHING, social_store.SCRIPTING,
            social_store.MEDIA_GENERATING)),
        "ready_for_review": counts.get(social_store.READY_FOR_REVIEW, 0),
        "approved": counts.get(social_store.APPROVED, 0),
        "scheduled": counts.get(social_store.SCHEDULED, 0),
        "published": counts.get(social_store.PUBLISHED, 0),
        "failed": counts.get(social_store.FAILED, 0),
        "awaiting_approval": [
            {"content_id": c["content_id"], "title": c.get("title", ""),
             "platform": c.get("platform", "")}
            for c in store.list_content(status=social_store.READY_FOR_REVIEW,
                                        limit=10)],
    }


def leads_view(store: social_store.SocialStore | None = None) -> dict[str, Any]:
    store = store or social_store.get_store()
    everything = store.leads(limit=200)
    by_status: dict[str, int] = {}
    for lead in everything:
        status = lead.get("status", "NEW")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "counts": by_status,
        "new": [
            {"lead_id": row["lead_id"], "platform": row.get("platform", ""),
             "username": row.get("username", ""),
             "service": row.get("requested_service", ""),
             "risk": row.get("risk_level", "")}
            for row in store.leads(status=social_store.LEAD_NEW, limit=10)],
    }


def overview(store: social_store.SocialStore | None = None) -> dict[str, Any]:
    """The whole dashboard. Safe to call when nothing is configured."""
    store = store or social_store.get_store()
    return {
        "generated_at": time.time(),
        "system": {
            "enabled": control.social_enabled(),
            "dry_run": control.dry_run(),
            "mode": control.mode(),
            "kill_switch": control.kill_switch_active(),
        },
        "instagram": platform_view(social_store.INSTAGRAM, store),
        "tiktok": platform_view(social_store.TIKTOK, store),
        "content": content_view(store),
        "leads": leads_view(store),
    }


def _platform_sentence(view: dict[str, Any]) -> list[str]:
    name = view["platform"].title()
    if not view["enabled"]:
        return [f"{name}: disabled."]
    if not view["available"]:
        return [f"{name}: {UNAVAILABLE} -- {view['reason']}"]

    handle = view["username"] or "unknown"
    lines = [f"{name} (@{handle}):",
             f"  followers: {view.get('followers', UNAVAILABLE)}"]
    if "followers_gained" in view:
        lines.append(f"  change since last snapshot: {view['followers_gained']:+d}")

    detail = view["posts_detail"]
    latest = detail.get("latest")
    if latest:
        lines.append(f"  latest post: {latest['title']} ({latest['views']} views)")
    best = detail.get("best")
    if best:
        lines.append(f"  best post: {best['title']} ({best['views']} views)")
    elif detail.get("reason"):
        lines.append(f"  best post: {UNAVAILABLE} -- {detail['reason']}")

    upcoming = view.get("next_scheduled")
    if upcoming:
        when = time.strftime("%a %d %b %H:%M",
                             time.localtime(upcoming["scheduled_for"]))
        lines.append(f"  next scheduled: {upcoming['title']} at {when}")
    return lines


def spoken_summary(store: social_store.SocialStore | None = None) -> str:
    """What ZENO says when asked how its socials are doing."""
    data = overview(store)
    system = data["system"]
    lines: list[str] = []

    if not system["enabled"]:
        lines.append("Social system: OFF (SOCIAL_ENABLED is false).")
    if system["kill_switch"]:
        lines.append("KILL SWITCH ENGAGED -- all social automation is stopped.")
    if system["dry_run"]:
        lines.append("Dry run is ON: content is prepared but never sent.")
    lines.append(f"Mode: {system['mode']}.")
    lines.append("")

    lines.extend(_platform_sentence(data["instagram"]))
    lines.append("")
    lines.extend(_platform_sentence(data["tiktok"]))
    lines.append("")

    content = data["content"]
    lines.append(f"Content: {content['ideas']} ideas, {content['drafts']} in "
                 f"progress, {content['ready_for_review']} awaiting approval, "
                 f"{content['scheduled']} scheduled, "
                 f"{content['published']} published.")

    leads = data["leads"]
    if leads["new"]:
        lines.append(f"Leads: {len(leads['new'])} new potential client(s).")
        for lead in leads["new"][:3]:
            lines.append(f"  @{lead['username']} on {lead['platform']}: "
                         f"{lead['service']} (risk {lead['risk']})")
    else:
        lines.append("Leads: none new.")
    return "\n".join(lines)
