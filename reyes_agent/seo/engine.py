"""Real SEO files, and no promises about rankings.

WHAT THIS PRODUCES
------------------
An actual `sitemap.xml`, an actual `robots.txt`, actual meta and Open Graph
tags, actual JSON-LD. Files on disk that a crawler can fetch -- not a report
saying they were considered.

THE TWO RULES THAT SHAPE EVERYTHING
-----------------------------------
1. **Metadata must describe the page.** A description is a promise to the
   person deciding whether to click. Inventing an offer, a price, a rating
   or a certification to improve a snippet is not optimisation, it is a lie
   with a bounce rate. `describe_page()` builds from real page content and
   refuses to emit a description it had to invent.

2. **Nothing here can promise a ranking.** Not "#1 on Google", not "instant
   indexing". `report()` returns what is measurable: the file exists, the
   URL is canonical, the sitemap validates, the page is crawlable. Anything
   past that belongs to Google and to time.

WHAT GETS EXCLUDED, AND WHY IT MATTERS MOST
-------------------------------------------
The commonest real damage from an automated SEO tool is a sitemap listing
admin pages, staging URLs and noindex routes -- or a robots.txt that
disallows everything on production. So exclusion is explicit, checked, and
`validate_robots()` refuses a rule that would hide the whole site.
"""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

# Google truncates around here. Not a hard limit -- a legibility one.
TITLE_MAX = 60
DESCRIPTION_MIN = 70
DESCRIPTION_MAX = 158

# Routes that must never appear in a public sitemap.
_PRIVATE = re.compile(
    r"(^|/)(admin|dashboard|account|settings|login|logout|signin|signup|auth|"
    r"reset|checkout|cart|api|internal|preview|draft|staging|test|_next|"
    r"wp-admin)(/|$)", re.I)

# Claims a generated description must never make up.
_FABRICATION = re.compile(
    r"(?i)\b(\d+\s*%\s*(off|discount)|free (shipping|trial)|award[- ]winning|"
    r"#1|no\.?\s*1|best in|certified|guaranteed|\d+\+? (customers|clients|users)|"
    r"rated \d(\.\d)?|since \d{4})\b")


@dataclass
class Page:
    url: str
    title: str = ""
    description: str = ""
    canonical: str = ""
    indexable: bool = True
    changed_at: float = 0.0
    priority: float = 0.5
    headings: list[str] = field(default_factory=list)
    body_text: str = ""

    @property
    def private(self) -> bool:
        return bool(_PRIVATE.search(urlparse(self.url).path or ""))

    @property
    def in_sitemap(self) -> bool:
        """Canonical, indexable, public and self-referencing."""
        if not self.indexable or self.private:
            return False
        return (not self.canonical) or self.canonical.rstrip("/") == self.url.rstrip("/")

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "description": self.description,
                "canonical": self.canonical or self.url, "indexable": self.indexable,
                "private": self.private, "in_sitemap": self.in_sitemap}


# --- metadata -----------------------------------------------------------

def describe_page(page: Page) -> tuple[str, list[str]]:
    """A description built from what the page really says. (text, problems)."""
    problems: list[str] = []
    text = (page.description or "").strip()

    if not text:
        # Build from the page's own first substantial sentences.
        body = re.sub(r"\s+", " ", page.body_text or "").strip()
        sentences = re.split(r"(?<=[.!?])\s+", body)
        built = ""
        for sentence in sentences:
            if len(built) + len(sentence) + 1 > DESCRIPTION_MAX:
                break
            built = f"{built} {sentence}".strip()
        text = built

    if not text:
        problems.append("there is not enough page content to describe it honestly; "
                        "I will not invent one")
        return "", problems

    invented = _FABRICATION.search(text)
    if invented and invented.group(0).lower() not in (page.body_text or "").lower():
        problems.append(f"the description claims {invented.group(0)!r}, which is not "
                        "on the page -- removed")
        text = _FABRICATION.sub("", text).strip(" ,.-")

    if len(text) > DESCRIPTION_MAX:
        cut = text[:DESCRIPTION_MAX].rsplit(" ", 1)[0]
        text = cut.rstrip(" ,.-") + "..."
    if len(text) < DESCRIPTION_MIN:
        problems.append(f"description is only {len(text)} characters; under "
                        f"{DESCRIPTION_MIN} usually reads as thin")
    return text, problems


