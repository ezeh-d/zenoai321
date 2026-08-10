"""The bounds. Separated out because they are the safety property.

"Do not crawl the entire internet" is easy to agree with and easy to breach
by accident: one recursive function with no depth counter and a news site
will happily serve ZENO ten thousand pages. So every limit lives here, in
one place, where it can be read and audited without following the crawl
logic.

`robots.txt` is honoured because ZENO is a browser acting for a person but
at machine speed, and a site's stated preference costs one cheap request to
respect. A disallowed page is skipped and SAID to be skipped, so a thin
result never looks like an empty internet.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any

MAX_PAGES = 12
MAX_DEPTH = 2
MAX_BYTES_PER_PAGE = 2_000_000
TOTAL_DEADLINE_S = 90.0
PER_REQUEST_TIMEOUT_S = 12.0

# One request per host at a time, and a gap between them. Politeness, and
# also the difference between research and a denial of service.
PER_HOST_GAP_S = 1.0

USER_AGENT = "ZENO-Research/1.0 (personal assistant; respects robots.txt)"

# Never fetched, whatever a link says.
DENY_SCHEMES = frozenset({"file", "ftp", "javascript", "data", "mailto", "about"})

# Hosts that are never crawled: local and private network space. A research
# crawler that can be steered onto 127.0.0.1 is an SSRF tool.
_PRIVATE_HOST_MARKERS = ("localhost", "127.", "0.0.0.0", "10.", "192.168.",
                         "169.254.", "::1", "[::1]", ".local", ".internal")

_robots_cache: dict[str, Any] = {}
_last_request: dict[str, float] = {}
_lock = threading.Lock()


@dataclass
class Budget:
    """What is left. Passed through the crawl rather than recomputed."""

    pages: int = MAX_PAGES
    depth: int = MAX_DEPTH
    started: float = field(default_factory=time.time)
    fetched: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return (time.time() - self.started) > TOTAL_DEADLINE_S

    @property
    def exhausted(self) -> bool:
        return self.fetched >= self.pages or self.expired

    def note_skip(self, url: str, why: str) -> None:
        self.skipped.append(f"{url} -- {why}")
        del self.skipped[:-40]

    def as_dict(self) -> dict[str, Any]:
        return {"pages_allowed": self.pages, "pages_fetched": self.fetched,
                "max_depth": self.depth, "elapsed_s": round(time.time() - self.started, 1),
                "expired": self.expired, "skipped": self.skipped[-12:]}


def is_private(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return True
    if not host:
        return True
    return any(host == m or host.startswith(m) or host.endswith(m)
               for m in _PRIVATE_HOST_MARKERS)


def allowed_scheme(url: str) -> bool:
    try:
        scheme = (urllib.parse.urlparse(url).scheme or "").lower()
    except ValueError:
        return False
    return scheme in {"http", "https"}


def robots_allows(url: str) -> tuple[bool, str]:
    """Ask robots.txt. A site that cannot be asked is given the benefit."""
    try:
        parts = urllib.parse.urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
    except ValueError:
        return False, "unparseable url"

    with _lock:
        parser = _robots_cache.get(root)
    if parser is None:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(root + "/robots.txt")
        try:
            parser.read()
        except Exception:  # noqa: BLE001 -- no robots.txt is not a refusal
            parser = None
        with _lock:
            _robots_cache[root] = parser or False

    if parser in (None, False):
        return True, "no robots.txt to consult"
    try:
        ok = parser.can_fetch(USER_AGENT, url)
    except Exception:  # noqa: BLE001
        return True, "robots.txt could not be interpreted"
    return ok, ("robots.txt permits it" if ok else "robots.txt disallows this path")


def may_fetch(url: str, budget: Budget, *, allow: tuple[str, ...] = (),
              deny: tuple[str, ...] = ()) -> tuple[bool, str]:
    """Every reason a URL might not be fetched, in one call."""
    if budget.exhausted:
        return False, ("page budget or time limit reached"
                       if not budget.expired else "crawl deadline reached")
    if not allowed_scheme(url):
        return False, "only http and https are fetched"
    if is_private(url):
        return False, "refusing to crawl local or private network addresses"

    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if deny and any(d.lower() in host for d in deny):
        return False, "host is on the denylist"
    if allow and not any(a.lower() in host for a in allow):
        return False, "host is not on the allowlist"

    ok, why = robots_allows(url)
    if not ok:
        return False, why
    return True, "allowed"


def wait_for_host(url: str) -> None:
    """Keep one request per host per PER_HOST_GAP_S."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    with _lock:
        previous = _last_request.get(host, 0.0)
        gap = time.time() - previous
        if gap < PER_HOST_GAP_S:
            delay = PER_HOST_GAP_S - gap
        else:
            delay = 0.0
        _last_request[host] = time.time() + delay
    if delay > 0:
        time.sleep(delay)


def describe() -> dict[str, Any]:
    return {"max_pages": MAX_PAGES, "max_depth": MAX_DEPTH,
            "max_bytes_per_page": MAX_BYTES_PER_PAGE,
            "total_deadline_s": TOTAL_DEADLINE_S,
            "per_request_timeout_s": PER_REQUEST_TIMEOUT_S,
            "per_host_gap_s": PER_HOST_GAP_S,
            "user_agent": USER_AGENT,
            "robots": "consulted and honoured; a disallowed page is skipped and reported",
            "private_networks": "never fetched -- a steerable crawler is an SSRF tool"}
