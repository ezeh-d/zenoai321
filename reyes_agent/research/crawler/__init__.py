"""Bounded, robots-respecting extraction with citations."""

from __future__ import annotations

from reyes_agent.research.crawler import limits          # no intra-package deps
from reyes_agent.research.crawler import manager         # needs limits
from reyes_agent.research.crawler.manager import Extract

__all__ = ["limits", "manager", "Extract", "research", "fetch", "dedupe", "rank", "status"]

research = manager.research
fetch = manager.fetch
dedupe = manager.dedupe
rank = manager.rank
status = manager.status
