# search.py

from __future__ import annotations

import re
import webbrowser
from urllib.parse import quote_plus


SEARCH_ENGINES: dict[str, str] = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "github": "https://github.com/search?q={query}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={query}",
    "stackoverflow": "https://stackoverflow.com/search?q={query}",
    "stack overflow": "https://stackoverflow.com/search?q={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "amazon": "https://www.amazon.com/s?k={query}",
    "maps": "https://www.google.com/maps/search/{query}",
    "google maps": "https://www.google.com/maps/search/{query}",
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}",
}


WEBSITES: dict[str, str] = {
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "docs": "https://docs.google.com",
    "google sheets": "https://sheets.google.com",
    "sheets": "https://sheets.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "ollama": "https://ollama.com",
    "github": "https://github.com",
    "youtube": "https://www.youtube.com",
    "wikipedia": "https://www.wikipedia.org",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "reddit": "https://www.reddit.com",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com",
    "whatsapp": "https://web.whatsapp.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "x": "https://x.com",
    "twitter": "https://x.com",
}


SEARCH_ALIASES: dict[str, str] = {
    "stack": "stackoverflow",
    "stack overflow": "stackoverflow",
    "wiki": "wikipedia",
    "yt": "youtube",
    "google maps": "maps",
    "map": "maps",
    "duck duck go": "duckduckgo",
    "ddg": "duckduckgo",
}


def normalize_provider(provider: str) -> str:
    """
    Convert aliases into a supported provider name.
    """

    clean_provider = provider.lower().strip()

    return SEARCH_ALIASES.get(
        clean_provider,
        clean_provider,
    )


def open_url(url: str) -> bool:
    """
    Open a URL in the default web browser.
    """

    try:
        return bool(webbrowser.open(url))

    except Exception:
        return False


def search_web(
    provider: str,
    query: str,
) -> str:
    """
    Search using a supported provider.

    Examples:
        search_web("google", "Python tutorials")
        search_web("youtube", "build a desktop assistant")
        search_web("github", "ollama python")
    """

    provider = normalize_provider(provider)
    query = query.strip()

    if not query:
        return "Please tell me what to search for."

    template = SEARCH_ENGINES.get(provider)

    if template is None:
        supported = ", ".join(sorted(SEARCH_ENGINES))

        return (
            f"Search provider '{provider}' is not supported. "
            f"Supported providers: {supported}."
        )

    encoded_query = quote_plus(query)
    url = template.format(query=encoded_query)

    if not open_url(url):
        return f"I could not open {provider.title()}."

    return f"Searching {provider.title()} for '{query}'."


def google_search(query: str) -> str:
    return search_web("google", query)


def youtube_search(query: str) -> str:
    return search_web("youtube", query)


def github_search(query: str) -> str:
    return search_web("github", query)


def wikipedia_search(query: str) -> str:
    return search_web("wikipedia", query)


def stackoverflow_search(query: str) -> str:
    return search_web("stackoverflow", query)


def reddit_search(query: str) -> str:
    return search_web("reddit", query)


def linkedin_search(query: str) -> str:
    return search_web("linkedin", query)


def amazon_search(query: str) -> str:
    return search_web("amazon", query)


def maps_search(query: str) -> str:
    return search_web("maps", query)


def open_website(name: str) -> str:
    """
    Open a supported website without performing a search.

    Examples:
        open_website("gmail")
        open_website("chatgpt")
        open_website("google drive")
    """

    clean_name = name.lower().strip()
    url = WEBSITES.get(clean_name)

    if url is None:
        supported = ", ".join(sorted(WEBSITES))

        return (
            f"Website '{name}' is not supported. "
            f"Supported websites: {supported}."
        )

    if not open_url(url):
        return f"I could not open {name.title()}."

    return f"Opening {name.title()}."


def parse_search_command(message: str) -> tuple[str, str] | None:
    """
    Parse natural-language search commands.

    Supported examples:
        search Google for Python
        search YouTube for Flask tutorials
        search GitHub for REYES AI
        look up Alan Turing on Wikipedia
        find restaurants on Google Maps
    """

    clean_message = message.strip()

    patterns = [
        r"^search\s+(.+?)\s+for\s+(.+)$",
        r"^find\s+(.+?)\s+on\s+(.+)$",
        r"^look\s+up\s+(.+?)\s+on\s+(.+)$",
    ]

    for index, pattern in enumerate(patterns):
        match = re.match(
            pattern,
            clean_message,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        if index == 0:
            provider = match.group(1).strip()
            query = match.group(2).strip()
        else:
            query = match.group(1).strip()
            provider = match.group(2).strip()

        return normalize_provider(provider), query

    return None


def parse_open_website_command(message: str) -> str | None:
    """
    Parse commands such as:
        open Gmail
        open ChatGPT
        open Google Drive
    """

    match = re.fullmatch(
        r"(?:please\s+)?open\s+(.+)",
        message.strip(),
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    website_name = match.group(1).strip().lower()

    if website_name not in WEBSITES:
        return None

    return website_name


def handle_search_command(message: str) -> str | None:
    """
    Main search handler for router.py or brain.py.

    Returns None when the command is not a search or supported website request.
    """

    parsed_search = parse_search_command(message)

    if parsed_search is not None:
        provider, query = parsed_search
        return search_web(provider, query)

    website_name = parse_open_website_command(message)

    if website_name is not None:
        return open_website(website_name)

    lower = message.lower().strip()

    if lower.startswith("google "):
        return google_search(message[7:].strip())

    if lower.startswith("youtube "):
        return youtube_search(message[8:].strip())

    if lower.startswith("github "):
        return github_search(message[7:].strip())

    if lower.startswith("wikipedia "):
        return wikipedia_search(message[10:].strip())

    if lower.startswith("reddit "):
        return reddit_search(message[7:].strip())

    if lower.startswith("maps "):
        return maps_search(message[5:].strip())

    return None


def run_test_mode() -> None:
    """
    Run search.py directly for testing.
    """

    print("=" * 50)
    print("REYES SEARCH TEST")
    print("=" * 50)
    print("Examples:")
    print("search Google for Python")
    print("search YouTube for Python tutorials")
    print("search GitHub for Ollama")
    print("open Gmail")
    print("open ChatGPT")
    print("Type 'exit' to stop.")
    print("=" * 50)

    while True:
        try:
            command = input("\nYou: ").strip()

            if not command:
                continue

            if command.lower() in {
                "exit",
                "quit",
            }:
                print("Search test stopped.")
                return

            response = handle_search_command(command)

            if response is None:
                response = "That is not a supported search command."

            print(f"REYES: {response}")

        except KeyboardInterrupt:
            print("\nSearch test stopped.")
            return


if __name__ == "__main__":
    run_test_mode()