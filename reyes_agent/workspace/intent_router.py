"""Contextual UI routing with one-primary-panel noise control."""

from __future__ import annotations

import re
from dataclasses import dataclass

from reyes_agent.workspace.models import PresentationMode, PresentationPlan
from reyes_agent.workspace.redaction import safe_text
from reyes_agent.workspace.registry import PanelRegistry


@dataclass(frozen=True)
class RouteRule:
    panel: str
    patterns: tuple[re.Pattern[str], ...]
    mode: PresentationMode = PresentationMode.FULL
    card_kind: str = ""

    def matches(self, message: str) -> bool:
        return any(pattern.search(message) for pattern in self.patterns)


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value, re.IGNORECASE) for value in values)


_NO_UI = _patterns(
    r"^\s*(?:pause|stop|cancel)\s*[.!?]*$",
    r"\b(?:what(?:'s| is) the time|what time is it|tell me the time)\b",
)
_EXTERNAL_APP = _patterns(
    r"\b(?:open|launch|start)\s+(?:the\s+)?(?:calculator|notepad|paint|settings)\b",
)
_RULES = (
    RouteRule("files", _patterns(
        r"\b(?:find|search|locate|look for)\b.*\b(?:file|folder|cv|resume|assignment|document|pdf)\b",
        r"\b(?:find|locate)\s+(?:my\s+)?(?:cv|resume|assignment)\b")),
    RouteRule("news", _patterns(r"\b(?:news|headlines?|top stories)\b")),
    RouteRule("system", _patterns(
        r"\b(?:system|computer|pc)\b.*\b(?:performance|health|status|ram|memory|cpu)\b",
        r"\bwhat is using (?:my )?(?:ram|memory|cpu)\b")),
    RouteRule("agents", _patterns(
        r"\b(?:ask|open|show|call)\b.*\b(?:council|agents?|stark|kate)\b",
        r"\b(?:council|agent workspace)\b")),
    RouteRule("downloads", _patterns(r"\b(?:download|downloading|downloads)\b"),
              PresentationMode.CARD, "progress"),
    RouteRule("media", _patterns(
        r"\b(?:what(?:'s| is) playing|show what is playing|now playing|media panel)\b",
        r"\b(?:open|show)\b.*\b(?:spotify|music|media)\b")),
    RouteRule("messages", _patterns(r"\b(?:messages?|inbox|message john|send a message)\b")),
    RouteRule("calls", _patterns(r"\b(?:calls?|call history|make a call)\b")),
    RouteRule("calendar", _patterns(r"\b(?:calendar|schedule|appointments?)\b")),
    RouteRule("tasks", _patterns(r"\b(?:tasks?|to-?do|missions?)\b")),
    RouteRule("weather", _patterns(r"\b(?:weather|forecast|temperature)\b")),
    RouteRule("browser", _patterns(r"\b(?:browser|browse|web page|website)\b")),
    RouteRule("coding", _patterns(r"\b(?:coding workspace|code panel|project files)\b")),
    RouteRule("terminal", _patterns(r"\b(?:terminal|command output|shell)\b")),
    RouteRule("documents", _patterns(r"\b(?:documents?|pdfs?|spreadsheets?|slides?)\b")),
    RouteRule("images", _patterns(r"\b(?:images?|photos?|pictures?)\b")),
    RouteRule("tool-health", _patterns(
        r"\b(?:tool|capability|system)\s+(?:health|status|diagnostics)\b",
        r"\bwhat can you actually do\b")),
    RouteRule("activity", _patterns(
        r"\b(?:current activity|live activity|what are you doing|show progress)\b")),
    RouteRule("history", _patterns(
        r"\b(?:what did you just do|last task|execution history|recent actions)\b")),
)
_UNAVAILABLE = {
    "AUTH_REQUIRED", "DEPENDENCY_MISSING", "DISCONNECTED", "UNAVAILABLE", "ERROR",
}


class PanelIntentRouter:
    def __init__(self, registry: PanelRegistry) -> None:
        self.registry = registry

    def route(
        self,
        message: str,
        *,
        correlation_id: str = "",
        source_surface: str = "desktop",
        capability_states: dict[str, str] | None = None,
        active_panels: tuple[str, ...] = (),
    ) -> PresentationPlan:
        text = safe_text(message, 300)
        correlation = safe_text(correlation_id, 80)
        source = safe_text(source_surface, 20).casefold() or "desktop"
        if not text or any(pattern.search(text) for pattern in _NO_UI):
            return PresentationPlan(PresentationMode.NO_UI, correlation_id=correlation,
                                    reason_code="quiet_response")
        if any(pattern.search(text) for pattern in _EXTERNAL_APP):
            return PresentationPlan(
                PresentationMode.CARD,
                card_kind="app",
                reason_code="external_app",
                context={"query": text, "source": source},
                correlation_id=correlation,
            )

        matched = next((rule for rule in _RULES if rule.matches(text)), None)
        if matched is None or self.registry.get(matched.panel) is None:
            return PresentationPlan(PresentationMode.NO_UI, correlation_id=correlation,
                                    reason_code="conversation_only")

        definition = self.registry.get(matched.panel)
        state = str((capability_states or {}).get(matched.panel, "")).upper()
        context = {
            "query": text,
            "source": source,
            "reuse_existing": matched.panel in set(active_panels),
        }
        if state in _UNAVAILABLE:
            return PresentationPlan(
                PresentationMode.CARD,
                primary_panel=matched.panel,
                card_kind="capability",
                reason_code=state.casefold(),
                priority=definition.priority,
                context=context,
                correlation_id=correlation,
            )

        mode = matched.mode
        if re.search(r"\b(?:in the background|silently|without opening)\b", text, re.I):
            mode = PresentationMode.BACKGROUND
        return PresentationPlan(
            mode,
            primary_panel=matched.panel,
            card_kind=matched.card_kind,
            reason_code=f"intent_{matched.panel}",
            priority=definition.priority,
            context=context,
            correlation_id=correlation,
        )
