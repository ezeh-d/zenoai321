"""Single-call provider adapter for contextual Charm candidates."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from reyes_agent.charm.models import CharmRequest, ContextSignals
from reyes_agent.charm.styles import get_style


class CharmGenerationError(RuntimeError):
    """Generation failed or returned an invalid structured result."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ResponseGenerator:
    """Generate a bounded candidate set without creating another AI runtime."""

    def __init__(self, run_turn: Callable[..., Any] | None = None) -> None:
        self._run_turn = run_turn

    def _provider(self) -> Callable[..., Any]:
        if self._run_turn is None:
            from reyes_agent.provider import run_turn

            self._run_turn = run_turn
        return self._run_turn

    @staticmethod
    def _system(request: CharmRequest) -> str:
        profile = get_style(request.mode)
        constraints = " ".join(profile.constraints) or "None beyond the universal rules."
        return (
            "You are ZENO's native Charm Engine candidate generator, not a separate assistant. "
            "Write context-specific drafts only; never send messages or claim they were sent. "
            "Respect rejection, discomfort, boundaries, and weak reciprocity. Never use coercion, "
            "deceptive impersonation, harassment, canned pickup lines, or invented shared history. "
            f"Selected mode: {profile.mode.value}. Style guidance: {profile.guidance} "
            f"Targets (0-100): warmth={profile.warmth}, humor={profile.humor}, "
            f"flirt={profile.flirt}, directness={profile.directness}. "
            f"Mode constraints: {constraints} "
            "Return only strict JSON with this shape: "
            '{"candidates":[{"text":"draft"}]}. '
            f"Return exactly {request.count} distinct candidates, each under 1000 characters. "
            "Do not include analysis, scoring, markdown, or chain-of-thought."
        )

    @staticmethod
    def _payload(
        request: CharmRequest,
        signals: ContextSignals,
        preferences: tuple[str, ...],
    ) -> str:
        return json.dumps(
            {
                "instruction": request.instruction,
                "feature": request.feature.value,
                "mode": request.mode.value,
                "intensity": request.intensity,
                "relationship": request.relationship,
                "objective": request.objective,
                "conversation": list(request.conversation),
                "context_signals": signals.as_dict(),
                "non_sensitive_style_preferences": list(preferences[:6]),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _parse(raw: str, limit: int) -> tuple[str, ...]:
        text = _FENCE_RE.sub("", str(raw or "").strip()).strip()
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise CharmGenerationError("Charm provider returned invalid JSON.") from exc
        rows = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise CharmGenerationError("Charm provider omitted the candidates list.")
        out: list[str] = []
        seen: set[str] = set()
        for row in rows:
            candidate = row.get("text") if isinstance(row, dict) else row
            clean = " ".join(str(candidate or "").split())[:1000]
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                out.append(clean)
            if len(out) >= limit:
                break
        if not out:
            raise CharmGenerationError("Charm provider returned no usable candidates.")
        if len(out) < limit:
            raise CharmGenerationError(
                f"Charm provider returned {len(out)} of {limit} requested candidates."
            )
        return tuple(out)

    def generate(
        self,
        request: CharmRequest,
        signals: ContextSignals,
        *,
        preferences: tuple[str, ...] = (),
        cancel_check: Callable[[], None] | None = None,
    ) -> tuple[str, ...]:
        try:
            turn = self._provider()(
                history=[{
                    "role": "user",
                    "content": self._payload(request, signals, preferences),
                }],
                system=self._system(request),
                tools=[],
                cancel_check=cancel_check,
                task_kind="conversation",
            )
        except CharmGenerationError:
            raise
        except Exception as exc:
            raise CharmGenerationError(f"Charm provider failed: {exc}") from exc
        if getattr(turn, "tool_calls", None):
            raise CharmGenerationError("Charm provider attempted an unsupported tool call.")
        return self._parse(getattr(turn, "text", ""), request.count)
