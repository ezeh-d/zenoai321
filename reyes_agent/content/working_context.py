"""WorkingContext -- what the file conversation is currently ABOUT.

So "open report.pdf" then "page 6" then "put that table into Excel" all resolve
without the user repeating the filename. Tracks the active file and a bounded
recent-file history, the active location inside it (page/sheet/slide/selection),
and resolves ordinary references ("it", "that one", "the second one", "the
previous file") back to a concrete target.

Bounded, thread-safe, and it never guesses wildly: an unresolvable reference
returns None with a reason, so the engine can ask instead of acting on the
wrong file.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_RECENT_MAX = 12
_SELECTION_MAX = 8

# recent files are stored oldest-first, newest-last, so a positive ordinal
# indexes from the start ("first" = earliest) and -1 is the newest.
_ORDINALS = {
    "first": 0, "1st": 0, "second": 1, "2nd": 1,
    "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4, "last": -1, "latest": -1, "newest": -1,
}
# References that mean "the current file".
_CURRENT = {"it", "this", "that", "this one", "that one", "the file",
            "the document", "the doc", "this file", "that file", "the current one"}
# References that mean "the file before the current one".
_PREVIOUS = {"the previous one", "the previous file", "the other one",
             "the other file", "previous", "the one before"}


@dataclass
class Selection:
    kind: str                 # "table" | "image" | "paragraph" | "cell_range" | ...
    ref: str                  # a handle the engine understands
    label: str = ""
    at: float = field(default_factory=time.time)


@dataclass
class Reference:
    ok: bool
    path: str = ""
    kind: str = "file"        # "file" | "selection"
    selection: Selection | None = None
    reason: str = ""


class WorkingContext:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.active_file: str = ""
        self.active_folder: str = ""
        self.active_page: int | None = None
        self.active_sheet: str = ""
        self.active_slide: int | None = None
        self.active_cell_range: str = ""
        # recent files, newest last; an OrderedDict de-dupes by path
        self._recent: "OrderedDict[str, float]" = OrderedDict()
        self._selections: list[Selection] = []
        self.last_result: dict[str, Any] = {}

    # -- updating ----------------------------------------------------------
    def set_active(self, path: str | Path, *, category: str = "") -> None:
        with self._lock:
            p = str(Path(os.path.expanduser(str(path))))
            self.active_file = p
            self.active_folder = str(Path(p).parent)
            self._recent[p] = time.time()
            self._recent.move_to_end(p)
            while len(self._recent) > _RECENT_MAX:
                self._recent.popitem(last=False)
            # A new file clears the intra-file location.
            self.active_page = None
            self.active_sheet = ""
            self.active_slide = None
            self.active_cell_range = ""
            self._selections.clear()

    def note_selection(self, kind: str, ref: str, label: str = "") -> None:
        with self._lock:
            self._selections.append(Selection(str(kind), str(ref), str(label)))
            del self._selections[:-_SELECTION_MAX]

    def set_location(self, *, page: int | None = None, sheet: str = "",
                     slide: int | None = None, cell_range: str = "") -> None:
        with self._lock:
            if page is not None:
                self.active_page = int(page)
            if sheet:
                self.active_sheet = str(sheet)
            if slide is not None:
                self.active_slide = int(slide)
            if cell_range:
                self.active_cell_range = str(cell_range)

    # -- resolving ---------------------------------------------------------
    def resolve(self, reference: str) -> Reference:
        """Turn a natural reference into a concrete file or selection."""
        with self._lock:
            text = str(reference or "").strip().casefold()
            recent = list(self._recent.keys())

            # an explicit existing path wins outright
            raw = str(reference or "").strip().strip('"').strip("'")
            if raw and Path(os.path.expanduser(raw)).exists():
                return Reference(True, str(Path(os.path.expanduser(raw))), "file")

            # a typed selection: "that table", "that image", "that paragraph"
            for sel in reversed(self._selections):
                if sel.kind and sel.kind in text:
                    return Reference(True, self.active_file, "selection", sel)

            if text in _CURRENT or not text:
                if self.active_file:
                    return Reference(True, self.active_file, "file")
                return Reference(False, reason="no active file yet")

            if text in _PREVIOUS:
                if len(recent) >= 2:
                    return Reference(True, recent[-2], "file")
                return Reference(False, reason="no previous file to refer back to")

            # ordinal: "the second one", "the first file", "the last one".
            # recent is oldest-first, newest-last, so recent[idx] is correct for
            # both positive ("first"=recent[0]) and -1 ("last"=newest).
            words = text.split()
            for word, idx in _ORDINALS.items():
                if word in words:
                    try:
                        return Reference(True, recent[idx], "file")
                    except IndexError:
                        return Reference(False, reason=f"there is no '{word}' file in context")

            return Reference(False, reason=f"couldn't resolve '{reference}'")

    # -- inspection --------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_file": self.active_file,
                "active_folder": self.active_folder,
                "active_page": self.active_page,
                "active_sheet": self.active_sheet,
                "active_slide": self.active_slide,
                "active_cell_range": self.active_cell_range,
                "recent_files": list(reversed(self._recent.keys())),
                "selections": [f"{s.kind}:{s.label or s.ref}" for s in self._selections],
            }

    def clear(self) -> None:
        with self._lock:
            self.__init__()   # reset every field


_context = WorkingContext()


def get_context() -> WorkingContext:
    return _context
