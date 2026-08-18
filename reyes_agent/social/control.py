"""Who is allowed to publish what, and the one switch that stops everything.

THE DEFAULT IS THE POINT
------------------------
A social automation system that ships in autonomous mode is a system that
posts something regrettable before anyone has read its first draft. So:

    dry run        ON
    mode           APPROVAL
    trusted list   empty
    platforms      disabled

Every one of those must be moved deliberately by the owner. None of them
moves itself, and nothing in ZENO may widen them -- `may_publish` reads
configuration, it never writes it.

THE KILL SWITCH IS CHECKED AT THE ACTION, NOT AT STARTUP
--------------------------------------------------------
A flag read once into a module global is a flag that keeps its old value
until restart, which is the opposite of what an emergency stop is for. It is
re-read on every publish, every scheduled run and every automatic reply, so
flipping it takes effect on the next action rather than the next boot.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from reyes_agent.social import store as social_store

MANUAL = "MANUAL"
APPROVAL = "APPROVAL"
TRUSTED_AUTONOMOUS = "TRUSTED_AUTONOMOUS"
MODES = (MANUAL, APPROVAL, TRUSTED_AUTONOMOUS)

# Settings the owner may change at runtime live in the database so they
# survive a restart; the environment supplies the initial value.
_SETTING_KEYS = (
    "mode", "dry_run", "kill_switch", "instagram_enabled", "tiktok_enabled",
    "trusted_categories", "ig_per_week", "tiktok_per_week", "comment_mode",
    "lead_detection", "quiet_start", "quiet_end", "analytics_interval_h",
)


def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().casefold() in {"1", "true", "yes", "on"}


def _setting(key: str, env_name: str, default: str) -> str:
    """Database first (owner changed it), environment second, default last."""
    stored = social_store.get_store().setting(key, "")
    if stored:
        return stored
    return os.environ.get(env_name, default)


def _flag_setting(key: str, env_name: str, default: str = "false") -> bool:
    return _setting(key, env_name, default).strip().casefold() in {"1", "true", "yes", "on"}


# --- the switches ---------------------------------------------------------

def social_enabled() -> bool:
    return _flag_setting("enabled", "ZENO_SOCIAL_ENABLED", "false")


def dry_run() -> bool:
    """True means nothing reaches a real platform. Defaults to TRUE."""
    return _flag_setting("dry_run", "SOCIAL_DRY_RUN", "true")


def kill_switch_active() -> bool:
    return _flag_setting("kill_switch", "SOCIAL_AUTOMATION_KILL_SWITCH", "false")


def mode() -> str:
    value = _setting("mode", "ZENO_SOCIAL_MODE", APPROVAL).strip().upper()
    return value if value in MODES else APPROVAL


def platform_enabled(platform: str) -> bool:
    if platform == social_store.INSTAGRAM:
        return _flag_setting("instagram_enabled", "ZENO_SOCIAL_INSTAGRAM_ENABLED", "false")
    if platform == social_store.TIKTOK:
        return _flag_setting("tiktok_enabled", "ZENO_SOCIAL_TIKTOK_ENABLED", "false")
    return False


def trusted_categories() -> set[str]:
    raw = _setting("trusted_categories", "ZENO_SOCIAL_TRUSTED_CATEGORIES", "")
    return {part.strip().upper() for part in raw.split(",") if part.strip()}


def posts_per_week(platform: str) -> int:
    key = "ig_per_week" if platform == social_store.INSTAGRAM else "tiktok_per_week"
    env = ("ZENO_SOCIAL_IG_POSTS_PER_WEEK" if platform == social_store.INSTAGRAM
           else "ZENO_SOCIAL_TIKTOK_POSTS_PER_WEEK")
    try:
        return max(0, min(21, int(_setting(key, env, "3"))))
    except ValueError:
        return 3


def comment_mode() -> str:
    value = _setting("comment_mode", "ZENO_SOCIAL_COMMENT_MODE", APPROVAL).strip().upper()
    return value if value in {APPROVAL, "TRUSTED", "OFF"} else APPROVAL


def lead_detection_enabled() -> bool:
    return _flag_setting("lead_detection", "ZENO_SOCIAL_LEAD_DETECTION", "true")


def quiet_hours() -> tuple[int, int]:
    def hour(key: str, env: str, default: str) -> int:
        try:
            return max(0, min(23, int(_setting(key, env, default))))
        except ValueError:
            return int(default)
    return hour("quiet_start", "ZENO_SOCIAL_QUIET_START", "22"), \
        hour("quiet_end", "ZENO_SOCIAL_QUIET_END", "7")


def in_quiet_hours(when: float | None = None) -> bool:
    start, end = quiet_hours()
    if start == end:
        return False
    current = time.localtime(when if when is not None else time.time()).tm_hour
    if start < end:
        return start <= current < end
    # Wraps midnight: 22 -> 7
    return current >= start or current < end


def analytics_interval_hours() -> float:
    try:
        return max(1.0, float(_setting("analytics_interval_h",
                                       "ZENO_SOCIAL_ANALYTICS_INTERVAL_H", "24")))
    except ValueError:
        return 24.0


def max_jobs() -> int:
    try:
        return max(1, min(8, int(os.environ.get("ZENO_SOCIAL_MAX_JOBS", "2"))))
    except ValueError:
        return 2


# --- the decision ---------------------------------------------------------

@dataclass
class PublishDecision:
    allowed: bool
    requires_approval: bool
    simulated: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "requires_approval": self.requires_approval,
                "simulated": self.simulated, "reason": self.reason}


def may_publish(item: dict[str, Any], *, approved_by_owner: bool = False,
                now: float | None = None) -> PublishDecision:
    """The single question every publish path must ask.

    Checks run cheapest-and-most-absolute first: a kill switch beats an
    owner approval, because the switch exists precisely for the moment the
    owner changes their mind after approving.
    """
    platform = str(item.get("platform") or "")

    if kill_switch_active():
        return PublishDecision(False, False, False,
                               "SOCIAL_AUTOMATION_KILL_SWITCH is active; all social "
                               "publishing is stopped")
    if not social_enabled():
        return PublishDecision(False, False, False,
                               "the social system is disabled (ZENO_SOCIAL_ENABLED)")
    if not platform_enabled(platform):
        return PublishDecision(False, False, False,
                               f"{platform} is not enabled")

    simulated = dry_run()
    current_mode = mode()

    if current_mode == MANUAL:
        return PublishDecision(
            False, True, simulated,
            "mode is MANUAL: ZENO prepares content and the owner publishes it")

    if current_mode == APPROVAL:
        if approved_by_owner:
            return PublishDecision(True, False, simulated,
                                   "owner approved this post")
        return PublishDecision(False, True, simulated,
                               "mode is APPROVAL and this post is not approved yet")

    # TRUSTED_AUTONOMOUS -- narrow by design.
    category = str(item.get("category") or "").upper()
    trusted = trusted_categories()
    if approved_by_owner:
        return PublishDecision(True, False, simulated, "owner approved this post")
    if not trusted:
        return PublishDecision(False, True, simulated,
                               "TRUSTED_AUTONOMOUS is set but no category is trusted; "
                               "nothing publishes without approval")
    if category not in trusted:
        return PublishDecision(
            False, True, simulated,
            f"{category or 'uncategorised'} is not a trusted category "
            f"({', '.join(sorted(trusted))})")
    if in_quiet_hours(now):
        start, end = quiet_hours()
        return PublishDecision(False, True, simulated,
                               f"inside quiet hours ({start:02d}:00-{end:02d}:00)")
    return PublishDecision(True, False, simulated,
                           f"{category} is a trusted category and publishing is "
                           f"within the configured window")


# --- owner control panel (Phase 62) --------------------------------------

def panel() -> dict[str, Any]:
    """Everything the owner can see and change, with its current value."""
    start, end = quiet_hours()
    return {
        "enabled": social_enabled(),
        "dry_run": dry_run(),
        "kill_switch": kill_switch_active(),
        "mode": mode(),
        "modes_available": list(MODES),
        "instagram_enabled": platform_enabled(social_store.INSTAGRAM),
        "tiktok_enabled": platform_enabled(social_store.TIKTOK),
        "trusted_categories": sorted(trusted_categories()),
        "instagram_posts_per_week": posts_per_week(social_store.INSTAGRAM),
        "tiktok_posts_per_week": posts_per_week(social_store.TIKTOK),
        "comment_mode": comment_mode(),
        "lead_detection": lead_detection_enabled(),
        "quiet_hours": {"start": start, "end": end, "active_now": in_quiet_hours()},
        "analytics_interval_hours": analytics_interval_hours(),
        "max_background_jobs": max_jobs(),
    }


_SETTABLE = {
    "mode": lambda v: v.strip().upper() if v.strip().upper() in MODES else None,
    "dry_run": lambda v: _normalise_flag(v),
    "kill_switch": lambda v: _normalise_flag(v),
    "enabled": lambda v: _normalise_flag(v),
    "instagram_enabled": lambda v: _normalise_flag(v),
    "tiktok_enabled": lambda v: _normalise_flag(v),
    "lead_detection": lambda v: _normalise_flag(v),
    "trusted_categories": lambda v: ",".join(
        part.strip().upper() for part in v.split(",") if part.strip()),
    "comment_mode": lambda v: v.strip().upper()
        if v.strip().upper() in {APPROVAL, "TRUSTED", "OFF"} else None,
    "ig_per_week": lambda v: _bounded_int(v, 0, 21),
    "tiktok_per_week": lambda v: _bounded_int(v, 0, 21),
    "quiet_start": lambda v: _bounded_int(v, 0, 23),
    "quiet_end": lambda v: _bounded_int(v, 0, 23),
    "analytics_interval_h": lambda v: _bounded_int(v, 1, 168),
}


def _normalise_flag(value: str) -> str | None:
    low = value.strip().casefold()
    if low in {"1", "true", "yes", "on"}:
        return "true"
    if low in {"0", "false", "no", "off"}:
        return "false"
    return None


def _bounded_int(value: str, low: int, high: int) -> str | None:
    try:
        return str(max(low, min(high, int(value))))
    except (TypeError, ValueError):
        return None


def update_setting(key: str, value: str, *, actor: str = "owner") -> tuple[bool, str]:
    """Change one setting. Unknown keys and bad values are refused, not coerced."""
    if key not in _SETTABLE:
        return False, f"{key} is not an owner-settable social setting"
    normalised = _SETTABLE[key](str(value))
    if normalised is None:
        return False, f"{value!r} is not a valid value for {key}"
    store = social_store.get_store()
    store.set_setting(key, normalised)
    store.audit(actor, "setting_changed", target=f"{key}={normalised}",
                result="applied")
    return True, f"{key} is now {normalised}"


def engage_kill_switch(*, actor: str = "owner") -> str:
    """Stop everything now. Published content is not touched."""
    store = social_store.get_store()
    store.set_setting("kill_switch", "true")
    store.audit(actor, "kill_switch_engaged", result="all social automation stopped")
    return ("SOCIAL AUTOMATION KILL SWITCH ENGAGED.\n"
            "Stopped: scheduled publishing, automatic comments, automatic "
            "messages, social background jobs.\n"
            "Not touched: content already published (nothing is deleted).\n"
            "Release it with: release_kill_switch()")


def release_kill_switch(*, actor: str = "owner") -> str:
    store = social_store.get_store()
    store.set_setting("kill_switch", "false")
    store.audit(actor, "kill_switch_released", result="social automation resumed")
    return ("Kill switch released. Social automation may run again, still "
            f"subject to {mode()} mode and dry run = {dry_run()}.")
