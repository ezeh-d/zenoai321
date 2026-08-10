"""Browser Controller -- real web automation via Playwright, with a
persistent profile and an OpenCV vision fallback when selectors fail.

WHY A LONG-LIVED BROWSER
------------------------
Every tool call reuses ONE browser + ONE context rather than launching per
call. That's what makes "log in, then go here, then fill this" work at
all: cookies, localStorage and session survive across tool calls because
it's literally the same context. The profile is stored on disk
(vault/07-System/browser_profile) so sessions also survive restarts.

Runs headed by default -- the user can see what's happening and take over
mid-flow. Set BROWSER_HEADLESS=1 in .env for background operation.

VISION FALLBACK
---------------
Selector-driven clicking breaks on canvas apps, obfuscated class names,
and dynamic React ids. When a selector fails, `vision_click` screenshots
the page and uses OpenCV template matching to find a supplied reference
image, then clicks its centre. That is a genuine fallback path, not a
decorative one -- but it needs a template image to match against, so it's
exposed as its own explicit tool rather than pretending selectors
magically self-heal.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
No mass-submission helper (bulk job applications, bulk posting). The
primitives here can fill and submit a form the user is driving, one at a
time, with the page visible. Firing generated applications or posts at
other people in bulk is a different act with a different failure mode --
it reaches third parties, can't be recalled, and damages the user's own
reputation if the model gets it wrong. See AGENT.md's standing list.
"""

from __future__ import annotations

import os
import importlib.util
import threading
import time
from pathlib import Path
from typing import Any

from reyes_agent import config

_PROFILE_DIR = config.VAULT_PATH / "07-System" / "browser_profile"
_DOWNLOAD_DIR = config.VAULT_PATH / "00-Inbox"

_lock = threading.Lock()
_playwright = None
_context = None  # persistent context == the browser, profile-backed
_last_used_at = 0.0
_launch_failures = 0
_owner_thread_id: int | None = None
_page_count = 0
_DEFAULT_TIMEOUT_MS = max(1_000, int(os.environ.get("BROWSER_TIMEOUT_MS", "45000")))


def _headless() -> bool:
    return os.environ.get("BROWSER_HEADLESS", "").strip().lower() in ("1", "true", "yes", "on")


def get_page():
    """The current page, starting the browser on first use.

    Persistent context (launch_persistent_context) rather than launch() +
    new_context(): that's what gives a real on-disk profile, so a login
    done once is still valid next week.
    """
    global _playwright, _context, _last_used_at, _launch_failures, _owner_thread_id, _page_count
    with _lock:
        try:
            if _context is None:
                from playwright.sync_api import sync_playwright

                _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
                _playwright = sync_playwright().start()
                _context = _playwright.chromium.launch_persistent_context(
                    user_data_dir=str(_PROFILE_DIR),
                    headless=_headless(),
                    accept_downloads=True,
                    viewport={"width": 1440, "height": 900},
                    # Browser launch can block on a broken profile, a stale
                    # Chromium child or a locked user-data directory.  It is
                    # still on the browser owner worker, but must have the
                    # same finite boundary as page actions.
                    timeout=_DEFAULT_TIMEOUT_MS,
                )
                _context.set_default_timeout(_DEFAULT_TIMEOUT_MS)
                _context.set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)
                _owner_thread_id = threading.get_ident()
            elif _owner_thread_id != threading.get_ident():
                raise RuntimeError(
                    "Playwright context accessed from a non-owner thread; "
                    "use reyes_agent.browser_runtime."
                )
            if not _context.pages:
                _context.new_page()
            _page_count = len(_context.pages)
            _last_used_at = time.monotonic()
            _launch_failures = 0
            return _context.pages[-1]
        except Exception:
            _launch_failures += 1
            _close_locked()
            raise


def close_browser() -> None:
    with _lock:
        _close_locked()


def _close_locked() -> None:
    global _playwright, _context, _owner_thread_id, _page_count
    if _context is not None:
        try:
            _context.close()
        except Exception:  # noqa: BLE001
            pass
        _context = None
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        _playwright = None
    _owner_thread_id = None
    _page_count = 0


def is_open() -> bool:
    with _lock:
        return _context is not None


def invalidate_if_unhealthy(error: Exception | str) -> bool:
    """Discard a crashed Playwright context so the next request recreates it."""
    text = str(error).lower()
    broken = any(token in text for token in (
        "target page, context or browser has been closed",
        "browser has been closed",
        "connection closed",
        "browser_type.launch",
    ))
    if broken:
        close_browser()
    return broken


def close_if_idle(max_idle_seconds: float = 1800.0) -> bool:
    """Release browser resources after sustained inactivity; the profile stays."""
    if not is_open() or time.monotonic() - _last_used_at < max_idle_seconds:
        return False
    close_browser()
    return True


def health() -> dict[str, Any]:
    with _lock:
        try:
            installed = importlib.util.find_spec("playwright.sync_api") is not None
        except (ImportError, ModuleNotFoundError):
            installed = False
        return {
            "available": installed,
            "open": _context is not None,
            # Do not touch Playwright objects from diagnostic/request threads:
            # sync_api contexts are strictly owner-thread affine.
            "pages": _page_count,
            "idle_s": round(time.monotonic() - _last_used_at, 1) if _last_used_at else None,
            "timeout_ms": _DEFAULT_TIMEOUT_MS,
            "launch_failures": _launch_failures,
            "owner_thread": _owner_thread_id,
            "state": ("ONLINE" if _context is not None else
                      "DEGRADED" if _launch_failures else
                      "STANDBY" if installed else "NOT_CONFIGURED"),
        }


def action_timeout_ms(default_ms: int) -> int:
    """Cap a Playwright wait by the current managed task's remaining time."""
    try:
        from reyes_agent.worker_pool import current_task_context

        context = current_task_context()
        if context is not None and context.remaining is not None:
            return max(1_000, min(int(default_ms), int(context.remaining * 1000)))
    except Exception:  # noqa: BLE001 -- timeout selection must not block tools
        pass
    return max(1_000, min(int(default_ms), _DEFAULT_TIMEOUT_MS))


def find_on_screenshot(template_path: str, threshold: float = 0.75) -> tuple[int, int] | None:
    """OpenCV template match against a screenshot of the live page.

    Returns the centre point of the best match in page coordinates, or
    None if nothing matched above `threshold`. This is the vision fallback
    for when there is no usable selector.
    """
    import cv2
    import numpy as np

    page = get_page()
    shot = page.screenshot()
    scene = cv2.imdecode(np.frombuffer(shot, np.uint8), cv2.IMREAD_COLOR)
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if scene is None or template is None:
        return None
    if template.shape[0] > scene.shape[0] or template.shape[1] > scene.shape[1]:
        return None
    result = cv2.matchTemplate(scene, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < threshold:
        return None
    h, w = template.shape[:2]
    return (int(max_loc[0] + w / 2), int(max_loc[1] + h / 2))
