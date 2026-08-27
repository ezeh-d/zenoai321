"""Real-time notification awareness -- REYES tells you about a new
notification immediately, without waiting for a wake word.

Uses Windows' own UserNotificationListener API (via `winsdk`), the same
system that feeds the Action Center -- covers every desktop app that
raises a toast (Slack, Mail, WhatsApp Desktop, etc.) with no per-app
integration needed. If Phone Link is ever paired with the user's Android
phone, phone notifications get mirrored into this exact same stream too,
so this one listener naturally picks those up as well -- nothing extra
to build for that.

Not built: reading a notification's action buttons or replying through
the notification itself (Windows doesn't expose that generically here).
The reply flow this enables is conversational -- REYES announces what
came in, the user says who to reply to and what, and the existing
send_slack_message/send_telegram_message/etc. tools handle sending it,
same as any other REYES message request.
"""

from __future__ import annotations

import asyncio
import gc
import sqlite3
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from reyes_agent import config

_DB_PATH = config.VAULT_PATH / "07-System" / "heartbeat" / "state.db"
_POLL_INTERVAL_S = 8
_WINRT_TIMEOUT_S = 2.0
_MAX_BACKOFF_S = 300.0
_MAX_ERROR_LOG_BYTES = 256 * 1024
_api_gate = threading.Lock()
_health_lock = threading.Lock()
_consecutive_failures = 0
_retry_after = 0.0
_last_error_log = 0.0
_pending_winrt = 0
_runtime_lock = threading.Lock()
_runtime_ready = threading.Event()
_runtime_loop: asyncio.AbstractEventLoop | None = None
_runtime_thread: threading.Thread | None = None


async def _await_winrt(awaitable: Awaitable[Any]) -> Any:
    """Bound a WinRT call without cancelling its native completion future."""
    global _pending_winrt
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=_WINRT_TIMEOUT_S)
    except TimeoutError:
        with _health_lock:
            _pending_winrt += 1

        def completed(future: asyncio.Future[Any]) -> None:
            global _pending_winrt
            try:
                future.result()
            except Exception:  # noqa: BLE001 -- completion is diagnostic cleanup
                pass
            finally:
                with _health_lock:
                    _pending_winrt = max(0, _pending_winrt - 1)

        task.add_done_callback(completed)
        raise


def _runtime_main() -> None:
    """Own one WinRT-compatible asyncio loop for the listener lifetime.

    Repeated ``asyncio.run()`` calls on winsdk's WinRT objects leaked native
    handles and exposed allocator corruption under Python's development mode.
    One bounded loop thread preserves COM/WinRT affinity and is released by the
    kernel's normal shutdown sequence.
    """
    global _runtime_loop, _runtime_thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with _runtime_lock:
        _runtime_loop = loop
        _runtime_ready.set()
    try:
        loop.run_forever()
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        with _runtime_lock:
            if _runtime_loop is loop:
                _runtime_loop = None
                _runtime_thread = None
            _runtime_ready.clear()


def _ensure_runtime() -> asyncio.AbstractEventLoop:
    global _runtime_thread
    with _runtime_lock:
        if (_runtime_loop is not None and _runtime_thread is not None
                and _runtime_thread.is_alive()):
            return _runtime_loop
        _runtime_ready.clear()
        _runtime_thread = threading.Thread(
            target=_runtime_main, name="zeno-notification-winrt", daemon=True,
        )
        _runtime_thread.start()
    if not _runtime_ready.wait(timeout=2.0):
        raise TimeoutError("Notification WinRT loop did not start.")
    with _runtime_lock:
        if _runtime_loop is None:
            raise RuntimeError("Notification WinRT loop stopped during startup.")
        return _runtime_loop


def _run_on_runtime(factory: Callable[[], Awaitable[Any]]) -> Any:
    loop = _ensure_runtime()

    async def invoke() -> Any:
        try:
            return await factory()
        finally:
            # Release winsdk wrappers on their owning event-loop thread. They
            # can form cycles around native WinRT references, so ordinary
            # refcounting otherwise left roughly one handle per poll.
            gc.collect()

    coroutine = invoke()
    try:
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    except Exception:
        coroutine.close()
        raise
    try:
        return future.result(timeout=_WINRT_TIMEOUT_S + 2.0)
    except TimeoutError:
        future.cancel()
        raise


