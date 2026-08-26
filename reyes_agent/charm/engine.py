"""Native Charm Engine orchestration with bounded state and honest outcomes."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from reyes_agent.charm.context import analyze_conversation
from reyes_agent.charm.critic import rank_candidates
from reyes_agent.charm.generator import CharmGenerationError, ResponseGenerator
from reyes_agent.charm.memory import CharmSessionStore, MemoryAdapter
from reyes_agent.charm.models import (
    CharmFeature,
    CharmMode,
    CharmRequest,
    CharmResult,
    ContextSignals,
    Recommendation,
)


def _default_publish(name: str, payload: dict[str, Any]) -> None:
    from reyes_agent import event_bus

    event_bus.publish(name, payload=payload, source="charm")


class CharmEngine:
    """Analyze, generate once, rank locally, and retain only bounded callbacks."""

    def __init__(
        self,
        *,
        generator: ResponseGenerator | Any | None = None,
        memory: MemoryAdapter | Any | None = None,
        sessions: CharmSessionStore | None = None,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._generator = generator or ResponseGenerator()
        self._memory = memory or MemoryAdapter()
        self._sessions = sessions or CharmSessionStore()
        self._publish = publish or _default_publish

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        try:
            self._publish(name, payload)
        except Exception:
            pass

    def analyze(
        self,
        conversation: list[str] | tuple[str, ...],
        relationship: str = "",
        *,
        session_id: str = "default",
        emit_event: bool = False,
    ) -> ContextSignals:
        signals = analyze_conversation(conversation, relationship)
        if emit_event:
            self._emit("charm.analyzed", {
                "session_id": str(session_id or "default")[:80],
                "recommendation": signals.recommendation.value,
                "tone": signals.tone,
                "engagement": signals.engagement,
                "confidence": signals.confidence,
            })
        return signals

    def generate(
        self,
        request: CharmRequest,
        *,
        cancel_check: Callable[[], None] | None = None,
    ) -> CharmResult:
        signals = self.analyze(request.conversation, request.relationship)
        self._sessions.record_conversation(request.session_id, request.conversation)
        self._emit("charm.started", {
            "session_id": request.session_id,
            "mode": request.mode.value,
            "feature": request.feature.value,
            "message_count": len(request.conversation),
        })
        self._emit("charm.analyzed", {
            "session_id": request.session_id,
            "recommendation": signals.recommendation.value,
            "tone": signals.tone,
            "engagement": signals.engagement,
            "confidence": signals.confidence,
        })

        if signals.recommendation in {Recommendation.PULL_BACK, Recommendation.ABORT}:
            warning = (
                "The conversation indicates contact should stop. Respect that boundary and do not send another message."
                if signals.recommendation is Recommendation.ABORT
                else "The conversation indicates you should back off instead of escalating."
            )
            self._emit("charm.backoff", {
                "session_id": request.session_id,
                "recommendation": signals.recommendation.value,
                "reason_count": len(signals.reasons),
            })
            return CharmResult(request=request, signals=signals, warning=warning)

        try:
            durable_preferences = tuple(self._memory.preferences(request.instruction))[:4]
        except Exception:
            durable_preferences = ()
        callback_hints = self._sessions.feedback_hints(request.session_id, limit=2)
        preferences = durable_preferences + callback_hints
        try:
            generated = self._generator.generate(
                request,
                signals,
                preferences=preferences,
                cancel_check=cancel_check,
            )
            self._emit("charm.generated", {
                "session_id": request.session_id,
                "candidate_count": len(generated),
            })
            ranked = rank_candidates(
                generated,
                request,
                signals,
                self._sessions.recent_hashes(request.session_id),
            )
            self._emit("charm.ranked", {
                "session_id": request.session_id,
                "candidate_count": len(ranked),
                "eligible_count": sum(item.eligible for item in ranked),
            })
        except CharmGenerationError as exc:
            message = str(exc)[:500]
            self._emit("charm.failed", {
                "session_id": request.session_id,
                "error": message,
            })
            return CharmResult(request=request, signals=signals, error=message)
        except Exception as exc:
            message = f"Charm Engine failed safely: {exc}"[:500]
            self._emit("charm.failed", {
                "session_id": request.session_id,
                "error": message,
            })
            return CharmResult(request=request, signals=signals, error=message)

        self._sessions.record_candidates(
            request.session_id, tuple(item.text for item in ranked)
        )
        best = next((item for item in ranked if item.eligible), None)
        warning = "" if best else "No candidate passed the safety and quality checks."
        self._emit("charm.completed", {
            "session_id": request.session_id,
            "mode": request.mode.value,
            "feature": request.feature.value,
            "recommendation": signals.recommendation.value,
            "candidate_count": len(ranked),
            "eligible_count": sum(item.eligible for item in ranked),
            "best_candidate_id": best.id if best else "",
        })
        return CharmResult(
            request=request,
            signals=signals,
            candidates=ranked,
            best=best,
            warning=warning,
            generated=bool(ranked),
        )

    def reply(
        self,
        instruction: str,
        conversation: list[str] | tuple[str, ...] = (),
        *,
        mode: CharmMode | str | None = None,
        feature: CharmFeature | str = CharmFeature.REPLY,
        count: int = 3,
        intensity: int | None = None,
        relationship: str = "",
        objective: str = "",
        include_scores: bool = True,
        session_id: str = "default",
        cancel_check: Callable[[], None] | None = None,
    ) -> CharmResult:
        selected_mode, selected_intensity = self._sessions.selection(session_id)
        supplied_conversation = tuple(conversation)
        effective_conversation = (
            supplied_conversation
            if supplied_conversation
            else self._sessions.recent_conversation(session_id)
        )
        request = CharmRequest(
            instruction=instruction,
            conversation=effective_conversation,
            mode=mode if mode is not None else selected_mode,
            feature=feature,
            count=count,
            intensity=selected_intensity if intensity is None else intensity,
            relationship=relationship,
            objective=objective,
            include_scores=include_scores,
            session_id=session_id,
        )
        return self.generate(request, cancel_check=cancel_check)

    def set_mode(
        self, session_id: str, mode: CharmMode | str, intensity: int | None = None
    ) -> dict[str, Any]:
        self._sessions.set_mode(session_id, mode, intensity)
        return self.status(session_id)

    def coach(
        self,
        feature: CharmFeature | str,
        instruction: str,
        conversation: list[str] | tuple[str, ...] = (),
        **kwargs: Any,
    ) -> CharmResult:
        """Run any coaching surface through the same analyzed reply pipeline."""
        return self.reply(
            instruction,
            conversation,
            feature=feature,
            **kwargs,
        )

    def feedback(self, session_id: str, candidate_id: str, outcome: str) -> bool:
        accepted = self._sessions.record_feedback(session_id, candidate_id, outcome)
        self._emit("charm.feedback", {
            "session_id": session_id,
            "candidate_id": str(candidate_id)[:80],
            "accepted": accepted,
            "outcome": self._sessions.feedback_label(outcome),
        })
        return accepted

    def status(self, session_id: str = "default") -> dict[str, Any]:
        snapshot = self._sessions.snapshot(session_id)
        if not snapshot.get("exists"):
            mode, intensity = self._sessions.selection(session_id)
            snapshot = self._sessions.snapshot(session_id)
            snapshot.update({"mode": mode.value, "intensity": intensity})
        snapshot.update({
            "engine": "CHARM ENGINE",
            "available": True,
            "modes": [item.value for item in CharmMode],
            "durable_transcript_storage": False,
            "automatic_sending": False,
        })
        try:
            from reyes_agent import config

            snapshot["provider"] = config.MODEL_PROVIDER or "configured fallback chain"
        except Exception:
            snapshot["provider"] = "unknown"
        return snapshot


_instance: CharmEngine | None = None
_instance_lock = threading.Lock()


def get_charm_engine() -> CharmEngine:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CharmEngine()
    return _instance
