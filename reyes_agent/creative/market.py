"""Where to sell what ZENO made -- and a listing to sell it with.

THE PART THAT ACTUALLY HELPS
----------------------------
Anyone can say "sell it on Etsy". The useful thing is knowing that a lot of
marketplaces RESTRICT or BAN AI-generated work, or require it to be disclosed
-- and getting that wrong gets an account banned and the work removed. So this
carries each marketplace's AI-content stance, so ZENO points the owner
somewhere the work is actually allowed.

HONEST ABOUT ONE THING
----------------------
These policies change, and this is ZENO's best knowledge, not a live feed.
Every entry says so, and ZENO should confirm the current policy before the
owner lists. Better to say "check this" than to state a stale rule as fact.

WHAT THIS DOES NOT DO
---------------------
It finds venues and drafts a listing. It does not create an account, upload,
set a payout method, take payment, or complete a sale -- those stay with the
owner, through the paid-work flow. Nothing here transacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# AI-content stance, as of ZENO's knowledge. Always to be re-checked live.
ALLOWS = "allows AI work"
ALLOWS_DISCLOSED = "allows AI work if disclosed / labelled"
RESTRICTED = "restricts or reviews AI work -- check first"
BANS = "bans AI-generated work"


@dataclass(frozen=True)
class Venue:
    name: str
    best_for: tuple[str, ...]
    ai_policy: str
    url: str
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "best_for": list(self.best_for),
                "ai_policy": self.ai_policy, "url": self.url, "note": self.note}


# Curated, honest, and dated by nature. Ordered roughly AI-friendliest first.
VENUES: tuple[Venue, ...] = (
    Venue("Gumroad", ("digital art", "animation", "downloads", "bundles"),
          ALLOWS, "https://gumroad.com",
          "Owner-friendly for digital downloads; you keep control of pricing."),
    Venue("Ko-fi", ("commissions", "digital downloads", "support"),
          ALLOWS, "https://ko-fi.com",
          "Good for commissions and tips; low friction, no listing review."),
    Venue("Payhip", ("digital downloads", "art packs"),
          ALLOWS, "https://payhip.com",
          "Simple digital storefront; handles VAT."),
    Venue("DeviantArt", ("illustration", "prints", "community"),
          ALLOWS_DISCLOSED, "https://www.deviantart.com",
          "AI work must be tagged as AI-generated; there is an active community."),
    Venue("Adobe Stock", ("stock art", "illustration"),
          ALLOWS_DISCLOSED, "https://stock.adobe.com/contributor",
          "Accepts AI with disclosure; no real-person or trademarked prompts."),
    Venue("Etsy", ("prints", "digital downloads", "merch"),
          RESTRICTED, "https://www.etsy.com/sell",
          "Allows AI but tightening; must disclose and add real value. Verify current policy."),
    Venue("Redbubble / TeePublic", ("print-on-demand", "merch", "stickers"),
          RESTRICTED, "https://www.redbubble.com",
          "AI content is scrutinised and sometimes removed; read their current terms."),
    Venue("ArtStation", ("portfolio", "prints", "industry visibility"),
          RESTRICTED, "https://www.artstation.com",
          "Supports a 'NoAI' tag; AI work has restrictions. Good for a portfolio regardless."),
    Venue("YouTube / TikTok / Instagram", ("animation", "short video", "audience"),
          ALLOWS_DISCLOSED, "https://www.youtube.com",
          "Not a store -- monetise through audience/creator funds; label AI/synthetic media."),
)


def find_venues(kind: str = "", *, allow_only: bool = False) -> list[Venue]:
    """Venues suited to a kind of work ('animation', 'art', 'prints', ...).

    `allow_only` keeps only venues that permit AI work outright, for when the
    owner wants the least-friction, lowest-ban-risk options.
    """
    kind = str(kind or "").strip().lower()
    out = []
    for v in VENUES:
        if allow_only and v.ai_policy not in (ALLOWS, ALLOWS_DISCLOSED):
            continue
        if not kind or any(kind in tag or tag in kind for tag in v.best_for):
            out.append(v)
    return out or [v for v in VENUES if not allow_only or v.ai_policy in (ALLOWS, ALLOWS_DISCLOSED)]


@dataclass
class Listing:
    title: str
    description: str
    tags: tuple[str, ...]
    price_low: float
    price_high: float
    currency: str = "USD"
    ai_disclosure: str = "Created with AI assistance by ZENO."

    def as_dict(self) -> dict[str, Any]:
        return {"title": self.title, "description": self.description,
                "tags": list(self.tags),
                "price_range": f"{self.currency} {self.price_low:.0f}-{self.price_high:.0f}",
                "ai_disclosure": self.ai_disclosure}


# Rough starting bands by kind. A suggestion to anchor on, not a valuation.
_PRICE_BANDS: dict[str, tuple[float, float]] = {
    "animation": (15, 60), "video": (15, 60), "reel": (10, 40),
    "art": (5, 30), "illustration": (8, 40), "print": (12, 45),
    "sticker": (2, 6), "wallpaper": (2, 8), "bundle": (20, 80),
}


def draft_listing(title: str, concept: str, kind: str = "art",
                  *, currency: str = "USD") -> Listing:
    """A listing draft to start from -- the owner edits and posts it."""
    kind_l = str(kind or "art").strip().lower()
    low, high = next((band for key, band in _PRICE_BANDS.items() if key in kind_l),
                     (5, 30))
    concept = str(concept or "").strip()
    title = str(title or concept or "Original artwork").strip()[:120]

    description = (
        f"{title} — an original {kind_l} {concept and 'of ' + concept}. "
        "Created by ZENO. High-resolution digital download; personal and "
        "small-commercial use as licensed at checkout. "
        "Disclosure: made with AI assistance."
    ).replace("  ", " ").strip()

    words = [w.lower() for w in (concept + " " + kind_l).split() if len(w) > 2]
    tags = tuple(dict.fromkeys(words + [kind_l, "digital art", "original", "download"]))[:12]
    return Listing(title=title, description=description, tags=tags,
                   price_low=low, price_high=high, currency=currency)
