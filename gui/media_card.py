"""Live media mini-card for the PyQt desktop HUD.

Mirrors the web mini-card (static/media_panel.js) on the native surface: album
art, title/artist/source, a progress bar and transport controls, updating in
real time. It rides the SAME engine -- reyes_agent.media -- so the desktop HUD
and the web UI show identical truth.

Threading: the media engine's background poller and event bus run off the Qt
thread; a Qt Signal marshals each state push onto the UI thread, so widgets are
only ever touched there. Transport commands run on a short-lived thread so a
click never blocks the UI while Windows applies it.

Degrades: if the media engine can't be imported, the card simply stays hidden
and the rest of the HUD is unaffected.
"""

from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

try:
    from gui.theme import (CARD_BACKGROUND, PRIMARY, PRIMARY_SOFT, TEXT_MUTED,
                           TEXT_PRIMARY, TEXT_SECONDARY, FONT_FAMILY)
except Exception:  # noqa: BLE001 -- keep import-safe outside the packaged app
    CARD_BACKGROUND, PRIMARY, PRIMARY_SOFT = "#0B1E2A", "#22D3EE", "#7FEFFF"
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED = "#E6FBFF", "#8FBECB", "#4E7B88"
    FONT_FAMILY = "Segoe UI"


class MediaCard(QFrame):
    """Always-on media card; hides itself when nothing is playing."""

    _state_ready = Signal(object)   # marshals a state dict onto the UI thread

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unsub = None
        self._last_key = ""
        self._pos = 0.0
        self._dur = 0.0
        self._playing = False
        self._at = 0.0
        self._watching = False

        self.setObjectName("MediaCard")
        self._build()
        self._state_ready.connect(self._apply_state)

        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._tick)
        self._progress_timer.start(500)

        self.hide()                 # nothing to show until a state arrives
        self._connect_engine()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        self.setStyleSheet(f"""
            QFrame#MediaCard {{
                background: {CARD_BACKGROUND};
                border: 1px solid {PRIMARY};
                border-radius: 12px;
            }}
            QLabel {{ background: transparent; font-family: "{FONT_FAMILY}"; }}
            QPushButton {{
                background: transparent; border: none; color: {TEXT_PRIMARY};
                font-size: 16px; padding: 4px 8px; border-radius: 8px;
            }}
            QPushButton:hover {{ background: {PRIMARY_SOFT}22; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(11)
        self._art = QLabel()
        self._art.setFixedSize(54, 54)
        self._art.setStyleSheet(
            f"border-radius:8px; border:1px solid {PRIMARY}; background:{PRIMARY}18;")
        self._art.setScaledContents(True)
        row.addWidget(self._art)

        meta = QVBoxLayout()
        meta.setSpacing(1)
        self._title = QLabel("--")
        self._title.setStyleSheet(
            f"color:{TEXT_PRIMARY}; font-size:13px; font-weight:600;")
        self._artist = QLabel("")
        self._artist.setStyleSheet(f"color:{TEXT_SECONDARY}; font-size:11px;")
        self._source = QLabel("")
        self._source.setStyleSheet(
            f"color:{TEXT_MUTED}; font-size:9px; letter-spacing:1px;")
        for w in (self._title, self._artist, self._source):
            w.setWordWrap(False)
            meta.addWidget(w)
        row.addLayout(meta, 1)
        outer.addLayout(row)

        # slim progress bar (a plain filled frame, so it matches the web card)
        track = QFrame()
        track.setFixedHeight(3)
        track.setStyleSheet(f"background:{PRIMARY}30; border-radius:2px;")
        self._fill = QFrame(track)
        self._fill.setStyleSheet(f"background:{PRIMARY}; border-radius:2px;")
        self._fill.setGeometry(0, 0, 0, 3)
        self._track = track
        outer.addWidget(track)

        ctrls = QHBoxLayout()
        ctrls.addStretch(1)
        self._prev = QPushButton("⏮")
        self._play = QPushButton("⏯")
        self._next = QPushButton("⏭")
        self._prev.clicked.connect(lambda: self._cmd("previous"))
        self._play.clicked.connect(lambda: self._cmd("toggle"))
        self._next.clicked.connect(lambda: self._cmd("next"))
        for b in (self._prev, self._play, self._next):
            ctrls.addWidget(b)
        ctrls.addStretch(1)
        outer.addLayout(ctrls)

    # -- engine wiring -----------------------------------------------------
    def _connect_engine(self) -> None:
        try:
            from reyes_agent.media import get_media_manager
            from reyes_agent.media.events import get_event_bus

            mgr = get_media_manager()
            mgr.add_live_watcher()
            self._watching = True
            self._unsub = get_event_bus().subscribe(self._on_event)
            # push an initial state without blocking the UI thread
            threading.Thread(target=self._emit_current, args=(mgr,),
                             daemon=True).start()
        except Exception:  # noqa: BLE001 -- media engine optional
            pass

    def _emit_current(self, mgr) -> None:
        try:
            self._state_ready.emit(mgr.state(with_art=True).to_dict())
        except Exception:  # noqa: BLE001
            pass

    def _on_event(self, evt) -> None:
        # runs on the poller/bus thread -> only emit; the slot touches widgets
        try:
            if evt.type == "state" and isinstance(evt.payload, dict):
                self._state_ready.emit(evt.payload)
        except Exception:  # noqa: BLE001
            pass

    def _cmd(self, action: str) -> None:
        def run() -> None:
            try:
                from reyes_agent.media import get_media_manager
                get_media_manager().command(action, reference="it")
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=run, daemon=True).start()

    # -- UI-thread updates -------------------------------------------------
    def _apply_state(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        active = payload.get("active")
        if not active or not active.get("title"):
            self.hide()
            return
        self.show()
        self._title.setText(active.get("title", ""))
        self._artist.setText(active.get("artist", ""))
        self._source.setText((active.get("source", "") or "").upper())
        self._play.setText("⏸" if active.get("playing") else "▶")

        key = f"{active.get('app_id')}|{active.get('title')}|{active.get('artist')}"
        if key != self._last_key:
            art = active.get("art_path") or ""
            if art and os.path.exists(art):
                pm = QPixmap(art)
                if not pm.isNull():
                    self._art.setPixmap(pm)
            else:
                self._art.clear()
            self._last_key = key

        self._pos = float(active.get("position_s", 0) or 0)
        self._dur = float(active.get("duration_s", 0) or 0)
        self._playing = bool(active.get("playing"))
        self._at = time.monotonic()
        self._tick()

    def _tick(self) -> None:
        pos = self._pos
        if self._playing:
            pos += time.monotonic() - self._at
        pct = (pos / self._dur) if self._dur > 0 else 0.0
        pct = max(0.0, min(1.0, pct))
        w = int(self._track.width() * pct)
        self._fill.setGeometry(0, 0, w, 3)

    # -- lifecycle ---------------------------------------------------------
    def stop(self) -> None:
        """Release the poller watcher and unsubscribe (idempotent)."""
        try:
            if self._unsub:
                self._unsub()
                self._unsub = None
            if self._watching:
                from reyes_agent.media import get_media_manager
                get_media_manager().remove_live_watcher()
                self._watching = False
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        self.stop()
        super().closeEvent(event)
