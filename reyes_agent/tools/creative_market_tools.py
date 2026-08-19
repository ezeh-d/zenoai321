"""Finding where to sell what ZENO made, and drafting the listing.

The honest boundary, in code: these tools RESEARCH venues and DRAFT a listing.
They do not create accounts, upload, set payout methods, take payment, or
complete a sale. Selling is the owner's action, tracked through the paid-work
flow. ZENO prepares; the owner sells.
"""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="find_where_to_sell",
    description=(
        "Suggest real marketplaces to sell creative work (art, animation, "
        "prints, merch), WITH each one's AI-content policy -- because many "
        "sites restrict or ban AI-generated work and getting it wrong gets "
        "the account banned. Use for 'where can I sell this', 'how do I "
        "monetize my animations'. Research and guidance only; it does not "
        "list or sell anything."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "What the work is: animation, art, prints, stickers, merch, bundle."},
            "ai_friendly_only": {"type": "boolean", "description": "Only venues that allow AI work outright."},
        },
    },
)
def find_where_to_sell(kind: str = "", ai_friendly_only: bool = False) -> str:
    from reyes_agent.creative import market

    venues = market.find_venues(kind, allow_only=bool(ai_friendly_only))
    if not venues:
        return "No venues matched. Try a broader kind like 'art' or 'animation'."
    lines = []
    for v in venues:
        best = ", ".join(v.best_for[:3])
        lines.append(f"- {v.name} — {v.ai_policy}\n    best for: {best}\n    {v.url} · {v.note}")
    header = (f"Where to sell {kind or 'creative work'} "
              f"({'AI-friendly only' if ai_friendly_only else 'with AI-policy notes'}):")
    return (f"{header}\n" + "\n".join(lines) +
            "\n\nThese policies change -- confirm the current one before you list. "
            "When you've picked one, I'll draft the listing; you create the account "
            "and post it (I don't handle payments or accounts).")


@register(
    name="draft_listing",
    description=(
        "Draft a marketplace listing for a piece of creative work: title, "
        "description, tags, a suggested price range, and an AI disclosure "
        "line. Use after find_where_to_sell, for 'write the listing for "
        "this'. A draft for the owner to edit and post -- it does not publish "
        "or sell."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Working title, or leave blank to derive from the concept."},
            "concept": {"type": "string", "description": "What the work depicts / is about."},
            "kind": {"type": "string", "description": "animation, art, illustration, print, sticker, wallpaper, bundle."},
            "currency": {"type": "string", "description": "Currency for the price range. Default USD."},
        },
        "required": ["concept"],
    },
)
def draft_listing(concept: str, title: str = "", kind: str = "art",
                  currency: str = "USD") -> str:
    from reyes_agent.creative import market

    listing = market.draft_listing(title, concept, kind, currency=(currency or "USD"))
    d = listing.as_dict()
    tags = ", ".join(d["tags"])
    return (f"Listing draft (yours to edit before posting):\n\n"
            f"Title: {d['title']}\n"
            f"Price: {d['price_range']}  (a starting anchor, not a valuation)\n"
            f"Tags: {tags}\n\n"
            f"Description:\n{d['description']}\n\n"
            f"Required disclosure: {d['ai_disclosure']}\n\n"
            "I can't post or price it for real -- you list it and set the final "
            "price. Want me to record it in your paid-work tracker so we follow "
            "the sale?")
