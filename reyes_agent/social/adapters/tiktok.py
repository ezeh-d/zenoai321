"""TikTok, through the official Content Posting API.

WHAT THIS NEEDS AND CANNOT OBTAIN BY ITSELF
-------------------------------------------
    * a TikTok for Developers app
    * the `video.publish` scope APPROVED (audited by TikTok, not instant)
    * `video.upload` and `user.info.basic` for the rest
    * an OAuth access token for the ZENO account

Scope approval is a review process with a human on the other side. Until it
completes, `video.upload` can put a video in the account's drafts but cannot
post it. That distinction matters and is reported rather than hidden.

THE UNAUDITED-CLIENT RULE
-------------------------
Before audit, TikTok forces every post from the API to private
(SELF_ONLY) regardless of what the request asks for. An adapter that ignores
this reports a successful public post that nobody can see. So
`_do_publish` reads the account's real posting capability first and states
the privacy level the platform will actually apply.

INIT THEN CHECK, NEVER INIT THEN ASSUME
---------------------------------------
Publishing is: initialise upload, transfer bytes, then poll status until
PUBLISH_COMPLETE. A `publish_id` is a receipt for a request, not a post.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from reyes_agent.social import store as social_store
from reyes_agent.social.adapters.base import (
    AUTH_REQUIRED, NOT_CONFIGURED, AuthState, PublishResult, SocialAdapter,
)

DEFAULT_BASE = "https://open.tiktokapis.com"
API_VERSION = "v2"

REQUIRED_SCOPES = ("user.info.basic", "video.upload", "video.publish")

# TikTok documents 6 posts per minute per user. Kept well under.
RATE_LIMIT = (4, 60.0)

STATUS_TIMEOUT_S = 300.0
STATUS_POLL_S = 5.0

# TikTok's own chunk minimum is 5 MB.
CHUNK_SIZE = 10 * 1024 * 1024


def _secret(name: str) -> str:
    try:
        from reyes_agent.security.secrets import manager
        value = manager.get(name, "")
        if value:
            return value
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(name, "").strip()


class TikTokAPIAdapter(SocialAdapter):
    platform = social_store.TIKTOK
    rate_limit = RATE_LIMIT

    def __init__(self, store: social_store.SocialStore | None = None,
                 *, timeout: float = 60.0) -> None:
        super().__init__(store)
        self.timeout = timeout

    @property
    def base(self) -> str:
        return os.environ.get("TIKTOK_API_BASE", DEFAULT_BASE).rstrip("/")

    @property
    def token(self) -> str:
        return _secret("TIKTOK_ACCESS_TOKEN")

    def _request(self, path: str, *, body: dict[str, Any] | None = None,
                 method: str = "GET", query: str = "") -> dict[str, Any]:
        url = f"{self.base}/{API_VERSION}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            url, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json; charset=UTF-8"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8") or "{}")
            except (ValueError, OSError):
                payload = {}
            message = (payload.get("error", {}) or {}).get("message") or f"HTTP {exc.code}"
            raise RuntimeError(f"TikTok API: {message}") from None

        error = payload.get("error") or {}
        # TikTok returns 200 with an error object inside. Treating that as
        # success is exactly how a publisher claims posts it never made.
        if error and str(error.get("code", "ok")).lower() not in {"ok", ""}:
            raise RuntimeError(f"TikTok API: {error.get('message') or error.get('code')}")
        return payload

    # --- auth -------------------------------------------------------------
    def auth_state(self) -> AuthState:
        if not self.token:
            return AuthState(
                connected=False, state=NOT_CONFIGURED,
                detail=("not configured -- missing TIKTOK_ACCESS_TOKEN. See "
                        "ZENO_TIKTOK_SETUP.md; this needs a TikTok for "
                        "Developers app with video.publish approved, which is "
                        "a human review process."))
        try:
            data = self._request(
                "user/info/", method="GET",
                query="fields=open_id,union_id,display_name,follower_count")
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            self._store.upsert_account(self.platform, token_state="INVALID",
                                       last_error=detail[:200], connected=0)
            return AuthState(connected=False, state=AUTH_REQUIRED, detail=detail)

        user = (data.get("data") or {}).get("user") or {}
        self._store.upsert_account(
            self.platform, account_id=str(user.get("open_id", "")),
            username=str(user.get("display_name", "")),
            display_name=str(user.get("display_name", "")),
            account_type="CREATOR", token_state="VALID",
            last_success=time.time(), last_error="", connected=1,
            scopes=list(REQUIRED_SCOPES))
        return AuthState(
            connected=True, state="CONNECTED",
            account_id=str(user.get("open_id", "")),
            username=str(user.get("display_name", "")), scopes=REQUIRED_SCOPES,
            detail=f"{user.get('display_name', '')} "
                   f"({user.get('follower_count', 0)} followers)")

    def posting_capability(self) -> dict[str, Any]:
        """What TikTok will ACTUALLY allow this client to do."""
        try:
            data = self._request("post/publish/creator_info/query/", method="POST",
                                 body={})
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        info = data.get("data") or {}
        return {
            "privacy_options": info.get("privacy_level_options") or [],
            "max_duration_s": info.get("max_video_post_duration_sec"),
            "nickname": info.get("creator_nickname"),
            "comment_disabled": info.get("comment_disabled"),
        }

    # --- publishing -------------------------------------------------------
    def _do_publish(self, item: dict[str, Any]) -> PublishResult:
        media_path = str(item.get("media_path") or "").strip()
        if not media_path or not Path(media_path).exists():
            return PublishResult(
                ok=False,
                error=f"media file not found: {media_path or '(none)'}")

        size = Path(media_path).stat().st_size
        if size <= 0:
            return PublishResult(ok=False, error="media file is empty")

        capability = self.posting_capability()
        if "error" in capability:
            return PublishResult(
                ok=False,
                error=f"could not read posting capability: {capability['error']}")

        options = capability.get("privacy_options") or []
        wanted = str(item.get("privacy") or "PUBLIC_TO_EVERYONE")
        if wanted not in options:
            # Not an error -- it is the platform's answer. Saying it out loud
            # prevents claiming a public post that TikTok made private.
            fallback = "SELF_ONLY" if "SELF_ONLY" in options else (
                options[0] if options else "SELF_ONLY")
            note = (f"{wanted} is not available to this client "
                    f"(TikTok offers {options or 'nothing'}); posting as {fallback}")
            wanted = fallback
        else:
            note = f"posting as {wanted}"

        caption = str(item.get("caption") or "")
        tags = item.get("hashtags") or []
        if tags:
            caption = f"{caption} {' '.join(tags)}".strip()

        init = self._request("post/publish/video/init/", method="POST", body={
            "post_info": {
                "title": caption[:2200],
                "privacy_level": wanted,
                "disable_duet": False, "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {
                "source": "FILE_UPLOAD", "video_size": size,
                "chunk_size": min(CHUNK_SIZE, size), "total_chunk_count": 1,
            },
        })
        data = init.get("data") or {}
        publish_id = str(data.get("publish_id") or "")
        upload_url = str(data.get("upload_url") or "")
        if not publish_id or not upload_url:
            return PublishResult(ok=False,
                                 error=f"init returned no upload target: {data}")

        try:
            self._upload(upload_url, Path(media_path), size)
        except Exception as exc:  # noqa: BLE001
            return PublishResult(ok=False,
                                 error=f"upload failed: {type(exc).__name__}: {exc}",
                                 response={"publish_id": publish_id})

        # A publish_id is a receipt, not a post.
        final, detail = self._await_publish(publish_id)
        if not final:
            return PublishResult(
                ok=False, error=f"publish did not complete: {detail}",
                response={"publish_id": publish_id})

        return PublishResult(
            ok=True, post_id=publish_id,
            detail=f"TikTok reported PUBLISH_COMPLETE; {note}.",
            response={"publish_id": publish_id, "privacy": wanted})

    def _upload(self, url: str, path: Path, size: int) -> None:
        payload = path.read_bytes()
        request = urllib.request.Request(
            url, data=payload, method="PUT",
            headers={"Content-Type": "video/mp4",
                     "Content-Length": str(size),
                     "Content-Range": f"bytes 0-{size - 1}/{size}"})
        with urllib.request.urlopen(request, timeout=max(self.timeout, 300.0)) as r:
            if r.status not in (200, 201, 204):
                raise RuntimeError(f"upload returned HTTP {r.status}")

    def _await_publish(self, publish_id: str) -> tuple[bool, str]:
        deadline = time.time() + STATUS_TIMEOUT_S
        last = "unknown"
        while time.time() < deadline:
            try:
                data = self._request("post/publish/status/fetch/", method="POST",
                                     body={"publish_id": publish_id})
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)
            status = (data.get("data") or {})
            last = str(status.get("status") or "unknown")
            if last == "PUBLISH_COMPLETE":
                return True, last
            if last in {"FAILED", "PUBLISH_FAILED"}:
                return False, f"{last}: {status.get('fail_reason', '')}"
            time.sleep(STATUS_POLL_S)
        return False, f"still {last} after {STATUS_TIMEOUT_S:.0f}s"

    def _do_verify(self, post_id: str) -> tuple[bool, dict[str, Any]]:
        """Confirm with a fresh status read, not with the publish response."""
        data = self._request("post/publish/status/fetch/", method="POST",
                             body={"publish_id": post_id})
        status = (data.get("data") or {})
        return str(status.get("status")) == "PUBLISH_COMPLETE", status

    # --- analytics --------------------------------------------------------
    def fetch_post_metrics(self, post_id: str) -> dict[str, Any]:
        """Requires video.list scope; returns only what TikTok gives back."""
        try:
            data = self._request(
                "video/query/", method="POST",
                query="fields=id,view_count,like_count,comment_count,share_count",
                body={"filters": {"video_ids": [post_id]}})
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        videos = (data.get("data") or {}).get("videos") or []
        if not videos:
            return {"error": "no video returned for that id"}
        video = videos[0]
        return {"views": video.get("view_count"), "likes": video.get("like_count"),
                "comments": video.get("comment_count"),
                "shares": video.get("share_count")}

    def fetch_account_metrics(self) -> dict[str, Any]:
        try:
            data = self._request(
                "user/info/", method="GET",
                query="fields=follower_count,following_count,likes_count,video_count")
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        user = (data.get("data") or {}).get("user") or {}
        return {"followers": user.get("follower_count"),
                "following": user.get("following_count"),
                "likes": user.get("likes_count"),
                "videos": user.get("video_count")}
