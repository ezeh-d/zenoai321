"""Event-driven microphone selection with hysteresis and safe fallback."""

from __future__ import annotations

import threading
import time


class MicrophoneSelector:
    def __init__(self, *, promote_score: float = 65.0, demote_score: float = 35.0) -> None:
        self.promote_score = promote_score
        self.demote_score = demote_score
        self._lock = threading.RLock()
        self._selected: str | None = None
        self._candidate_since: dict[str, float] = {}
        self._poor_since: dict[str, float] = {}
        self._reason = "local WebView2 is the default"

    def observe(self, source: str, score: float, *, connected: bool = True,
                now: float | None = None) -> tuple[str | None, bool]:
        now = now or time.monotonic()
        changed = False
        with self._lock:
            if not connected:
                self._candidate_since.pop(source, None)
                self._poor_since.pop(source, None)
                if self._selected == source:
                    self._selected = None
                    self._reason = "remote stream disconnected; restored local WebView2"
                    changed = True
                return self._selected, changed

            if self._selected is None:
                if score >= self.promote_score:
                    started = self._candidate_since.setdefault(source, now)
                    if now - started >= 0.12:
                        self._selected = source
                        self._reason = f"remote stream stable at quality {score:.1f}"
                        self._poor_since.pop(source, None)
                        changed = True
                else:
                    self._candidate_since.pop(source, None)
            elif self._selected == source:
                if score < self.demote_score:
                    started = self._poor_since.setdefault(source, now)
                    if now - started >= 2.0:
                        self._selected = None
                        self._reason = f"remote quality stayed below {self.demote_score:.0f}; restored local"
                        changed = True
                else:
                    self._poor_since.pop(source, None)
        return self._selected, changed

    def status(self) -> dict:
        with self._lock:
            return {"selected": self._selected or "local-webview2", "reason": self._reason,
                    "promote_score": self.promote_score, "demote_score": self.demote_score}
