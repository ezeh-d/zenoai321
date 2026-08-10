"""The structured element a screen parse returns.

One schema regardless of which backend produced it -- UI Automation, OCR or
OmniParser -- so the computer controller never has to care where an element
came from. `source` and `confidence` say how much to trust it: UIA is
accessibility ground truth (1.0), OCR and vision models are inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Windows UIA control type ids -> readable names. Only the ones that
# actually turn up in real applications.
CONTROL_TYPES = {
    50000: "button", 50001: "calendar", 50002: "checkbox", 50003: "combobox",
    50004: "edit", 50005: "link", 50006: "image", 50007: "listitem",
    50008: "list", 50009: "menu", 50010: "menubar", 50011: "menuitem",
    50012: "progressbar", 50013: "radiobutton", 50014: "scrollbar",
    50015: "slider", 50016: "spinner", 50017: "statusbar", 50018: "tab",
    50019: "tabitem", 50020: "text", 50021: "toolbar", 50022: "tooltip",
    50023: "tree", 50024: "treeitem", 50025: "custom", 50026: "group",
    50027: "thumb", 50028: "datagrid", 50029: "dataitem", 50030: "document",
    50031: "splitbutton", 50032: "window", 50033: "pane", 50034: "header",
    50035: "headeritem", 50036: "table", 50037: "titlebar", 50038: "separator",
}

# What a human can actually act on. Everything else is chrome or layout.
INTERACTIVE = frozenset({
    "button", "checkbox", "combobox", "edit", "link", "listitem", "menuitem",
    "radiobutton", "slider", "splitbutton", "tabitem", "treeitem", "spinner",
})

# Types that hold text worth reading even though you cannot click them.
READABLE = frozenset({"text", "document", "statusbar", "tooltip", "header"})

UIA, OCR, OMNIPARSER = "uia", "ocr", "omniparser"


@dataclass
class Element:
    """One thing on screen."""

    type: str
    label: str = ""
    position: tuple[int, int, int, int] = (0, 0, 0, 0)   # left, top, width, height
    interactive: bool = False
    confidence: float = 1.0
    source: str = UIA
    enabled: bool = True
    automation_id: str = ""
    depth: int = 0
    # What the control CONTAINS, as opposed to what it is called. A text box
    # is named "Search" forever while its value is what the owner typed --
    # without this ZENO can see the box but not read it.
    value: str = ""

    @property
    def center(self) -> tuple[int, int]:
        left, top, width, height = self.position
        return (left + width // 2, top + height // 2)

    @property
    def area(self) -> int:
        return max(0, self.position[2]) * max(0, self.position[3])

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "label": self.label, "position": list(self.position),
                "interactive": self.interactive, "confidence": round(self.confidence, 3),
                "source": self.source, "enabled": self.enabled, "value": self.value,
                "automation_id": self.automation_id, "center": list(self.center)}

    def describe(self) -> str:
        left, top, width, height = self.position
        state = "" if self.enabled else " (disabled)"
        content = f" containing {self.value[:120]!r}" if self.value else ""
        return (f"{self.type} '{self.label}'{state}{content} "
                f"at ({left},{top}) {width}x{height}")


@dataclass
class Scene:
    """Everything a single parse saw, plus how it was obtained."""

    window: str = ""
    window_handle: int = 0
    elements: list[Element] = field(default_factory=list)
    source: str = UIA
    parsed_at: float = 0.0
    duration_ms: int = 0
    truncated: bool = False
    error: str = ""
    # Whether this parse can be believed. Set by the parser via
    # `vision.coverage`; None means it was never assessed.
    coverage: Any = None

    @property
    def interactive(self) -> list[Element]:
        return [e for e in self.elements if e.interactive and e.enabled]

    @property
    def reliable(self) -> bool:
        """False when we know we are looking at a shell, not the window."""
        return bool(self.coverage is None or self.coverage.trustworthy)

    def as_dict(self) -> dict[str, Any]:
        return {"window": self.window, "source": self.source,
                "element_count": len(self.elements),
                "interactive_count": len(self.interactive),
                "duration_ms": self.duration_ms, "truncated": self.truncated,
                "error": self.error, "reliable": self.reliable,
                "coverage": self.coverage.as_dict() if self.coverage else None,
                "elements": [e.as_dict() for e in self.elements]}

    def summary(self, limit: int = 25) -> str:
        """Readable for a model. Interactive things first -- those are what
        an action can target."""
        if self.error:
            return f"Could not read the screen: {self.error}"

        # An unreliable scan must never be reported as an empty window --
        # that is how the loop concludes a control "is not there" when it is
        # simply not being published.
        if not self.reliable:
            note = (f"I could not properly read '{self.window}': {self.coverage.reason}. "
                    f"To fix it: {self.coverage.remedy}.")
            if self.elements:
                note += (f" (Only {len(self.elements)} element(s) came back, so treat "
                         "anything below as incomplete.)")
            return note

        if not self.elements:
            return f"'{self.window}' exposes no readable elements."
        lines = [f"Window: {self.window} ({len(self.elements)} elements, "
                 f"{len(self.interactive)} interactive, via {self.source})"]
        for element in self.interactive[:limit]:
            lines.append("  " + element.describe())
        labelled_text = [e for e in self.elements
                         if e.type in READABLE and e.label and not e.interactive]
        for element in labelled_text[:max(0, limit - len(self.interactive))]:
            lines.append(f"  text: {element.label[:80]!r}")
        if self.truncated:
            lines.append("  ... (scan was capped; this is not the whole window)")
        return "\n".join(lines)


def classify(control_type: int) -> tuple[str, bool]:
    """(name, interactive) for a raw UIA control type id."""
    name = CONTROL_TYPES.get(int(control_type), "unknown")
    return name, name in INTERACTIVE