def _submit_on_runtime(
    factory: Callable[[], Awaitable[Any]],
    completed: Callable[[Any, BaseException | None], None],
) -> None:
    """Schedule one WinRT operation without parking a managed worker.

    The scheduler already invokes ``_poll`` on the bounded pool.  Waiting on
    ``future.result`` there consumed one of four general workers every eight
    seconds even though a dedicated WinRT loop was doing the actual work.
    Completion and backoff now happen on the existing runtime callback.
    """
    loop = _ensure_runtime()

    async def invoke() -> Any:
        try:
            return await factory()
        finally:
            gc.collect()

    coroutine = invoke()
    try:
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    except Exception:
        coroutine.close()
        raise

    def done(result_future) -> None:
        try:
            completed(result_future.result(), None)
        except BaseException as exc:  # cancellation must release the gate too
            completed(None, exc)

    future.add_done_callback(done)


def shutdown_background() -> None:
    """Release the one notification event loop; safe to call repeatedly."""
    deadline = time.monotonic() + _WINRT_TIMEOUT_S + 0.5
    while time.monotonic() < deadline:
        with _health_lock:
            if _pending_winrt == 0:
                break
        time.sleep(0.05)
    with _runtime_lock:
        loop, thread = _runtime_loop, _runtime_thread
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=_WINRT_TIMEOUT_S + 2.0)


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS seen_notifications (id INTEGER PRIMARY KEY)")
    return conn


def _already_seen(notif_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM seen_notifications WHERE id = ?", (notif_id,)).fetchone()
    return row is not None


def _mark_seen(notif_id: int) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR IGNORE INTO seen_notifications (id) VALUES (?)", (notif_id,))


def _extract_text(user_notif) -> tuple[str, str]:
    """Returns (app_name, message_text) from a UserNotification."""
    app_info = user_notif.app_info
    app_name = app_info.display_info.display_name if app_info else "Unknown app"

    toast = user_notif.notification
    lines: list[str] = []
    if toast.visual and toast.visual.bindings.size:
        binding = toast.visual.get_binding(toast.visual.bindings[0].template)
        if binding:
            lines = [t.text for t in binding.get_text_elements() if t.text]
    return app_name, " -- ".join(lines) if lines else "(no text)"


async def _poll_once(speak_fn) -> None:
    from winsdk.windows.ui.notifications import NotificationKinds
    from winsdk.windows.ui.notifications.management import UserNotificationListener

    listener = UserNotificationListener.current
    if listener.get_access_status() != 1:  # ALLOWED
        return

    # The WinRT operation has been observed hanging long enough to exhaust a
    # managed-worker deadline in a console-free WebView host.  wait_for keeps
    # this optional awareness feature from starving voice/model work.
    notifs = await _await_winrt(listener.get_notifications_async(NotificationKinds.TOAST))
    for n in notifs:
        if _already_seen(n.id):
            continue
        _mark_seen(n.id)
        app_name, text = _extract_text(n)
        message = f"{app_name}: {text}"

        from reyes_agent import heartbeat, notification_bus

        # Local record only -- speaks it on this laptop, does NOT push to
        # Telegram or anywhere else. The user was explicit: "speak the
        # notification on the laptop", not "message me about it elsewhere".
        heartbeat._add_notice("notification", message)
        if not heartbeat._in_quiet_hours():
            # Land the notification's content in the SAME history the
            # browser panel's turns read from, *before* speaking it, so
            # that when the user's spoken reply comes in as a normal
            # turn, the agent already has the context to know who/what
            # app it's replying to -- framed as background info, not a
            # live user message, same convention as heartbeat's own
            # automated-check messages.
            from reyes_agent.web import _history, _lock

            with _lock:
                _history.append(
                    {
                        "role": "user",
                        "content": (
                            f"[New notification, not a live message from {config.USER_NAME} -- "
                            f"FYI context only: {message}. If {config.USER_NAME}'s next message "
                            "sounds like a reply ('tell them...', 'say I'll...'), it's a reply to "
                            "this, sent via whichever tool matches the app it came from.]"
                        ),
                    }
                )

            notification_bus.publish({"type": "notification", "app": app_name, "text": text})
            # The NaturalResponseEngine decides whether/how to speak and
            # generates the words from the facts -- instead of a fixed phrase.
            # It keeps OTPs/secrets off the speaker (privacy), stays quiet for
            # trivia, and never says "you have a new message / what's your reply".
            from reyes_agent.conversation import response_engine as nre

            sender = ""
            body = text
            if ": " in text and text.split(": ", 1)[0].strip():
                sender, body = (part.strip() for part in text.split(": ", 1))
            decision = nre.respond(nre.Event(
                kind="message_received", app=app_name, sender=sender,
                message=body or text))
            if decision.action in (nre.SPEAK, nre.ASK) and decision.speech:
                speak_fn(decision.speech)
            # SHOW/WAIT/QUIET/NOTHING: it's already recorded as a panel notice
            # and in history above; ZENO deliberately stays silent.


async def _baseline() -> None:
    """First run: mark every currently-existing notification as already
    seen, so REYES doesn't announce a backlog the instant it starts --
    only genuinely new notifications from here on.
    """
    from winsdk.windows.ui.notifications import NotificationKinds
    from winsdk.windows.ui.notifications.management import UserNotificationListener

    listener = UserNotificationListener.current
    if listener.get_access_status() != 1:
        return
    notifs = await _await_winrt(listener.get_notifications_async(NotificationKinds.TOAST))
    for n in notifs:
        _mark_seen(n.id)


def _speak(text: str) -> None:
    from reyes_agent.voice.tts import TTSError, speak

    try:
        speak(text, threading.Event())
    except TTSError:
        pass  # a failed announcement must not kill the listener loop


def _log_error(exc: Exception) -> None:
    import traceback

    log_path = config.VAULT_PATH / "07-System" / "logs" / "notification_listener_errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() and log_path.stat().st_size >= _MAX_ERROR_LOG_BYTES:
        backup = log_path.with_suffix(".log.1")
        try:
            backup.unlink(missing_ok=True)
            log_path.replace(backup)
        except OSError:
            # Logging must never turn an optional notification failure into a
            # worker failure. If rotation is unavailable, truncate safely.
            try:
                log_path.write_text("", encoding="utf-8")
            except OSError:
                return
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))


