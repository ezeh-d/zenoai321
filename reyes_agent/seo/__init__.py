"""Real SEO artefacts -- and no promises about rankings.

Produces sitemap.xml, robots.txt, meta/Open Graph tags and JSON-LD as
actual files. Refuses fabricated ratings, prices and claims, refuses a
'Disallow: /' on production, and reports measurable facts rather than
predicted positions.
"""

from __future__ import annotations

from reyes_agent.seo import engine
from reyes_agent.seo.engine import Page

__all__ = ["engine", "Page", "build_sitemap", "build_robots", "head_tags",
           "json_ld", "write_site_files", "audit", "report", "status"]

build_sitemap = engine.build_sitemap
build_robots = engine.build_robots
head_tags = engine.head_tags
json_ld = engine.json_ld
write_site_files = engine.write_site_files
audit = engine.audit
report = engine.report
status = engine.status
