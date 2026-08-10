"""On-demand Screenpipe/ActivityWatch query adapter with strict privacy."""
from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import urlparse

import requests

from reyes_agent.context.episodic.privacy import allowed, exclusions


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _local_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Episodic providers must use an explicit loopback URL.")
    return value.rstrip("/")


class EpisodicProvider:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_error = ""

    def status(self) -> dict[str, Any]:
        globally_enabled = _enabled("ZENO_EPISODIC_MEMORY_ENABLED")
        screenpipe = globally_enabled and _enabled("ZENO_SCREENPIPE_ENABLED")
        activitywatch = globally_enabled and _enabled("ZENO_ACTIVITYWATCH_ENABLED")
        selected = "screenpipe" if screenpipe else ("activitywatch" if activitywatch else "none")
        return {"enabled": selected != "none", "provider": selected, "state": "STANDBY" if selected != "none" else "DISABLED",
                "global_capture_enabled": globally_enabled,
                "continuous_llm_upload": False, "privacy_exclusions": list(exclusions()), "last_error": self._last_error}

    def query(self, text: str, *, limit: int = 20) -> dict[str, Any]:
        query = " ".join(str(text or "").split())[:500]
        if not query:
            return {"ok": False, "items": [], "reason": "empty query"}
        status = self.status()
        if not status["enabled"]:
            return {"ok": False, "items": [], "reason": "episodic memory is disabled"}
        provider = status["provider"]
        url_var = "ZENO_SCREENPIPE_URL" if provider == "screenpipe" else "ZENO_ACTIVITYWATCH_URL"
        raw_url = os.environ.get(url_var, "").strip()
        if not raw_url:
            return {"ok": False, "items": [], "reason": f"{url_var} is not configured"}
        try:
            base = _local_url(raw_url)
            capped = max(1, min(100, limit))
            with self._lock:
                if provider == "screenpipe":
                    response = requests.get(f"{base}/search", params={"q": query, "limit": capped}, timeout=3)
                    response.raise_for_status()
                    payload = response.json()
                    raw_items = payload.get("data", payload.get("items", payload if isinstance(payload, list) else []))
                else:
                    # ActivityWatch has no generic free-text /search endpoint.
                    # Read bounded recent events from its documented window
                    # bucket API and filter locally.
                    buckets_response = requests.get(f"{base}/api/0/buckets/", timeout=3)
                    buckets_response.raise_for_status()
                    buckets = buckets_response.json()
                    bucket_id = next((key for key, meta in buckets.items()
                                      if "aw-watcher-window" in key.casefold()
                                      or str(meta.get("type", "")).casefold() == "currentwindow"), "")
                    if not bucket_id:
                        return {"ok": False, "provider": provider, "items": [], "reason": "no ActivityWatch window bucket"}
                    response = requests.get(f"{base}/api/0/buckets/{bucket_id}/events",
                                            params={"limit": capped}, timeout=3)
                    response.raise_for_status()
                    raw_items = response.json()
            items = []
            for item in raw_items[:max(1, min(100, limit))]:
                if not isinstance(item, dict):
                    continue
                data = item.get("data") if isinstance(item.get("data"), dict) else item
                title = str(data.get("window_title") or data.get("title") or "")
                app = str(data.get("app_name") or data.get("app") or "")
                if bool(data.get("incognito")):
                    continue
                if allowed(title, app):
                    items.append({"timestamp": item.get("timestamp"), "application": app[:120],
                                  "title": title[:240], "text": str(data.get("text") or data.get("url") or "")[:1000]})
            self._last_error = ""
            return {"ok": True, "provider": provider, "items": items, "excluded_sensitive": len(raw_items) - len(items)}
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"[:300]
            return {"ok": False, "provider": provider, "items": [], "reason": self._last_error}


_provider: EpisodicProvider | None = None
_lock = threading.Lock()


def get_provider() -> EpisodicProvider:
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                _provider = EpisodicProvider()
    return _provider
