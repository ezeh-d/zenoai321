"""Bounded motion primitives for the native Mini ZENO window."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


Position = tuple[int, int]
CompletionCallback = Callable[[bool], Any]
MoveCallback = Callable[[int, int], bool]

_LOGGER = logging.getLogger(__name__)


def ease_in_out(progress: float) -> float:
    """Return smoothstep easing for progress clamped to ``0..1``."""

    bounded = max(0.0, min(1.0, float(progress)))
    return bounded * bounded * (3.0 - 2.0 * bounded)


def interpolate_position(
    start: Sequence[int], target: Sequence[int], progress: float
) -> Position:
    """Interpolate two screen positions with exact integer endpoints."""

    eased = ease_in_out(progress)
    return (
        round(start[0] + (target[0] - start[0]) * eased),
        round(start[1] + (target[1] - start[1]) * eased),
    )


@dataclass(frozen=True)
class _Plan:
    generation: int
    start: Position
    target: Position
    started_at: float
    duration_s: float
    on_complete: CompletionCallback | None


class CompanionMotionController:
    """Serialize native companion movement through one bounded worker."""

    def __init__(
        self,
        move: MoveCallback,
        *,
        fps: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._move = move
        self._clock = clock
        self._frame_s = 1.0 / max(10.0, min(60.0, float(fps)))
        self._condition = threading.Condition()
        self._dispatch_lock = threading.RLock()
        self._generation = 0
        self._plan: _Plan | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="zeno-companion-motion",
            daemon=True,
        )
        self._thread.start()

    @property
    def active(self) -> bool:
        with self._condition:
            return not self._closed and self._plan is not None

    def walk_to(
        self,
        start: Sequence[int],
        target: Sequence[int],
        duration_s: float,
        on_complete: CompletionCallback | None = None,
    ) -> int:
        duration = float(duration_s)
        if not math.isfinite(duration) or duration < 0:
            duration = 0.0
        normalized_start = (round(start[0]), round(start[1]))
        normalized_target = (round(target[0]), round(target[1]))
        with self._dispatch_lock:
            with self._condition:
                if self._closed:
                    raise RuntimeError("companion motion controller is closed")
                self._generation += 1
                self._plan = _Plan(
                    generation=self._generation,
                    start=normalized_start,
                    target=normalized_target,
                    started_at=self._clock(),
                    duration_s=duration,
                    on_complete=on_complete,
                )
                self._condition.notify()
                return self._generation

    def cancel(self) -> None:
        callback = None
        with self._dispatch_lock:
            with self._condition:
                if self._closed or self._plan is None:
                    return
                callback = self._plan.on_complete
                self._generation += 1
                self._plan = None
                self._condition.notify()
            self._invoke_callback(callback, False)

    def close(self, timeout_s: float = 1.0) -> None:
        callback = None
        with self._dispatch_lock:
            with self._condition:
                if self._closed:
                    return
                self._closed = True
                if self._plan is not None:
                    callback = self._plan.on_complete
                self._generation += 1
                self._plan = None
                self._condition.notify()
            self._invoke_callback(callback, False)
        if threading.current_thread() is not self._thread:
            self._thread.join(max(0.0, float(timeout_s)))

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._plan is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                plan = self._plan

            while plan is not None:
                callback = None
                result = False
                finished = False
                with self._condition:
                    if self._closed:
                        return
                    if self._plan is not plan or plan.generation != self._generation:
                        break

                    elapsed = max(0.0, self._clock() - plan.started_at)
                    progress = 1.0 if plan.duration_s == 0 else min(1.0, elapsed / plan.duration_s)
                    x, y = interpolate_position(plan.start, plan.target, progress)

                try:
                    moved = bool(self._move(x, y))
                except Exception:
                    _LOGGER.exception("Companion native move callback failed")
                    moved = False

                with self._condition:
                    if self._closed:
                        return
                    if self._plan is not plan or plan.generation != self._generation:
                        break
                    if not moved or progress >= 1.0:
                        callback = plan.on_complete
                        result = moved
                        self._plan = None
                        finished = True
                    else:
                        remaining = max(0.0, plan.duration_s - elapsed)
                        self._condition.wait(min(self._frame_s, remaining))

                if finished:
                    self._dispatch_completion(plan.generation, callback, result)
                    break

    def _dispatch_completion(
        self,
        generation: int,
        callback: CompletionCallback | None,
        result: bool,
    ) -> None:
        with self._dispatch_lock:
            with self._condition:
                if self._closed or generation != self._generation:
                    return
            self._invoke_callback(callback, result)

    @staticmethod
    def _invoke_callback(callback: CompletionCallback | None, result: bool) -> None:
        if callback is None:
            return
        try:
            callback(result)
        except Exception:
            _LOGGER.exception("Companion motion completion callback failed")
