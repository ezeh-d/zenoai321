"""What every platform adapter must do, and what none of them may claim.

THE ONE RULE
------------
`publish()` returns PUBLISHED only when the platform returned an identifier
AND a separate read found that identifier. "The POST did not raise" is not
publication -- an HTTP 200 with an error body, a queued upload that later
fails moderation, and a successful publish are three different outcomes that
look identical to code that only checks the status line.

So the result carries `verified` separately from `ok`, and the pipeline only
writes PUBLISHED when `verified` is true.

RATE LIMITS ARE THE ADAPTER'S JOB (Phase 49)
--------------------------------------------
Not the caller's. A caller that has to remember to check a limit is a caller
that will forget once. `_RateLimiter` is enforced inside `request()`, so
every call through an adapter is limited whether or not anyone remembered.

DRY RUN IS ENFORCED HERE TOO
----------------------------
Belt and braces: the pipeline checks it, and the adapter refuses to make a
network call regardless. A publishing path that reaches the network because
one check was missed is the failure this brief cares most about.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from reyes_agent.social import control, store as social_store

# Health states, shared with the health monitor (Phase 52).
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
AUTH_REQUIRED = "AUTH_REQUIRED"
RATE_LIMITED = "RATE_LIMITED"
OFFLINE = "OFFLINE"
FAILED = "FAILED"
NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass
class PublishResult:
    """What actually happened, with belief and confirmation kept apart."""
    ok: bool
    verified: bool = False
    post_id: str = ""
    post_url: str = ""
    simulated: bool = False
    detail: str = ""
    error: str = ""
    response: dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)

    @property
    def status(self) -> str:
        if self.simulated:
            return "SIMULATED"
        if self.ok and self.verified:
            return social_store.PUBLISHED
        if self.ok and not self.verified:
            # Deliberately not PUBLISHED. The platform accepted it and could
            # not confirm it; saying PUBLISHED here would be the exact lie
            # the brief forbids.
            return social_store.PUBLISHING
        return social_store.FAILED

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "verified": self.verified, "post_id": self.post_id,
                "post_url": self.post_url, "simulated": self.simulated,
                "status": self.status, "detail": self.detail, "error": self.error}


@dataclass
class AuthState:
    connected: bool
    state: str
    account_id: str = ""
    username: str = ""
    scopes: tuple[str, ...] = ()
    expires: float | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"connected": self.connected, "state": self.state,
                "account_id": self.account_id, "username": self.username,
                "scopes": list(self.scopes), "expires": self.expires,
                "detail": self.detail}


class RateLimitError(RuntimeError):
    """Raised before a call is made, never after the platform complains."""


class _RateLimiter:
    """A sliding window per platform. Refuses rather than sleeping forever."""

    def __init__(self, max_calls: int, window_s: float) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self) -> tuple[bool, float]:
        """(allowed, seconds until a slot frees)."""
        now = time.time()
        with self._lock:
            while self._calls and now - self._calls[0] > self.window_s:
                self._calls.popleft()
            if len(self._calls) < self.max_calls:
                return True, 0.0
            return False, max(0.0, self.window_s - (now - self._calls[0]))

    def record(self) -> None:
        with self._lock:
            self._calls.append(time.time())

    def snapshot(self) -> dict[str, Any]:
        allowed, wait = self.check()
        with self._lock:
            used = len(self._calls)
        return {"used": used, "limit": self.max_calls,
                "window_s": self.window_s, "allowed": allowed,
                "retry_after_s": round(wait, 1)}


# Publishing fails for reasons that do not improve with repetition -- a
# rejected caption, a revoked token, a video the platform will not accept.
# Retrying those forever is how an account gets rate limited into oblivion.
MAX_PUBLISH_ATTEMPTS = 3


class SocialAdapter:
    """Base class. Subclasses implement the platform-specific calls."""

    platform = ""
    # Conservative defaults; each platform narrows them.
    rate_limit = (200, 3600.0)

    def __init__(self, store: social_store.SocialStore | None = None) -> None:
        self._store = store or social_store.get_store()
        self._limiter = _RateLimiter(*self.rate_limit)

    # --- subclass surface -------------------------------------------------
    def auth_state(self) -> AuthState:
        raise NotImplementedError

    def _do_publish(self, item: dict[str, Any]) -> PublishResult:
        raise NotImplementedError

    def _do_verify(self, post_id: str) -> tuple[bool, dict[str, Any]]:
        raise NotImplementedError

    def fetch_post_metrics(self, post_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def fetch_account_metrics(self) -> dict[str, Any]:
        raise NotImplementedError

    # --- shared behaviour -------------------------------------------------
    def guard(self) -> tuple[bool, str]:
        """Every reason this adapter must not make a call right now."""
        if control.kill_switch_active():
            return False, "SOCIAL_AUTOMATION_KILL_SWITCH is active"
        if not control.platform_enabled(self.platform):
            return False, f"{self.platform} is not enabled"
        allowed, wait = self._limiter.check()
        if not allowed:
            return False, (f"{self.platform} rate limit reached; "
                           f"retry in {wait:.0f}s")
        state = self.auth_state()
        if not state.connected:
            return False, f"{self.platform}: {state.detail or state.state}"
        return True, "ready"

    def publish(self, item: dict[str, Any]) -> PublishResult:
        """Publish, then confirm. Never one without the other."""
        # Dry run is checked first and unconditionally: no network call.
        if control.dry_run():
            self._store.audit(f"{self.platform}Adapter", "publish_simulated",
                              platform=self.platform,
                              target=str(item.get("content_id", "")),
                              result="SOCIAL_DRY_RUN is on; nothing was sent")
            return PublishResult(
                ok=True, verified=False, simulated=True,
                detail=("SOCIAL_DRY_RUN is on. The post was fully prepared and "
                        "NOT sent to the platform."))

        ready, reason = self.guard()
        if not ready:
            return PublishResult(ok=False, error=reason, detail=reason)

        attempts = int(item.get("attempts") or 0)
        if attempts >= MAX_PUBLISH_ATTEMPTS:
            reason = (f"already attempted {attempts} times; not retrying. "
                      f"Publishing failures are reported, not repeated forever.")
            self._store.audit(f"{self.platform}Adapter", "publish_abandoned",
                              platform=self.platform,
                              target=str(item.get("content_id", "")),
                              error=reason)
            return PublishResult(ok=False, error=reason, detail=reason)

        self._limiter.record()
        try:
            result = self._do_publish(item)
        except RateLimitError as exc:
            return PublishResult(ok=False, error=f"rate limited: {exc}")
        except Exception as exc:  # noqa: BLE001
            self._store.audit(f"{self.platform}Adapter", "publish_error",
                              platform=self.platform,
                              target=str(item.get("content_id", "")),
                              error=f"{type(exc).__name__}: {exc}")
            return PublishResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        # The second, separate question: is it actually there?
        if result.ok and result.post_id:
            try:
                verified, payload = self._do_verify(result.post_id)
                result.verified = verified
                if verified:
                    result.detail = (f"{result.detail} Publication verified: the "
                                     f"platform returned the post when asked for "
                                     f"it by id.").strip()
                    result.response.update(payload)
                else:
                    result.detail = (
                        f"{result.detail} The platform accepted the post but did "
                        f"NOT return it when asked. Recorded as PUBLISHING, not "
                        f"PUBLISHED.").strip()
            except Exception as exc:  # noqa: BLE001
                result.verified = False
                result.detail = (f"{result.detail} Verification could not run "
                                 f"({type(exc).__name__}); not claiming "
                                 f"publication.").strip()

        self._store.audit(
            f"{self.platform}Adapter", "publish",
            platform=self.platform, target=str(item.get("content_id", "")),
            result=result.status, error=result.error)
        return result

    def health(self) -> dict[str, Any]:
        """One platform's line in the health monitor."""
        if not control.platform_enabled(self.platform):
            state = OFFLINE
            detail = f"{self.platform} is disabled"
        else:
            allowed, wait = self._limiter.check()
            auth = self.auth_state()
            if not auth.connected and auth.state == NOT_CONFIGURED:
                state, detail = NOT_CONFIGURED, auth.detail
            elif not auth.connected:
                state, detail = AUTH_REQUIRED, auth.detail
            elif not allowed:
                state, detail = RATE_LIMITED, f"retry in {wait:.0f}s"
            else:
                state, detail = HEALTHY, auth.detail or "connected"
        return {"platform": self.platform, "state": state, "detail": detail,
                "rate_limit": self._limiter.snapshot(),
                "dry_run": control.dry_run()}
