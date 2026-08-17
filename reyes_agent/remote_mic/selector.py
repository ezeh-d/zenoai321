"""Event-driven microphone selection with hysteresis and safe fallback."""

from __future__ import annotations

import threading
import time


class MicrophoneSelector:
    def __init__(self, *, promote_score: float = 65.0, demote_score: float = 35.0,
                 hold_s: float = 20.0) -> None:
        self.promote_score = promote_score
        self.demote_score = demote_score
        # How long a selected phone must be SILENT before a poor score is
        # allowed to hand listening back to the laptop.
        self.hold_s = hold_s
        self._last_voice: dict[str, float] = {}
        self._lock = threading.RLock()
        self._selected: str | None = None
        self._candidate_since: dict[str, float] = {}
        self._poor_since: dict[str, float] = {}
        self._reason = "local WebView2 is the default"

    def observe(self, source: str, score: float, *, connected: bool = True,
                voice: bool = False,
                now: float | None = None) -> tuple[str | None, bool]:
        """`voice` says real speech is arriving, not merely a stream."""
        now = now or time.monotonic()
        if voice:
            self._last_voice[source] = now
        changed = False
        with self._lock:
            if not connected:
                self._candidate_since.pop(source, None)
                self._poor_since.pop(source, None)
                self._last_voice.pop(source, None)
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
                    # A CHOSEN PHONE STAYS CHOSEN WHILE IT IS STILL TALKING.
                    #
                    # The owner asked for this in plain terms: when he is
                    # speaking into his phone, ZENO should listen to the
                    # phone. Dropping back to the laptop microphone because a
                    # quality score dipped means his next sentence is picked
                    # up by a machine across the room -- or not at all -- and
                    # from where he is standing that looks like ZENO simply
                    # ignoring him.
                    #
                    # The score measures jitter and packet loss, not whether
                    # a voice is arriving. A phone on a busy hotspot can score
                    # badly and still carry perfectly good speech. So the
                    # fallback now needs BOTH: a poor score AND a stream that
                    # has gone quiet. A live stream is never abandoned.
                    started = self._poor_since.setdefault(source, now)
                    # A source that has NEVER carried voice counts as silent,
                    # not as having just spoken. Defaulting to `now` made
                    # quiet == 0 forever, so a stream that only ever delivered
                    # noise could never be handed back -- the exact opposite
                    # of the protection this is for.
                    last = self._last_voice.get(source)
                    quiet = (now - last) if last is not None else float("inf")
                    if now - started >= 2.0 and quiet >= self.hold_s:
                        self._selected = None
                        self._reason = (
                            f"remote quality below {self.demote_score:.0f} and "
                            f"silent for {quiet:.0f}s; restored local")
                        changed = True
                else:
                    self._poor_since.pop(source, None)
        return self._selected, changed

    def status(self) -> dict:
        with self._lock:
            return {"selected": self._selected or "local-webview2", "reason": self._reason,
                    "promote_score": self.promote_score, "demote_score": self.demote_score,
                    "hold_s": self.hold_s,
                    "rule": ("A phone that is still carrying speech is never "
                             "handed back to the laptop microphone.")}
