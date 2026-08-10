"""Reading the web for evidence, as distinct from interacting with it.

`browser/` clicks and fills forms. This extracts what pages say and keeps
the URL attached, because a research answer without provenance cannot be
told apart from a guess.
"""

from __future__ import annotations

from reyes_agent.research import crawler

__all__ = ["crawler", "research", "status"]

research = crawler.research
status = crawler.status
