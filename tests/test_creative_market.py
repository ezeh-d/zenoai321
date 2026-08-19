"""Finding where to sell creative work, and drafting the listing.

The point of these is the AI-policy honesty (many marketplaces restrict AI
work) and the boundary: research and drafts, never a transaction.
"""

from __future__ import annotations

import os

os.environ.setdefault("ZENO_ENV", "test")

from reyes_agent.creative import market  # noqa: E402
from reyes_agent.tools import TOOLS  # noqa: E402


def test_every_venue_declares_an_ai_policy():
    for v in market.VENUES:
        assert v.ai_policy in (market.ALLOWS, market.ALLOWS_DISCLOSED,
                               market.RESTRICTED, market.BANS)


def test_ai_friendly_filter_excludes_restricted_venues():
    friendly = market.find_venues("art", allow_only=True)
    assert friendly
    assert all(v.ai_policy in (market.ALLOWS, market.ALLOWS_DISCLOSED) for v in friendly)


def test_find_venues_matches_by_kind():
    animation = market.find_venues("animation")
    assert any("Gumroad" == v.name for v in animation)


def test_draft_listing_has_title_price_tags_and_disclosure():
    listing = market.draft_listing("", "a glowing AI orb", "animation")
    d = listing.as_dict()
    assert d["title"]
    assert "USD" in d["price_range"]
    assert d["tags"]
    assert "AI" in d["ai_disclosure"]


def test_the_price_band_follows_the_kind():
    cheap = market.draft_listing("s", "x", "sticker")
    dear = market.draft_listing("a", "x", "animation")
    assert cheap.price_high <= dear.price_high


# --- tools ---------------------------------------------------------------
def test_market_tools_are_registered_and_routed():
    from reyes_agent.routing import capability

    for name in ("find_where_to_sell", "draft_listing"):
        assert name in TOOLS
    for msg in ("where can I sell my animations", "how do I monetize my art",
                "draft a listing for this"):
        assert "creative" in capability.tools_for(msg).capabilities, msg


def test_selling_stocks_is_not_a_creative_request():
    """Financial 'sell', not art. Must not route to the creative tools."""
    from reyes_agent.routing import capability
    assert "creative" not in capability.tools_for("sell my Tesla stocks").capabilities


def test_find_where_to_sell_names_ai_policies():
    out = TOOLS["find_where_to_sell"].func(kind="animation")
    assert "AI" in out
    assert "policies change" in out or "confirm the current" in out


def test_the_tools_state_they_do_not_transact():
    """The boundary must be visible to the owner, not just in the code."""
    sell = TOOLS["find_where_to_sell"].func(kind="art")
    draft = TOOLS["draft_listing"].func(concept="a dragon", kind="art")
    assert "don't handle payment" in sell.lower() or "you create the account" in sell.lower()
    assert "can't post" in draft.lower() or "you list it" in draft.lower()
