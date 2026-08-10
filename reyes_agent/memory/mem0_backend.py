"""Lazy, failure-isolated adapter for Mem0 OSS or Platform.

No Mem0 import happens at startup.  Local OSS is preferred; the hosted client
is used only when the owner explicitly selects it and supplies a key.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from typing import Any

from reyes_agent.memory.privacy import redact


class Mem0Backend:
    def __init__(self) -> None:
        self.enabled = os.environ.get("ZENO_MEM0_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.mode = os.environ.get("ZENO_MEM0_MODE", "local").strip().lower()
        self.user_id = os.environ.get("ZENO_MEM0_USER_ID", "divine").strip() or "divine"
        self._client: Any = None
        self._lock = threading.RLock()
        self._state = "STANDBY" if self.enabled else "DISABLED"
        self._error = ""
        self._last_latency_ms = 0.0

    def installed(self) -> bool:
        try:
            return importlib.util.find_spec("mem0") is not None
        except (ImportError, ValueError):
            return False

    def _get(self) -> Any:
        if not self.enabled:
            raise RuntimeError("Mem0 is disabled; Living Memory is active.")
        with self._lock:
            if self._client is not None:
                return self._client
            if not self.installed():
                self._state = "UNAVAILABLE"
                raise RuntimeError("mem0ai is not installed")
            started = time.perf_counter()
            try:
                if self.mode == "platform":
                    from mem0 import MemoryClient

                    key = os.environ.get("MEM0_API_KEY", "").strip()
                    if not key:
                        raise RuntimeError("MEM0_API_KEY is required for platform mode")
                    self._client = MemoryClient(api_key=key)
                else:
                    from mem0 import Memory

                    self._client = Memory()
                self._state = "CONNECTED"
                self._error = ""
                return self._client
            except Exception as exc:
                self._state = "FAILED"
                self._error = f"{type(exc).__name__}: {redact(exc, limit=240)}"
                raise
            finally:
                self._last_latency_ms = (time.perf_counter() - started) * 1000

    def search(self, query: str, *, category: str = "", limit: int = 5) -> list[dict[str, Any]]:
        client = self._get()
        started = time.perf_counter()
        try:
            filters: dict[str, Any] = {"user_id": self.user_id}
            result = client.search(str(query), filters=filters, top_k=max(1, min(10, int(limit))))
            rows = result.get("results", result) if isinstance(result, dict) else result
            output = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                metadata = row.get("metadata") or {}
                if category and metadata.get("category") not in {"", category}:
                    continue
                output.append({
                    "id": str(row.get("id", "")),
                    "memory": redact(row.get("memory", row.get("text", ""))),
                    "score": row.get("score"),
                    "category": metadata.get("category", ""),
                    "source": "mem0",
                })
            self._state = "CONNECTED"
            self._error = ""
            return output[:limit]
        except Exception as exc:
            self._state = "DEGRADED"
            self._error = f"{type(exc).__name__}: {redact(exc, limit=240)}"
            raise
        finally:
            self._last_latency_ms = (time.perf_counter() - started) * 1000

    def add(self, text: str, *, category: str, source: str, memory_id: str = "") -> Any:
        client = self._get()
        started = time.perf_counter()
        try:
            metadata = {"category": category, "source": source, "living_memory_id": memory_id}
            messages = [{"role": "user", "content": redact(text, limit=4000)}]
            return client.add(messages, user_id=self.user_id, metadata=metadata)
        except TypeError:
            return client.add(messages, user_id=self.user_id)
        except Exception as exc:
            self._state = "DEGRADED"
            self._error = f"{type(exc).__name__}: {redact(exc, limit=240)}"
            raise
        finally:
            self._last_latency_ms = (time.perf_counter() - started) * 1000

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "installed": self.installed(),
            "mode": self.mode,
            "state": self._state,
            "error": self._error,
            "last_latency_ms": round(self._last_latency_ms, 1),
            "fallback": "Living Memory",
        }
