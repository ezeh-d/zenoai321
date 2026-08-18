"""Captions and hashtags.

WHY HASHTAGS ARE NOT A CONSTANT LIST
------------------------------------
The brief forbids reusing one massive tag list, and the platforms agree:
identical tag blocks across posts is a spam signal. So tags are derived from
the post's own topic, then mixed by reach tier -- a few broad, several
mid-sized, several specific -- because a post that only carries broad tags
competes with everything and a post that only carries narrow ones reaches
nobody.

WHAT THIS MODULE REFUSES TO CLAIM
---------------------------------
`recommend_from_history` will say a tag group performed better ONLY when
there are enough posts to say it. Below that it returns "insufficient data"
and the caller must not dress that up. Three posts is not a trend, and the
brief is explicit: do not claim causation from weak data.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from reyes_agent.social import store as social_store

# Platform limits, checked rather than assumed.
LIMITS = {
    social_store.INSTAGRAM: {"caption": 2200, "hashtags": 30},
    social_store.TIKTOK: {"caption": 2200, "hashtags": 30},
}

# Broad reach, high competition. At most two per post.
_BROAD = ("ai", "tech", "coding", "programming", "artificialintelligence")

# Mid reach. The working middle of the mix.
_MID_BY_TOPIC: dict[str, tuple[str, ...]] = {
    "voice": ("voiceai", "speechrecognition", "voiceassistant", "texttospeech"),
    "browser": ("automation", "webautomation", "browserautomation", "playwright"),
    "agent": ("aiagents", "agenticai", "multiagent", "autonomousagents"),
    "memory": ("aimemory", "vectordatabase", "rag", "llm"),
    "speed": ("performance", "optimization", "latency", "benchmarking"),
    "test": ("softwaretesting", "qa", "unittesting", "cicd"),
    "security": ("cybersecurity", "appsec", "securecoding", "infosec"),
    "desktop": ("windowsautomation", "desktopapp", "productivity", "workflow"),
    "python": ("python", "pythonprogramming", "backend", "softwareengineering"),
    "build": ("buildinpublic", "indiehacker", "sideproject", "devlog"),
}

# Narrow and specific. Low competition, high intent.
_NARROW = ("zeno", "zenoai", "buildinpublic", "aiassistant", "devjourney")


def _topic_keys(text: str) -> list[str]:
    low = (text or "").casefold()
    keys = [key for key in _MID_BY_TOPIC if key in low]
    # Synonyms, so "microphone" finds the voice group.
    synonyms = {
        "voice": ("mic", "microphone", "audio", "speech", "stt", "tts", "whisper"),
        "browser": ("chrome", "playwright", "scrape", "web page", "navigate"),
        "agent": ("agents", "delegate", "specialist", "orchestrat"),
        "memory": ("remember", "recall", "embedding", "knowledge"),
        "speed": ("fast", "slow", "latency", "ms", "seconds", "perf"),
        "test": ("pytest", "suite", "soak", "stress", "coverage"),
        "security": ("auth", "token", "secure", "injection", "passkey"),
        "desktop": ("windows", "app", "gui", "orb"),
        "python": ("py", "fastapi", "sqlite"),
        "build": ("commit", "shipped", "built", "refactor"),
    }
    for key, words in synonyms.items():
        if key not in keys and any(word in low for word in words):
            keys.append(key)
    return keys


@dataclass
class CaptionSet:
    short: str
    medium: str
    long: str

    def for_platform(self, platform: str) -> str:
        # TikTok captions are read in a scrolling feed; Instagram's are read
        # after the image has already stopped someone. Different jobs.
        return self.short if platform == social_store.TIKTOK else self.medium

    def as_dict(self) -> dict[str, str]:
        return {"short": self.short, "medium": self.medium, "long": self.long}


def write_captions(item: dict[str, Any]) -> CaptionSet:
    """Three lengths, so the pipeline can pick per platform."""
    title = str(item.get("title") or "").strip()
    hook = str(item.get("hook") or "").strip()
    evidence = item.get("evidence") or []
    measurement = next((e.get("summary", "") for e in evidence
                        if isinstance(e, dict) and e.get("kind") == "measurement"), "")

    short = (hook or title)[:150].rstrip()
    if not short.endswith((".", "!", "?")):
        short += "."

    medium_parts = [hook or title]
    if measurement:
        medium_parts.append(f"The measurement: {measurement}")
    medium_parts.append("Follow the build.")
    medium = "\n\n".join(part for part in medium_parts if part)[:600]

    long_parts = [hook or title]
    if item.get("script"):
        body = re.sub(r"\[[A-Z ]+\]\s*", "", str(item["script"]))
        long_parts.append(body.strip())
    if measurement:
        long_parts.append(f"Measured: {measurement}")
    long_parts.append(
        "ZENO is an AI assistant I am building. Everything posted here comes "
        "from its actual development.")
    long_parts.append("Follow the build.")
    long = "\n\n".join(part for part in long_parts if part)[:2000]

    return CaptionSet(short=short, medium=medium, long=long)


def generate_hashtags(item: dict[str, Any], *, platform: str,
                      count: int = 12) -> list[str]:
    """Topic-derived tags, mixed by reach tier. Never a fixed block."""
    text = " ".join(str(item.get(key) or "") for key in
                    ("title", "hook", "topic", "category", "script"))
    keys = _topic_keys(text)

    mid: list[str] = []
    for key in keys:
        mid.extend(_MID_BY_TOPIC[key])

    # Deterministic but content-dependent rotation, so two posts on the same
    # day do not carry an identical block.
    seed = sum(ord(char) for char in text[:200]) if text else 0

    def rotate(values: tuple[str, ...] | list[str], take: int) -> list[str]:
        items = list(dict.fromkeys(values))
        if not items:
            return []
        offset = seed % len(items)
        rotated = items[offset:] + items[:offset]
        return rotated[:take]

    chosen: list[str] = []
    chosen.extend(rotate(_BROAD, 2))
    chosen.extend(rotate(mid, max(0, count - 6)))
    chosen.extend(rotate(_NARROW, 4))

    # De-duplicate, keep order, respect the platform limit.
    limit = min(count, LIMITS.get(platform, {}).get("hashtags", 30))
    unique = list(dict.fromkeys(tag.lower().lstrip("#") for tag in chosen if tag))
    return [f"#{tag}" for tag in unique[:limit]]


@dataclass
class TagRecommendation:
    confident: bool
    detail: str
    groups: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {"confident": self.confident, "detail": self.detail,
                "groups": self.groups}


# Below this many published posts carrying analytics, any comparison is noise.
MIN_POSTS_FOR_TAG_CLAIM = 8


def recommend_from_history(store: social_store.SocialStore | None = None,
                           *, platform: str | None = None) -> TagRecommendation:
    """Which tag groups correlate with reach -- and only when that is knowable."""
    active = store or social_store.get_store()
    posts = [p for p in active.list_content(status=social_store.PUBLISHED, limit=200)
             if not platform or p["platform"] == platform]

    scored: dict[str, list[float]] = defaultdict(list)
    measured = 0
    for post in posts:
        latest = active.latest_analytics(post["content_id"])
        if not latest:
            continue
        views = float(latest["metrics"].get("views")
                      or latest["metrics"].get("impressions") or 0)
        if views <= 0:
            continue
        measured += 1
        for tag in post.get("hashtags") or []:
            scored[str(tag).lower()].append(views)

    if measured < MIN_POSTS_FOR_TAG_CLAIM:
        return TagRecommendation(
            confident=False,
            detail=(f"{measured} published post(s) carry view data. At least "
                    f"{MIN_POSTS_FOR_TAG_CLAIM} are needed before a hashtag "
                    f"comparison means anything, so no recommendation is made."),
            groups={})

    averages = {tag: statistics.fmean(values)
                for tag, values in scored.items() if len(values) >= 3}
    if not averages:
        return TagRecommendation(
            confident=False,
            detail="no hashtag appears on enough posts to compare.",
            groups={})

    ranked = dict(sorted(averages.items(), key=lambda kv: kv[1], reverse=True)[:10])
    return TagRecommendation(
        confident=True,
        detail=(f"across {measured} measured posts, these tags appear on the "
                f"highest-reach content. Correlation only -- the topic and the "
                f"tags move together, and this cannot separate them."),
        groups={tag: round(value, 1) for tag, value in ranked.items()})
