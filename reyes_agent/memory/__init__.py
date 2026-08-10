"""Policy-driven memory facade for ZENO.

Living Memory remains the durable source of truth.  Mem0 is a lazy semantic
index which may be unavailable without costing ZENO its memory or a reply.
"""

from reyes_agent.memory.manager import MemoryManager, get_memory_manager

__all__ = ["MemoryManager", "get_memory_manager"]
