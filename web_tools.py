# web_tools.py

from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus


# ==========================================================
# REYES WEB TOOLS
# ==========================================================

WEBSITES = {

    # AI
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "lovable": "https://lovable.dev",
    "openai": "https://openai.com",
    "anthropic": "https://anthropic.com",
    "ollama": "https://ollama.com",

    # Search
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",

    # Development
    "github": "https://github.com",
    "stackoverflow": "https://stackoverflow.com",

    # Communication
    "gmail": "https://mail.google.com",
    "slack": "https://app.slack.com",
    "discord": "https://discord.com/app",

    # Social
    "facebook": "https://facebook.com",
    "instagram": "https://instagram.com",
    "linkedin": "https://linkedin.com",
    "reddit": "https://reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",

    # Entertainment
    "spotify": "https://spotify.com",
    "netflix": "https://netflix.com",

    # Shopping
    "amazon": "https://amazon.com",

}


# ==========================================================
# OPEN WEBSITE
# ==========================================================

def open_website(site: str) -> str:

    site = site.strip().lower()

    if not site:
        return "Please tell me which website to open."

    if site in WEBSITES:
        webbrowser.open(WEBSITES[site])
        return f"Opening {site.title()}."

    # Allow custom domains
    if "." in site:

        if not site.startswith(("http://", "https://")):
            site = "https://" + site

        webbrowser.open(site)
        return f"Opening {site}."

    return f"I don't know the website '{site}'."


# ==========================================================
# GOOGLE SEARCH
# ==========================================================

def google_search(query: str) -> str:

    query = query.strip()

    if not query:
        return "Please tell me what to search for."

    url = (
        "https://www.google.com/search?q="
        + quote_plus(query)
    )

    webbrowser.open(url)

    return f"Searching Google for '{query}'."


# ==========================================================
# YOUTUBE SEARCH
# ==========================================================

def youtube_search(query: str) -> str:

    query = query.strip()

    if not query:
        return "Please tell me what to search for."

    url = (
        "https://www.youtube.com/results?search_query="
        + quote_plus(query)
    )

    webbrowser.open(url)

    return f"Searching YouTube for '{query}'."


# ==========================================================
# GITHUB SEARCH
# ==========================================================

def github_search(query: str) -> str:

    query = query.strip()

    if not query:
        return "Please tell me what to search for."

    url = (
        "https://github.com/search?q="
        + quote_plus(query)
    )

    webbrowser.open(url)

    return f"Searching GitHub for '{query}'."


# ==========================================================
# STACK OVERFLOW SEARCH
# ==========================================================

def stackoverflow_search(query: str) -> str:

    query = query.strip()

    if not query:
        return "Please tell me what to search for."

    url = (
        "https://stackoverflow.com/search?q="
        + quote_plus(query)
    )

    webbrowser.open(url)

    return f"Searching Stack Overflow for '{query}'."


# ==========================================================
# WIKIPEDIA SEARCH
# ==========================================================

def wikipedia_search(query: str) -> str:

    query = query.strip()

    if not query:
        return "Please tell me what to search for."

    url = (
        "https://en.wikipedia.org/wiki/Special:Search?search="
        + quote_plus(query)
    )

    webbrowser.open(url)

    return f"Searching Wikipedia for '{query}'."


# ==========================================================
# LOVABLE WEBSITE CREATOR
# ==========================================================

def open_lovable() -> str:
    """
    Open Lovable AI.
    """

    webbrowser.open("https://lovable.dev")

    return "Opening Lovable AI."


def create_website_with_lovable(prompt: str) -> str:
    """
    Future integration.

    Later REYES will automatically open Lovable,
    insert your prompt,
    and create websites.
    """

    webbrowser.open("https://lovable.dev")

    return (
        "Lovable has been opened.\n\n"
        "Future versions of REYES will automatically "
        "fill your website prompt and generate the project."
    )


# ==========================================================
# OPEN SEARCH
# ==========================================================

def search(query: str) -> str:
    """
    Default search engine.
    """

    return google_search(query)