def head_tags(page: Page, *, site_name: str = "", image: str = "") -> str:
    """The actual tags for the page head. Escaped, canonical, honest."""
    description, _problems = describe_page(page)
    canonical = page.canonical or page.url
    escape = html.escape

    lines = [f'<title>{escape(page.title)}</title>']
    if description:
        lines.append(f'<meta name="description" content="{escape(description)}">')
    lines.append(f'<link rel="canonical" href="{escape(canonical)}">')
    lines.append('<meta name="robots" content="'
                 + ("index, follow" if page.indexable else "noindex, nofollow")
                 + '">')
    lines.append(f'<meta property="og:title" content="{escape(page.title)}">')
    if description:
        lines.append(f'<meta property="og:description" content="{escape(description)}">')
    lines.append(f'<meta property="og:url" content="{escape(canonical)}">')
    lines.append('<meta property="og:type" content="website">')
    if site_name:
        lines.append(f'<meta property="og:site_name" content="{escape(site_name)}">')
    if image:
        lines.append(f'<meta property="og:image" content="{escape(image)}">')
    lines.append('<meta name="twitter:card" content="'
                 + ("summary_large_image" if image else "summary") + '">')
    return "\n".join(lines)


# --- sitemap ------------------------------------------------------------

def build_sitemap(pages: list[Page], *, base_url: str = "") -> tuple[str, dict[str, Any]]:
    """A sitemap containing ONLY canonical, indexable, public URLs."""
    included, excluded = [], []
    for page in pages:
        (included if page.in_sitemap else excluded).append(page)

    root = ET.Element("urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
    for page in included:
        node = ET.SubElement(root, "url")
        ET.SubElement(node, "loc").text = urljoin(base_url, page.canonical or page.url)
        if page.changed_at:
            stamp = datetime.fromtimestamp(page.changed_at, tz=timezone.utc)
            ET.SubElement(node, "lastmod").text = stamp.strftime("%Y-%m-%d")
        ET.SubElement(node, "priority").text = f"{min(1.0, max(0.0, page.priority)):.1f}"

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           + ET.tostring(root, encoding="unicode"))
    report = {
        "included": len(included),
        "excluded": [{"url": p.url,
                      "why": ("private route" if p.private else
                              "noindex" if not p.indexable else
                              "canonical points elsewhere")}
                     for p in excluded],
        "note": ("Only canonical, indexable, public URLs. A sitemap listing admin "
                 "pages or noindex routes tells Google you do not know your own site."),
    }
    return xml, report


def build_robots(*, sitemap_url: str = "", disallow: tuple[str, ...] = (),
                 allow_all: bool = True) -> tuple[str, list[str]]:
    """A robots.txt that cannot accidentally hide the whole site."""
    problems: list[str] = []
    rules = ["User-agent: *"]

    blocked = [d for d in disallow if d.strip()]
    if not allow_all:
        problems.append("refusing to write 'Disallow: /' for a production site -- "
                        "that removes it from search entirely")
    for rule in blocked:
        cleaned = rule if rule.startswith("/") else "/" + rule
        if cleaned.strip() == "/":
            problems.append("dropped a 'Disallow: /' rule, which would hide "
                            "everything")
            continue
        rules.append(f"Disallow: {cleaned}")
    if len(rules) == 1:
        rules.append("Allow: /")
    if sitemap_url:
        rules.extend(["", f"Sitemap: {sitemap_url}"])
    return "\n".join(rules) + "\n", problems


def validate_robots(text: str) -> dict[str, Any]:
    """Would this robots.txt hide the site. The check that saves launches."""
    problems, notes = [], []
    lines = [line.strip() for line in (text or "").splitlines()]
    agent_all = False
    for line in lines:
        low = line.lower()
        if low.startswith("user-agent:"):
            agent_all = low.split(":", 1)[1].strip() == "*"
        if agent_all and low.replace(" ", "") == "disallow:/":
            problems.append("'Disallow: /' under 'User-agent: *' hides the entire "
                            "site from every search engine")
    if not any(l.lower().startswith("sitemap:") for l in lines):
        notes.append("no Sitemap: line -- crawlers will still find it, but naming "
                     "it here is free")
    return {"ok": not problems, "problems": problems, "notes": notes}


# --- structured data ----------------------------------------------------

