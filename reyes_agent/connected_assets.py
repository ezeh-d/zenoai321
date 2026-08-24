"""One registry for everything connected to ZENO, with capability TRUTH.

The brief's core rule: connect everything through one architecture, but NEVER
pretend a service exposes data it does not have (Gmail is not GPS). Each asset
TYPE has a fixed profile of what it can and -- explicitly -- cannot expose, so
`can_expose(gmail, "location")` is False by construction, not by hoping a caller
remembered. Presence/health are honest states; nothing here initiates tracking,
it only records what authorized adapters report. Thread-safe, never raises.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# Asset types (extensible).
PHONE = "PHONE"; LAPTOP = "LAPTOP"; DESKTOP = "DESKTOP"; TABLET = "TABLET"
WEB_SESSION = "WEB_SESSION"; GMAIL_ACCOUNT = "GMAIL_ACCOUNT"
GOOGLE_ACCOUNT = "GOOGLE_ACCOUNT"; EMAIL_ACCOUNT = "EMAIL_ACCOUNT"
SLACK_ACCOUNT = "SLACK_ACCOUNT"; DISCORD_ACCOUNT = "DISCORD_ACCOUNT"
TELEGRAM_ACCOUNT = "TELEGRAM_ACCOUNT"; WHATSAPP_CONNECTION = "WHATSAPP_CONNECTION"
GITHUB_ACCOUNT = "GITHUB_ACCOUNT"; BROWSER_PROFILE = "BROWSER_PROFILE"
ZENO_AGENT = "ZENO_AGENT"; ZENO_TOOL = "ZENO_TOOL"; ZENO_NODE = "ZENO_NODE"
REMOTE_SESSION = "REMOTE_SESSION"

# Authorization / connection / health states.
AUTHORIZED = "AUTHORIZED"; UNAUTHORIZED = "UNAUTHORIZED"; REVOKED = "REVOKED"
ONLINE = "ONLINE"; OFFLINE = "OFFLINE"; IDLE = "IDLE"; LAST_SEEN = "LAST_SEEN"
HEALTHY = "HEALTHY"; DEGRADED = "DEGRADED"; AUTH_REQUIRED = "AUTH_REQUIRED"
TOKEN_EXPIRED = "TOKEN_EXPIRED"; RATE_LIMITED = "RATE_LIMITED"
PERMISSION_MISSING = "PERMISSION_MISSING"; DISCONNECTED = "DISCONNECTED"

# What each asset TYPE can expose, and what it explicitly CANNOT. The `cannot`
# set is the anti-fabrication guard (Gmail is not a GPS).
_TYPE_CAPABILITIES: dict[str, dict[str, set[str]]] = {
    PHONE: {"can": {"location", "battery", "network", "presence", "notifications",
                    "commands", "last_seen"}, "cannot": set()},
    LAPTOP: {"can": {"presence", "health", "commands", "last_seen", "location"},
             "cannot": set()},
    DESKTOP: {"can": {"presence", "health", "commands", "last_seen"}, "cannot": set()},
    TABLET: {"can": {"presence", "commands", "last_seen"}, "cannot": set()},
    GMAIL_ACCOUNT: {"can": {"messages", "threads", "labels", "drafts", "send",
                            "mailbox_events"},
                    "cannot": {"location", "gps", "device_location", "battery"}},
    GOOGLE_ACCOUNT: {"can": {"sessions", "signed_in_devices", "security_events",
                             "last_activity"},
                     "cannot": {"gps", "precise_location", "mailbox_contents"}},
    EMAIL_ACCOUNT: {"can": {"messages", "send", "drafts"},
                    "cannot": {"location", "gps"}},
    SLACK_ACCOUNT: {"can": {"messages", "channels", "send", "mentions"},
                    "cannot": {"location", "gps"}},
    GITHUB_ACCOUNT: {"can": {"repos", "commits", "issues", "actions"},
                     "cannot": {"location", "gps"}},
    BROWSER_PROFILE: {"can": {"pages", "downloads", "automation"},
                      "cannot": {"passwords", "location"}},
    ZENO_AGENT: {"can": {"tasks", "status", "results"}, "cannot": {"gps"}},
    ZENO_TOOL: {"can": {"invocations", "status"}, "cannot": {"gps"}},
    ZENO_NODE: {"can": {"presence", "health", "commands", "last_seen"}, "cannot": set()},
    REMOTE_SESSION: {"can": {"status", "commands", "last_seen"}, "cannot": {"gps"}},
}


@dataclass
class ConnectedAsset:
    asset_id: str
    asset_type: str
    display_name: str = ""
    provider: str = ""
    owner: str = ""
    authorization_status: str = UNAUTHORIZED
    connection_status: str = OFFLINE
    health: str = HEALTHY
    last_seen: float = 0.0
    last_activity: float = 0.0
    device_id: str = ""
    account_id: str = ""
    declared: set[str] = field(default_factory=set)   # caps the adapter actually enabled

    def type_caps(self) -> dict[str, set[str]]:
        return _TYPE_CAPABILITIES.get(self.asset_type, {"can": set(), "cannot": set()})

    def can_expose(self, capability: str) -> bool:
        cap = str(capability or "").strip().casefold()
        caps = self.type_caps()
        if cap in caps["cannot"]:
            return False                       # the anti-fabrication guard
        if cap not in caps["can"]:
            return False                       # type simply doesn't have it
        if self.authorization_status != AUTHORIZED:
            return False                       # not authorized -> cannot expose
        return cap in self.declared            # adapter must have actually enabled it

    def as_dict(self) -> dict[str, Any]:
        caps = self.type_caps()
        return {
            "asset_id": self.asset_id, "asset_type": self.asset_type,
            "display_name": self.display_name, "provider": self.provider,
            "owner": self.owner, "authorization_status": self.authorization_status,
            "connection_status": self.connection_status, "health": self.health,
            "last_seen": self.last_seen, "last_activity": self.last_activity,
            "device_id": self.device_id, "account_id": self.account_id,
            "can_expose": sorted(c for c in caps["can"] if c in self.declared),
            "cannot_expose": sorted(caps["cannot"]),
        }


class ConnectedAssetRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._assets: dict[str, ConnectedAsset] = {}

    def register(self, asset_id: str, asset_type: str, *, display_name: str = "",
                 provider: str = "", owner: str = "", device_id: str = "",
                 account_id: str = "", authorized: bool = False,
                 capabilities: list[str] | None = None) -> ConnectedAsset:
        aid = str(asset_id or "").strip()
        atype = asset_type if asset_type in _TYPE_CAPABILITIES else asset_type
        declared = {str(c).strip().casefold() for c in (capabilities or [])}
        # Only capabilities the TYPE genuinely supports can be declared.
        supported = _TYPE_CAPABILITIES.get(atype, {"can": set()})["can"]
        declared &= supported
        with self._lock:
            asset = ConnectedAsset(
                asset_id=aid, asset_type=atype, display_name=display_name or aid,
                provider=provider, owner=owner, device_id=device_id,
                account_id=account_id,
                authorization_status=AUTHORIZED if authorized else UNAUTHORIZED,
                declared=declared)
            self._assets[aid] = asset
            return asset

    def can_expose(self, asset_id: str, capability: str) -> bool:
        with self._lock:
            asset = self._assets.get(str(asset_id or "").strip())
        return bool(asset and asset.can_expose(capability))

    def update_presence(self, asset_id: str, *, connection_status: str,
                        last_seen: float, last_activity: float | None = None) -> bool:
        with self._lock:
            asset = self._assets.get(str(asset_id or "").strip())
            if asset is None:
                return False
            asset.connection_status = connection_status
            asset.last_seen = float(last_seen)
            if last_activity is not None:
                asset.last_activity = float(last_activity)
            return True

    def set_health(self, asset_id: str, health: str) -> bool:
        with self._lock:
            asset = self._assets.get(str(asset_id or "").strip())
            if asset is None:
                return False
            asset.health = health
            return True

    def get(self, asset_id: str) -> dict[str, Any] | None:
        with self._lock:
            asset = self._assets.get(str(asset_id or "").strip())
            return asset.as_dict() if asset else None

    def dashboard(self) -> list[dict[str, Any]]:
        with self._lock:
            return [a.as_dict() for a in sorted(self._assets.values(),
                                                key=lambda x: (x.asset_type, x.display_name))]

    def by_type(self, asset_type: str) -> list[dict[str, Any]]:
        with self._lock:
            return [a.as_dict() for a in self._assets.values() if a.asset_type == asset_type]

    def forget(self, asset_id: str) -> bool:
        with self._lock:
            return self._assets.pop(str(asset_id or "").strip(), None) is not None


_instance: ConnectedAssetRegistry | None = None
_lock = threading.Lock()


def get_registry() -> ConnectedAssetRegistry:
    global _instance
    with _lock:
        if _instance is None:
            _instance = ConnectedAssetRegistry()
        return _instance
