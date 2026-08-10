"""Semantic retrieval that filters by metadata before it scores anything."""

from __future__ import annotations

from reyes_agent.knowledge.vector import index
from reyes_agent.knowledge.vector.index import Document, Hit

__all__ = ["index", "Document", "Hit", "add", "search", "remove", "collections", "status"]

add = index.add
search = index.search
remove = index.remove
collections = index.collections
status = index.status
