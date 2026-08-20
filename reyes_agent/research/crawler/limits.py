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

import ipaddress
import socket
import threading
import time
import urllib.parse
import urllib.robotparser
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any

MAX_PAGES = 12
MAX_DEPTH = 2
MAX_BYTES_PER_PAGE = 2_000_000
TOTAL_DEADLINE_S = 90.0
PER_REQUEST_TIMEOUT_S = 12.0
ROBOTS_TIMEOUT_S = 5.0
MAX_ROBOTS_BYTES = 256_000

# One request per host at a time, and a gap between them. Politeness, and
# also the difference between research and a denial of service.
PER_HOST_GAP_S = 1.0

USER_AGENT = "ZENO-Research/1.0 (personal assistant; respects robots.txt)"

# Never fetched, whatever a link says.
DENY_SCHEMES = frozenset({"file", "ftp", "javascript", "data", "mailto", "about"})

# Research is for ordinary public web pages. Ports used by internal consoles,
# development servers and metadata services are not part of that surface.
_PUBLIC_WEB_PORTS = frozenset({80, 443})
_LOCAL_HOST_SUFFIXES = (".local", ".internal", ".localhost")

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


def _target(url: str) -> tuple[bool, str, tuple[str, ...]]:
    """Resolve a URL and prove that every address is publicly routable.

    String-prefix checks are not a security boundary: they miss 172.16/12,
    carrier-grade NAT, unusual integer IPv4 forms and hostnames resolving to
    loopback/private addresses.  ``ipaddress.is_global`` handles the complete
    IPv4/IPv6 classification and ``getaddrinfo`` covers DNS and unusual numeric
    spellings.  A mixed public/private answer is rejected in full.
    """
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
    except (TypeError, ValueError):
        return False, "unparseable target", ()
    if not host:
        return False, "target has no host", ()
    if parsed.username is not None or parsed.password is not None:
        return False, "credentials are not allowed in research URLs", ()
    if host == "localhost" or host.endswith(_LOCAL_HOST_SUFFIXES):
        return False, "local hostnames are never fetched", ()
    if port not in _PUBLIC_WEB_PORTS:
        return False, "only standard public web ports 80 and 443 are fetched", ()

    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return False, "target could not be resolved safely", ()
    addresses = tuple(sorted({str(answer[4][0]).split("%", 1)[0] for answer in answers}))
    if not addresses:
        return False, "target resolved to no address", ()
    try:
        unsafe = [address for address in addresses
                  if not ipaddress.ip_address(address).is_global]
    except ValueError:
        return False, "target returned an invalid address", ()
    if unsafe:
        return False, "target resolves to local, private, reserved or non-global space", addresses
    return True, "target resolves only to public addresses", addresses


def is_private(url: str) -> bool:
    """Compatibility predicate: unresolvable/unsafe targets are private."""
    safe, _why, _addresses = _target(url)
    return not safe


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
        try:
            import requests

            # RobotFileParser.read() follows redirects internally. That turns
            # an otherwise safe public target into a second, unvalidated SSRF
            # fetch. Download the small file ourselves with redirects off.
            with closing(requests.get(
                    root + "/robots.txt", timeout=ROBOTS_TIMEOUT_S, stream=True,
                    allow_redirects=False,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})) as response:
                if response.status_code != 200:
                    parser = None
                else:
                    chunks, total = [], 0
                    for chunk in response.iter_content(16_384):
                        remaining = MAX_ROBOTS_BYTES - total
                        if remaining <= 0:
                            break
                        piece = chunk[:remaining]
                        chunks.append(piece)
                        total += len(piece)
                        if len(piece) < len(chunk) or total >= MAX_ROBOTS_BYTES:
                            break
                    text = b"".join(chunks).decode(
                        response.encoding or "utf-8", errors="replace")
                    parser = urllib.robotparser.RobotFileParser()
                    parser.set_url(root + "/robots.txt")
                    parser.parse(text.splitlines())
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
    public, why, _addresses = _target(url)
    if not public:
        return False, why

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