def json_ld(kind: str, data: dict[str, Any]) -> tuple[str, list[str]]:
    """Valid JSON-LD, with fabricated trust signals refused.

    Fake reviews, ratings, prices and availability are the structured-data
    fields that carry real consequences -- they change what Google shows and
    what a person believes before clicking. They are not emitted unless the
    caller supplies them AND says where they came from.
    """
    problems: list[str] = []
    payload: dict[str, Any] = {"@context": "https://schema.org", "@type": kind}

    risky = ("aggregateRating", "review", "offers", "priceRange", "price")
    for key, value in data.items():
        if key in risky and not data.get(f"{key}_source"):
            problems.append(f"dropped '{key}' -- a rating, review or price must come "
                            "from real data, and none was given")
            continue
        if key.endswith("_source"):
            continue
        payload[key] = value

    return json.dumps(payload, indent=2, ensure_ascii=False), problems


# --- writing it out -----------------------------------------------------

def write_site_files(directory: str | Path, pages: list[Page], *,
                     base_url: str, disallow: tuple[str, ...] = ()) -> dict[str, Any]:
    """Write sitemap.xml and robots.txt for real. Returns what happened."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)

    xml, sitemap_report = build_sitemap(pages, base_url=base_url)
    sitemap_path = root / "sitemap.xml"
    sitemap_path.write_text(xml, encoding="utf-8")

    robots, robots_problems = build_robots(
        sitemap_url=urljoin(base_url, "/sitemap.xml"), disallow=disallow)
    robots_path = root / "robots.txt"
    robots_path.write_text(robots, encoding="utf-8")

    return {
        "sitemap": {"path": str(sitemap_path), "bytes": sitemap_path.stat().st_size,
                    **sitemap_report},
        "robots": {"path": str(robots_path), "bytes": robots_path.stat().st_size,
                   "problems": robots_problems,
                   **validate_robots(robots)},
        "wrote": [str(sitemap_path), str(robots_path)],
    }


def audit(pages: list[Page]) -> dict[str, Any]:
    """Everything checkable before deployment."""
    problems: list[str] = []
    titles: dict[str, list[str]] = {}

    for page in pages:
        if not page.title:
            problems.append(f"{page.url}: no title")
        elif len(page.title) > TITLE_MAX:
            problems.append(f"{page.url}: title is {len(page.title)} characters and "
                            f"will be truncated near {TITLE_MAX}")
        titles.setdefault(page.title.strip().lower(), []).append(page.url)

        description, page_problems = describe_page(page)
        problems.extend(f"{page.url}: {p}" for p in page_problems)
        if not description:
            problems.append(f"{page.url}: no usable description")

    for title, urls in titles.items():
        if title and len(urls) > 1:
            problems.append(f"{len(urls)} pages share the title {title!r}: "
                            + ", ".join(urls[:3]))

    return {
        "pages": len(pages),
        "in_sitemap": sum(1 for p in pages if p.in_sitemap),
        "problems": problems,
        "ok": not problems,
        "note": ("These are the things that can be checked before deploying. "
                 "Whether the page ranks is not one of them."),
    }


def report(*, deployed: bool = False, sitemap_written: bool = False,
           sitemap_submitted: bool = False, indexed: int | None = None) -> dict[str, Any]:
    """What is TRUE, stated plainly. Never a promise about rankings."""
    facts = []
    if deployed:
        facts.append("the site is deployed and responding")
    if sitemap_written:
        facts.append("sitemap.xml exists and validates")
    if sitemap_submitted:
        facts.append("the sitemap was accepted by Search Console")
    if indexed is not None:
        facts.append(f"{indexed} page(s) confirmed indexed")
    return {
        "facts": facts,
        "say": ("; ".join(facts) if facts else "nothing verified yet"),
        "never_claimed": ["a ranking position", "instant indexing",
                          "guaranteed visibility"],
        "note": ("Indexing is Google's decision and takes time. Anything beyond "
                 "these facts would be a guess dressed as a result."),
    }


def status() -> dict[str, Any]:
    return {
        "state": "ONLINE",
        "produces": ["sitemap.xml", "robots.txt", "meta + Open Graph", "JSON-LD"],
        "title_max": TITLE_MAX,
        "description_range": [DESCRIPTION_MIN, DESCRIPTION_MAX],
        "refuses": ["fabricated ratings, reviews, prices and availability",
                    "descriptions asserting things not on the page",
                    "'Disallow: /' on a production site",
                    "sitemap entries for private, noindex or non-canonical URLs"],
        "never": "promises a ranking, a position, or instant indexing",
    }
