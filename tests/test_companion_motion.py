import threading
import time

import pytest

from reyes_agent.companion_motion import (
    CompanionMotionController,
    ease_in_out,
    interpolate_position,
)


@pytest.fixture
def controllers():
    owned = []

    def create(move, **kwargs):
        controller = CompanionMotionController(move, **kwargs)
        owned.append(controller)
        return controller

    yield create
    for controller in owned:
        controller.close()


def test_interpolation_has_exact_endpoints_and_monotonic_middle():
    assert interpolate_position((10, 20), (110, 220), 0) == (10, 20)
    assert interpolate_position((10, 20), (110, 220), 0.5) == (60, 120)
    assert interpolate_position((10, 20), (110, 220), 1) == (110, 220)
    assert 0 < ease_in_out(0.25) < ease_in_out(0.75) < 1


def test_interpolation_clamps_progress_outside_the_animation_range():
    assert interpolate_position((10, 20), (110, 220), -4) == (10, 20)
    assert interpolate_position((10, 20), (110, 220), 7) == (110, 220)


def test_latest_walk_wins_and_close_is_idempotent(controllers):
    moves = []
    completed = []
    reached = threading.Event()
    controller = controllers(lambda x, y: moves.append((x, y)) or True, fps=120)

    controller.walk_to((0, 0), (100, 0), 0.2, lambda ok: completed.append(("old", ok)))
    generation = controller.walk_to(
        (0, 0),
        (20, 30),
        0.03,
        lambda ok: (completed.append(("latest", ok)), reached.set()),
    )

    assert generation == 2
    assert reached.wait(1.0)
    assert moves[-1] == (20, 30)
    assert completed == [("latest", True)]
    controller.close()
    controller.close()
    assert not controller.active


def test_cancel_stops_motion_and_reports_failure_once(controllers):
    moves = []
    callbacks = []
    cancelled = threading.Event()
    controller = controllers(lambda x, y: moves.append((x, y)) or True, fps=60)
    controller.walk_to(
        (0, 0),
        (500, 0),
        0.5,
        lambda ok: (callbacks.append(ok), cancelled.set()),
    )
    time.sleep(0.03)

    controller.cancel()

    assert cancelled.wait(1.0)
    settled_count = len(moves)
    time.sleep(0.05)
    assert len(moves) == settled_count
    assert callbacks == [False]
    assert not controller.active


def test_failed_native_move_ends_plan_and_reports_failure_once(controllers):
    moves = []
    callbacks = []
    finished = threading.Event()

    def reject_move(x, y):
        moves.append((x, y))
        return False

    controller = controllers(reject_move)
    controller.walk_to(
        (0, 0),
        (50, 50),
        0.2,
        lambda ok: (callbacks.append(ok), finished.set()),
    )

    assert finished.wait(1.0)
    assert len(moves) == 1
    assert callbacks == [False]
    assert not controller.active


def test_callback_exception_does_not_kill_the_worker(controllers):
    first_callback = threading.Event()
    second_callback = threading.Event()
    second_result = []
    controller = controllers(lambda _x, _y: True)

    def broken_callback(_ok):
        first_callback.set()
        raise RuntimeError("callback failed")

    controller.walk_to((0, 0), (1, 1), 0, broken_callback)
    assert first_callback.wait(1.0)
    controller.walk_to(
        (1, 1),
        (2, 2),
        0,
        lambda ok: (second_result.append(ok), second_callback.set()),
    )

    assert second_callback.wait(1.0)
    assert second_result == [True]


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf")])
def test_non_finite_or_negative_duration_completes_at_target(controllers, duration):
    moves = []
    finished = threading.Event()
    controller = controllers(lambda x, y: moves.append((x, y)) or True)

    controller.walk_to((10, 20), (30, 40), duration, lambda _ok: finished.set())

    assert finished.wait(1.0)
    assert moves == [(30, 40)]


def test_rapid_replacements_reuse_one_worker(controllers):
    before = sum(
        thread.name == "zeno-companion-motion" and thread.is_alive()
        for thread in threading.enumerate()
    )
    finished = threading.Event()
    moves = []
    controller = controllers(lambda x, y: moves.append((x, y)) or True, fps=60)

    for x in range(1_000):
        controller.walk_to((0, 0), (x, x), 0.05)
    controller.walk_to((0, 0), (1_000, 1_000), 0, lambda _ok: finished.set())

    assert finished.wait(1.0)
    during = sum(
        thread.name == "zeno-companion-motion" and thread.is_alive()
        for thread in threading.enumerate()
    )
    assert during == before + 1
    assert moves[-1] == (1_000, 1_000)


def test_walk_after_close_is_rejected_without_movement(controllers):
    moves = []
    controller = controllers(lambda x, y: moves.append((x, y)) or True)
    controller.close()

    with pytest.raises(RuntimeError, match="closed"):
        controller.walk_to((0, 0), (10, 10), 0)

    assert moves == []


def test_close_timeout_is_not_blocked_by_an_inflight_native_move(controllers):
    worker_count_before = sum(
        thread.name == "zeno-companion-motion" and thread.is_alive()
        for thread in threading.enumerate()
    )
    move_started = threading.Event()
    release_move = threading.Event()
    close_returned = threading.Event()

    def blocking_move(_x, _y):
        move_started.set()
        release_move.wait(1.0)
        return True

    controller = controllers(blocking_move)
    controller.walk_to((0, 0), (10, 10), 0.2)
    assert move_started.wait(1.0)
    closer = threading.Thread(
        target=lambda: (controller.close(timeout_s=0.01), close_returned.set())
    )
    closer.start()

    returned_within_bound = close_returned.wait(0.15)
    release_move.set()
    closer.join(1.0)

    assert returned_within_bound
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        current_count = sum(
            thread.name == "zeno-companion-motion" and thread.is_alive()
            for thread in threading.enumerate()
        )
        if current_count == worker_count_before:
            break
        time.sleep(0.005)
    assert current_count == worker_count_before


def test_new_walk_cannot_be_accepted_between_callback_claim_and_dispatch(
    controllers, monkeypatch
):
    callback_claimed = threading.Event()
    release_callback = threading.Event()
    walk_attempted = threading.Event()
    walk_accepted = threading.Event()
    latest_completed = threading.Event()
    callbacks = []
    original_invoke = CompanionMotionController._invoke_callback

    def pause_before_callback(callback, result):
        if callback is old_callback:
            callback_claimed.set()
            release_callback.wait(1.0)
        original_invoke(callback, result)

    monkeypatch.setattr(
        CompanionMotionController,
        "_invoke_callback",
        staticmethod(pause_before_callback),
    )
    controller = controllers(lambda _x, _y: True)

    def old_callback(ok):
        callbacks.append(("old", ok))

    controller.walk_to((0, 0), (1, 1), 0, old_callback)
    assert callback_claimed.wait(1.0)

    def accept_latest_walk():
        walk_attempted.set()
        controller.walk_to(
            (1, 1),
            (2, 2),
            0,
            lambda ok: (callbacks.append(("latest", ok)), latest_completed.set()),
        )
        walk_accepted.set()

    submitter = threading.Thread(target=accept_latest_walk)
    submitter.start()
    assert walk_attempted.wait(1.0)
    accepted_before_old_dispatch = walk_accepted.wait(0.15)
    release_callback.set()
    submitter.join(1.0)

    assert not accepted_before_old_dispatch
    assert walk_accepted.is_set()
    assert latest_completed.wait(1.0)
    assert callbacks == [("old", True), ("latest", True)]
