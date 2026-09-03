"""Trusted, source-aware metadata shared by every ZENO agent turn."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


_PROACTIVE_SOURCES = frozenset({"heartbeat", "scheduled", "event", "dream"})


@dataclass(frozen=True)
class TurnContext:
    source: str = "internal"
    owner_authenticated: bool = False
    spoken: bool = False
    turn_id: str = ""

    @property
    def is_proactive(self) -> bool:
        return self.source in _PROACTIVE_SOURCES


_current: ContextVar[TurnContext] = ContextVar("zeno_turn_context", default=TurnContext())


def current_turn_context() -> TurnContext:
    return _current.get()


@contextmanager
def use_turn_context(context: TurnContext) -> Iterator[TurnContext]:
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def build_turn_context(
    source: str, *, owner_authenticated: bool, spoken: bool = False, turn_id: str = ""
) -> TurnContext:
    normalized = "_".join(str(source or "internal").strip().casefold().replace("-", "_").split())
    return TurnContext(
        source=normalized or "internal",
        owner_authenticated=bool(owner_authenticated),
        spoken=bool(spoken),
        turn_id=str(turn_id or "")[:120],
    )
