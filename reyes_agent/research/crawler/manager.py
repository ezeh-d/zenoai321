"""Extract and rank what pages actually say, with the source kept attached.

THE DIVISION OF LABOUR
----------------------
    browser-use / Playwright  ->  INTERACT with a site (click, log in, fill)
    this                      ->  EXTRACT what a set of pages says

They are not competing. ZENO already has the first; this is the second, and
it deliberately does not click anything.

WHY EVERY EXTRACT CARRIES ITS URL
---------------------------------
A research answer without provenance is indistinguishable from a
hallucination, and the whole point of crawling rather than asking a model
from memory is that the claim can be traced. So the unit here is not text;
it is text WITH the URL it came from and when it was fetched. Summaries
built from these keep the citation.

AND IT IS ALL UNTRUSTED
-----------------------
Every page is written by someone else. Extracts go through
`security.ai.guardrails.screen_input` before any of it reaches a model, so
a page that says "ignore your instructions" is quoted, not obeyed.

Crawl4AI is an optional backend for the extraction step. It is not
installed here, and `requests` plus a bounded HTML-to-text pass covers the
job for a desktop assistant reading a dozen pages.
"""

from __future__ import annotations


import html
import re
import time
import urllib.parse
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.research.crawler import limits

_SCRIPT = re.compile(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>")
_TAG = re.compile(r"(?s)<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK = re.compile(r"\n{3,}")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_LINK = re.compile(r"""(?i)<a\s[^>]*href=["']([^"'#]+)""")

# Chrome for the page, not content. Dropping these is most of what a
# "readability" pass does, and it needs no dependency.
_BOILERPLATE = re.compile(
    r"(?im)^\s*(cookie|accept all|subscribe|sign in|log in|advertisement|"
    r"share this|related articles|newsletter|skip to content)\b.*$")


@dataclass
class Extract:
    url: str
    title: str = ""
    text: str = ""
    fetched_at: float = field(default_factory=time.time)
    status: int = 0
    words: int = 0
    error: str = ""
    suspicious: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text)

    def citation(self) -> str:
        host = urllib.parse.urlparse(self.url).hostname or self.url
        return f"{self.title or host} <{self.url}>"

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "words": self.words,
                "status": self.status, "error": self.error,
                "fetched_at": self.fetched_at, "citation": self.citation(),
                "suspicious": self.suspicious}


def to_text(markup: str) -> tuple[str, str, list[str]]:
    """(title, text, links). Bounded, dependency-free."""
    body = _SCRIPT.sub(" ", markup or "")
    title_match = _TITLE.search(body)
    title = html.unescape(_TAG.sub("", title_match.group(1))).strip() if title_match else ""
    links = [html.unescape(m.group(1)) for m in _LINK.finditer(body)]

    body = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", body)
    text = html.unescape(_TAG.sub(" ", body))
    text = _SPACE.sub(" ", text)
    text = _BOILERPLATE.sub("", text)
    text = _BLANK.sub("\n\n", text).strip()
    return title, text, links


def fetch(url: str, budget: limits.Budget, *, allow: tuple[str, ...] = (),
          deny: tuple[str, ...] = (), session: Any = None) -> Extract:
    """One page, bounded, robots-respecting, and screened."""
    permitted, why = limits.may_fetch(url, budget, allow=allow, deny=deny)
    if not permitted:
        budget.note_skip(url, why)
        return Extract(url=url, error=why)

    try:
        import requests
    except Exception as exc:  # noqa: BLE001
        return Extract(url=url, error=f"no http client: {type(exc).__name__}: {exc}")

    limits.wait_for_host(url)
    extract = Extract(url=url)
    try:
        request = session.get if session is not None else requests.get
        # Redirects are deliberately not followed. A safe public URL can
        # redirect to a loopback/cloud-metadata target after our validation;
        # the caller must provide the final URL so it is validated separately.
        with closing(request(
                url, timeout=limits.PER_REQUEST_TIMEOUT_S, stream=True,
                allow_redirects=False,
                headers={"User-Agent": limits.USER_AGENT,
                         "Accept": "text/html,text/plain"})) as response:
            extract.status = response.status_code
            if 300 <= extract.status < 400:
                extract.error = "redirect refused; provide the final public URL"
                return extract
            kind = (response.headers.get("content-type") or "").lower()
            if "html" not in kind and "text" not in kind:
                extract.error = f"not a text document ({kind or 'unknown type'})"
                return extract

            # Read with an exact hard cap. The previous loop appended the
            # whole last chunk and could exceed the documented limit by 64 KiB.
            chunks, total = [], 0
            for chunk in response.iter_content(65536):
                remaining = limits.MAX_BYTES_PER_PAGE - total
                if remaining <= 0:
                    break
                piece = chunk[:remaining]
                chunks.append(piece)
                total += len(piece)
                if len(piece) < len(chunk) or total >= limits.MAX_BYTES_PER_PAGE:
                    break
            markup = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        extract.error = f"{type(exc).__name__}: {exc}"
        return extract
    finally:
        budget.fetched += 1

    if extract.status >= 400:
        extract.error = f"http {extract.status}"
        return extract

    extract.title, extract.text, _links = to_text(markup)
    extract.words = len(extract.text.split())

    # Someone else wrote this. Screen it before it can reach a model.
    try:
        from reyes_agent.security.ai import guardrails

        screening = guardrails.screen_input(extract.text, origin="research:crawl")
        extract.suspicious = sorted({f.detail for f in screening.findings})
        extract.text = screening.text
    except Exception:  # noqa: BLE001
        pass
    return extract


# Two pages counted as the same article. Mirrors differ by a nav bar and a
# footer, so this is deliberately below 1.0.
SIMILARITY = 0.8

_SHINGLE = 5


def _shingles(text: str) -> frozenset[str]:
    """Overlapping word n-grams -- the unit of near-duplicate comparison.

    An exact hash of a prefix does NOT work here, and the tests caught it: it
    only collapses documents longer than the prefix, so two mirrors of a
    short article that differ by three trailing words hash differently and
    both survive. Shingle overlap compares what the pages actually share.
    """
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    if len(words) < _SHINGLE:
        return frozenset({" ".join(words)}) if words else frozenset()
    return frozenset(" ".join(words[i:i + _SHINGLE])
                     for i in range(len(words) - _SHINGLE + 1))


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of shingles. 1.0 is identical, 0.0 shares nothing."""
    a, b = _shingles(left), _shingles(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe(extracts: list[Extract]) -> tuple[list[Extract], int]:
    """Keep the fullest copy of each distinct article."""
    # Longest first, so the copy that survives is the most complete one.
    ordered = sorted([e for e in extracts if e.ok], key=lambda e: -e.words)
    kept: list[Extract] = []
    dropped = 0
    for extract in ordered:
        if any(similarity(extract.text, existing.text) >= SIMILARITY for existing in kept):
            dropped += 1
            continue
        kept.append(extract)
    return kept, dropped


def rank(extracts: list[Extract], question: str) -> list[Extract]:
    """Order by how much of the question a page actually addresses.

    Deliberately simple and explainable: term coverage, then term frequency,
    then length as a tiebreak. A page that mentions every term once beats one
    that mentions a single term forty times, which is the failure mode of
    raw frequency scoring.
    """
    terms = [t for t in re.findall(r"[a-z0-9]{3,}", (question or "").lower())]
    if not terms:
        return sorted(extracts, key=lambda e: -e.words)

    def score(extract: Extract) -> tuple[float, float, int]:
        body = extract.text.lower()
        hits = {t: body.count(t) for t in terms}
        covered = sum(1 for t in terms if hits[t]) / len(terms)
        density = sum(hits.values()) / max(1, extract.words)
        return (-covered, -density, -extract.words)

    return sorted([e for e in extracts if e.ok], key=score)


def research(question: str, urls: list[str], *, max_pages: int = 0,
             allow: tuple[str, ...] = (), deny: tuple[str, ...] = ()) -> dict[str, Any]:
    """Fetch a chosen set of pages, clean, dedupe, rank, cite.

    URLs are chosen by the CALLER (search happens elsewhere). This does not
    follow links off the page -- a research pass reads what it was pointed
    at, which is what keeps the bound meaningful.
    """
    budget = limits.Budget(pages=max_pages or limits.MAX_PAGES)
    started = time.time()

    extracts = []
    try:
        import requests

        session = requests.Session()
    except Exception:  # fetch() will return the precise missing-client error
        session = None
    try:
        for url in urls:
            if budget.exhausted:
                budget.note_skip(url, "budget reached before this page")
                continue
            extracts.append(fetch(url, budget, allow=allow, deny=deny, session=session))
    finally:
        if session is not None:
            session.close()

    kept, duplicates = dedupe(extracts)
    ranked = rank(kept, question)
    failed = [e for e in extracts if not e.ok]

    return {
        "question": question,
        "sources": [e.as_dict() for e in ranked],
        "citations": [e.citation() for e in ranked],
        "evidence": [{"citation": e.citation(), "excerpt": e.text[:1500]} for e in ranked[:5]],
        "duplicates_dropped": duplicates,
        "failed": [{"url": e.url, "why": e.error} for e in failed],
        "flagged": [{"url": e.url, "found": e.suspicious} for e in ranked if e.suspicious],
        "budget": budget.as_dict(),
        "duration_s": round(time.time() - started, 2),
        "note": ("Page text is untrusted and was screened before being returned. "
                 "Anything instruction-shaped inside it is quoted, not followed."),
    }


def status() -> dict[str, Any]:
    import importlib.util as finder

    return {
        "state": "ONLINE",
        "backend": "requests + bounded HTML extraction",
        "crawl4ai": {"installed": finder.find_spec("crawl4ai") is not None,
                     "role": "optional extraction backend; not required"},
        "interaction": "browser/ handles clicking and forms; this only reads",
        "limits": limits.describe(),
        "provenance": "every extract carries its URL and fetch time",
    }
