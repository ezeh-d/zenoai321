"""Instagram, through the current "Instagram API with Instagram Login".

This talks to graph.instagram.com (NOT graph.facebook.com) and does not need a
linked Facebook Page. The OAuth login, code exchange and token storage live in
reyes_agent/social/instagram_login.py; this adapter reads the token + Instagram
user id that flow stores and does the reading/publishing.

WHAT THIS NEEDS BEFORE IT CAN DO ANYTHING (and cannot obtain by itself)
-----------------------------------------------------------------------
    * an Instagram PROFESSIONAL account (Creator or Business)
    * a Meta app configured for "Instagram API with Instagram Login" with
      instagram_business_basic + instagram_business_content_publish
    * an Instagram User access token (obtained by the OAuth callback)

The account + app cannot be created programmatically -- they need a human in
Meta's console. `auth_state()` reports exactly which piece is missing rather
than failing at publish time with a confusing 400. See ZENO_INSTAGRAM_SETUP.md.

THE TWO-STEP PUBLISH IS NOT OPTIONAL
------------------------------------
Graph publishing is: create a media container, then publish the container.
A container that exists is not a post. For Reels the container also has to
FINISH PROCESSING first, so this polls `status_code` until FINISHED and
refuses to publish an IN_PROGRESS container -- which is the most common way
an automated Instagram publisher silently produces nothing.

MEDIA MUST BE PUBLICLY REACHABLE
--------------------------------
Graph fetches the video from a URL; it does not accept an upload from this
process. A local file path cannot be published, and saying so early is more
useful than a 400 from Meta.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from reyes_agent import config
from reyes_agent.social import store as social_store
from reyes_agent.social.adapters.base import (
    AUTH_REQUIRED, NOT_CONFIGURED, AuthState, PublishResult, SocialAdapter,
)

DEFAULT_API_VERSION = "v23.0"
# The current "Instagram API with Instagram Login" is reached on
# graph.instagram.com, NOT graph.facebook.com. Both are overridable via config
# so a future migration never needs a code change here.
GRAPH = config.INSTAGRAM_GRAPH_BASE

# Meta's documented limit is 100 API-published posts per 24 hours per account.
# Kept well below it so ZENO never becomes the reason an account is throttled.
PUBLISH_LIMIT_PER_DAY = 20

# Scopes for the initial posting integration (Instagram Login). Messaging and
# comments permissions are intentionally NOT requested here.
REQUIRED_SCOPES = ("instagram_business_basic",
                   "instagram_business_content_publish")

# How long to wait for a Reel container to finish processing.
CONTAINER_TIMEOUT_S = 180.0
CONTAINER_POLL_S = 5.0


def _secret(name: str) -> str:
    """Keyring first, environment second. Never logged either way."""
    try:
        from reyes_agent.security.secrets import manager
        value = manager.get(name, "")
        if value:
            return value
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get(name, "").strip()


class InstagramAPIAdapter(SocialAdapter):
    platform = social_store.INSTAGRAM
    rate_limit = (PUBLISH_LIMIT_PER_DAY, 86400.0)

    def __init__(self, store: social_store.SocialStore | None = None,
                 *, timeout: float = 30.0) -> None:
        super().__init__(store)
        self.timeout = timeout

    # --- configuration ----------------------------------------------------
    @property
    def api_version(self) -> str:
        return os.environ.get("INSTAGRAM_API_VERSION", DEFAULT_API_VERSION)

    @property
    def token(self) -> str:
        return _secret("INSTAGRAM_ACCESS_TOKEN")

    @property
    def account_id(self) -> str:
        return _secret("INSTAGRAM_BUSINESS_ACCOUNT_ID")

    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.api_version}/{path.lstrip('/')}"

    def _request(self, path: str, *, params: dict[str, Any] | None = None,
                 method: str = "GET") -> dict[str, Any]:
        payload = dict(params or {})
        payload["access_token"] = self.token
        encoded = urllib.parse.urlencode(payload).encode()

        if method == "GET":
            request = urllib.request.Request(f"{self._url(path)}?{encoded.decode()}")
        else:
            request = urllib.request.Request(self._url(path), data=encoded,
                                             method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8") or "{}")
            except (ValueError, OSError):
                body = {}
            error = body.get("error", {})
            message = error.get("message", f"HTTP {exc.code}")
            # The token itself must never enter a message that gets stored.
            raise RuntimeError(f"Instagram API: {message}") from None

    # --- auth -------------------------------------------------------------
    def auth_state(self) -> AuthState:
        missing = []
        if not self.token:
            missing.append("INSTAGRAM_ACCESS_TOKEN")
        if not self.account_id:
            missing.append("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        if missing:
            return AuthState(
                connected=False, state=NOT_CONFIGURED,
                detail=(f"not configured -- missing {', '.join(missing)}. "
                        f"See ZENO_INSTAGRAM_SETUP.md; this needs a Meta app "
                        f"and an Instagram Professional account, which cannot "
                        f"be created automatically."))
        try:
            data = self._request(self.account_id, params={
                "fields": "id,username,account_type,name,"
                          "followers_count,media_count"})
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            self._store.upsert_account(self.platform, token_state="INVALID",
                                       last_error=detail[:200], connected=0)
            return AuthState(connected=False, state=AUTH_REQUIRED, detail=detail)

        self._store.upsert_account(
            self.platform, account_id=str(data.get("id") or self.account_id),
            username=str(data.get("username", "")),
            display_name=str(data.get("name", "")),
            account_type=str(data.get("account_type") or "PROFESSIONAL").upper(),
            token_state="VALID",
            last_success=time.time(), last_error="", connected=1,
            scopes=list(REQUIRED_SCOPES))
        return AuthState(
            connected=True, state="CONNECTED", account_id=str(data.get("id", "")),
            username=str(data.get("username", "")), scopes=REQUIRED_SCOPES,
            detail=f"@{data.get('username', '')} "
                   f"({data.get('followers_count', 0)} followers)")

    # --- publishing -------------------------------------------------------
    def _do_publish(self, item: dict[str, Any]) -> PublishResult:
        media_url = str(item.get("media_url") or "").strip()
        if not media_url:
            local = str(item.get("media_path") or "")
            return PublishResult(
                ok=False,
                error=("no media_url. The Graph API fetches media from a public "
                       "URL -- it cannot accept a local file"
                       + (f" ({local})" if local else "") +
                       ". Host the file and set media_url."))
        if not media_url.lower().startswith("https://"):
            return PublishResult(
                ok=False, error="media_url must be https and publicly reachable")

        caption = str(item.get("caption") or "")
        tags = item.get("hashtags") or []
        if tags:
            caption = f"{caption}\n\n{' '.join(tags)}".strip()

        is_video = str(item.get("media_type") or "").lower() in {
            "video", "reel", "reels", "mp4"}

        params: dict[str, Any] = {"caption": caption[:2200]}
        if is_video:
            params["media_type"] = "REELS"
            params["video_url"] = media_url
        else:
            params["image_url"] = media_url

        container = self._request(f"{self.account_id}/media", params=params,
                                  method="POST")
        container_id = str(container.get("id") or "")
        if not container_id:
            return PublishResult(ok=False,
                                 error=f"no container id returned: {container}")

        # A container is not a post. Video containers must finish processing,
        # and publishing an unfinished one produces nothing while returning
        # an id that looks like success.
        if is_video:
            ready, detail = self._await_container(container_id)
            if not ready:
                return PublishResult(
                    ok=False, error=f"media container never became publishable: {detail}",
                    response={"container_id": container_id})

        published = self._request(f"{self.account_id}/media_publish",
                                  params={"creation_id": container_id},
                                  method="POST")
        post_id = str(published.get("id") or "")
        if not post_id:
            return PublishResult(ok=False,
                                 error=f"publish returned no id: {published}",
                                 response={"container_id": container_id})

        return PublishResult(
            ok=True, post_id=post_id,
            detail="Instagram accepted the post.",
            response={"container_id": container_id, "id": post_id})

    def _await_container(self, container_id: str) -> tuple[bool, str]:
        deadline = time.time() + CONTAINER_TIMEOUT_S
        last = "unknown"
        while time.time() < deadline:
            data = self._request(container_id, params={"fields": "status_code,status"})
            last = str(data.get("status_code") or data.get("status") or "unknown")
            if last == "FINISHED":
                return True, last
            if last in {"ERROR", "EXPIRED"}:
                return False, f"{last}: {data.get('status', '')}"
            time.sleep(CONTAINER_POLL_S)
        return False, f"still {last} after {CONTAINER_TIMEOUT_S:.0f}s"

    def _do_verify(self, post_id: str) -> tuple[bool, dict[str, Any]]:
        """Ask Instagram for the post by id. Presence is the confirmation."""
        data = self._request(post_id, params={
            "fields": "id,permalink,media_type,timestamp"})
        return bool(data.get("id")), data

    # --- analytics --------------------------------------------------------
    def fetch_post_metrics(self, post_id: str) -> dict[str, Any]:
        """Only metrics Instagram actually returns. Nothing is invented."""
        metrics = ("reach,likes,comments,saved,shares,views,total_interactions")
        try:
            data = self._request(f"{post_id}/insights", params={"metric": metrics})
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        out: dict[str, Any] = {}
        for entry in data.get("data", []):
            name = entry.get("name")
            values = entry.get("values") or [{}]
            if name:
                out[name] = values[0].get("value")
        return out

    def fetch_account_metrics(self) -> dict[str, Any]:
        try:
            data = self._request(self.account_id, params={
                "fields": "followers_count,media_count,username"})
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        return {"followers": data.get("followers_count"),
                "posts": data.get("media_count"),
                "username": data.get("username")}

    def recent_comments(self, post_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        try:
            data = self._request(f"{post_id}/comments", params={
                "fields": "id,text,username,timestamp", "limit": limit})
        except Exception:  # noqa: BLE001
            return []
        return list(data.get("data", []))