def _begin_attempt() -> bool:
    """Enter the one WinRT call allowed at a time, respecting backoff."""
    with _health_lock:
        if time.monotonic() < _retry_after or _pending_winrt:
            return False
    return _api_gate.acquire(blocking=False)


def _record_success() -> None:
    global _consecutive_failures, _retry_after
    with _health_lock:
        _consecutive_failures = 0
        _retry_after = 0.0


def _record_failure(exc: Exception) -> None:
    global _consecutive_failures, _retry_after, _last_error_log
    now = time.monotonic()
    with _health_lock:
        _consecutive_failures += 1
        # One bad WinRT call is enough to back off. Repeated failures increase
        # the quiet period to five minutes without creating another thread.
        delay = min(_MAX_BACKOFF_S, 30.0 * (2 ** min(_consecutive_failures - 1, 4)))
        _retry_after = now + delay
        should_log = now - _last_error_log >= 60.0
        if should_log:
            _last_error_log = now
    if should_log:
        try:
            _log_error(exc)
        except OSError:
            pass


def health() -> dict[str, object]:
    """Small local diagnostic; no WinRT call and no sensitive content."""
    with _health_lock:
        retry_in = max(0.0, _retry_after - time.monotonic())
        return {
            "consecutive_failures": _consecutive_failures,
            "retry_in_s": round(retry_in, 1),
            "winrt_timeout_s": _WINRT_TIMEOUT_S,
            "call_active": _api_gate.locked(),
            "pending_winrt": _pending_winrt,
            "runtime_alive": _runtime_thread is not None and _runtime_thread.is_alive(),
        }


def _baseline_once() -> None:
    if not _begin_attempt():
        return

    def completed(_result: Any, error: BaseException | None) -> None:
        try:
            if error is None:
                _record_success()
            else:
                _record_failure(error if isinstance(error, Exception) else RuntimeError(str(error)))
        finally:
            _api_gate.release()

    try:
        _submit_on_runtime(_baseline, completed)
    except Exception as exc:  # noqa: BLE001 -- optional Windows API may be unavailable
        _record_failure(exc)
        _api_gate.release()


def _poll() -> None:
    if not _begin_attempt():
        return

    def completed(_result: Any, error: BaseException | None) -> None:
        try:
            if error is None:
                _record_success()
            else:
                _record_failure(error if isinstance(error, Exception) else RuntimeError(str(error)))
        finally:
            _api_gate.release()

    try:
        _submit_on_runtime(lambda: _poll_once(_speak), completed)
    except Exception as exc:  # noqa: BLE001 -- one bad poll must not stop future polls
        _record_failure(exc)
        _api_gate.release()


def start_background() -> None:
    from reyes_agent.scheduler import get_scheduler

    scheduler = get_scheduler()
    scheduler.schedule("notification-baseline", _baseline_once, delay=3.0, priority=80, timeout=15)
    scheduler.schedule(
        "notification-listener", _poll, delay=5.0, interval=_POLL_INTERVAL_S,
        priority=50, timeout=max(10.0, _POLL_INTERVAL_S * 2),
    )
