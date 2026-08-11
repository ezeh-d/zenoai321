"""Who owns this footage, and what the owner is actually allowed to do with it.

THE BRIEF CALLS THIS MANDATORY, AND IT IS THE RIGHT CALL
--------------------------------------------------------
Every other part of a creative studio makes things faster. This is the part
that decides whether ZENO is a production tool or a piracy tool, and the
difference is one refusal:

    "Take 10 minutes from this anime and upload it."

A system that says yes to that is a reposting engine with a nice UI. So
rights are recorded per asset, checked before publication, and UNKNOWN is
never treated as permission.

THE DEFAULT IS THE WHOLE DESIGN
-------------------------------
An asset nobody classified is UNKNOWN_RIGHTS, and UNKNOWN_RIGHTS cannot be
published. Not "warn and continue" -- refused, with the rights-compliant
alternatives offered instead. Failing open here would mean the safety
property only holds for people who remember to use it.

WHAT ZENO WILL NEVER DO
-----------------------
Download full copyrighted works, rip a streaming service, circumvent DRM,
remove a watermark, or present someone else's work as original. Those are
not gated behind a permission flag, because there is no configuration in
which they are the right answer.

TRANSFORMATION IS NOT A LOOPHOLE
--------------------------------
Commentary, review and criticism are genuinely different uses, and ZENO can
help make them. But "add a webcam and call it a reaction" is republication
wearing a hat, so `transformative_plan()` requires the original material to
be a MINORITY of the runtime and the commentary to be substantial. It
describes what would be defensible; it does not rule on the law, and it
says so.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

# Rights classifications, exactly as the brief lists them.
OWNER_CREATED = "OWNER_CREATED"
USER_LICENSED = "USER_LICENSED"
PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
CREATIVE_COMMONS = "CREATIVE_COMMONS"
RIGHTS_CLEARED = "RIGHTS_CLEARED"
UNKNOWN_RIGHTS = "UNKNOWN_RIGHTS"
THIRD_PARTY_COPYRIGHTED = "THIRD_PARTY_COPYRIGHTED"

CLASSIFICATIONS = (OWNER_CREATED, USER_LICENSED, PUBLIC_DOMAIN, CREATIVE_COMMONS,
                   RIGHTS_CLEARED, UNKNOWN_RIGHTS, THIRD_PARTY_COPYRIGHTED)

# Only these may be published as-is.
PUBLISHABLE = frozenset({OWNER_CREATED, USER_LICENSED, PUBLIC_DOMAIN,
                         CREATIVE_COMMONS, RIGHTS_CLEARED})

# These require the owner to say what the rights are before anything happens.
NEEDS_PROOF = frozenset({UNKNOWN_RIGHTS, THIRD_PARTY_COPYRIGHTED})

# For a use to read as commentary rather than republication, the borrowed
# material has to be the minority of it. Not a legal test -- a sanity floor.
MAX_BORROWED_RATIO = 0.33
MIN_ORIGINAL_SECONDS = 15.0

# Titles that are almost always somebody's protected work. Used to CHALLENGE
# an OWNER_CREATED claim, never to classify on its own.
_LIKELY_PROTECTED = (
    "episode", "season", "s01e", "s02e", "full movie", "official trailer",
    "ost", "soundtrack", "netflix", "disney", "crunchyroll", "hbo", "prime video",
    "bluray", "blu-ray", "webrip", "hdrip", "camrip", "dvdrip", "x264", "x265",
)

_lock = threading.RLock()
_cache: dict[str, dict[str, Any]] | None = None


@dataclass
class Asset:
    asset_id: str
    path: str = ""
    source: str = ""
    owner: str = ""
    classification: str = UNKNOWN_RIGHTS
    license: str = ""
    commercial_allowed: bool = False
    social_post_allowed: bool = False
    attribution_required: bool = False
    attribution_text: str = ""
    expires_at: float = 0.0
    evidence: str = ""            # where the right comes from
    declared_by: str = ""
    at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return bool(self.expires_at) and time.time() > self.expires_at

    @property
    def publishable(self) -> bool:
        return self.classification in PUBLISHABLE and not self.expired

    def as_dict(self) -> dict[str, Any]:
        return {"asset_id": self.asset_id, "path": self.path, "source": self.source,
                "owner": self.owner, "classification": self.classification,
                "license": self.license, "commercial_allowed": self.commercial_allowed,
                "social_post_allowed": self.social_post_allowed,
                "attribution_required": self.attribution_required,
                "attribution_text": self.attribution_text,
                "expires_at": self.expires_at or None, "expired": self.expired,
                "publishable": self.publishable, "evidence": self.evidence,
                "declared_by": self.declared_by, "at": self.at}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Asset":
        return cls(**{k: v for k, v in raw.items()
                      if k in cls.__dataclass_fields__ and v is not None})


def asset_id_for(path: str | Path) -> str:
    """Stable id from the path, so re-registering the same file is idempotent."""
    return hashlib.sha256(str(path).strip().lower().encode("utf-8")).hexdigest()[:16]


def _path() -> Path:
    return Path(config.VAULT_PATH) / "07-System" / "creative" / "rights.json"


def _load() -> dict[str, dict[str, Any]]:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = _path()
        try:
            _cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            _cache = {}
        return _cache


def _save() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(_load(), handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def declare(path: str | Path, classification: str, *, owner: str = "",
            source: str = "", license: str = "", evidence: str = "",
            commercial: bool = False, social: bool = False,
            attribution: str = "", expires_at: float = 0.0,
            declared_by: str = "owner") -> tuple[Asset | None, str]:
    """Record what the owner says the rights are.

    A claim of OWNER_CREATED over something that looks like a commercial
    release is QUESTIONED rather than accepted. Nobody's home footage is
    called `S01E04.1080p.WEB-DL.x265.mkv`, and quietly accepting that claim
    is how a rights engine becomes decorative.
    """
    if classification not in CLASSIFICATIONS:
        return None, f"'{classification}' is not a rights classification I know"

    text = f"{path} {source}".lower()
    suspicious = [m for m in _LIKELY_PROTECTED if m in text]
    if suspicious and classification in (OWNER_CREATED, PUBLIC_DOMAIN):
        return None, (
            f"That file looks like a commercial release ({', '.join(suspicious[:3])}), "
            f"so I am not going to record it as {classification} on my own. If you do "
            "hold the rights, tell me what they are -- a licence, a written permission, "
            "or the agreement it comes under -- and I will record that instead.")

    if classification in NEEDS_PROOF:
        commercial = social = False        # never publishable, whatever was passed

    asset = Asset(asset_id=asset_id_for(path), path=str(path), source=source,
                  owner=owner, classification=classification, license=license,
                  commercial_allowed=bool(commercial),
                  social_post_allowed=bool(social),
                  attribution_required=bool(attribution),
                  attribution_text=attribution, expires_at=float(expires_at or 0.0),
                  evidence=evidence, declared_by=declared_by)
    with _lock:
        _load()[asset.asset_id] = asset.as_dict()
        _save()
    return asset, f"recorded as {classification}"


def get(path_or_id: str | Path) -> Asset | None:
    key = str(path_or_id)
    raw = _load().get(key) or _load().get(asset_id_for(key))
    return Asset.from_dict(raw) if raw else None


def classify(path: str | Path) -> Asset:
    """What ZENO knows about this file. Unregistered means UNKNOWN, always."""
    existing = get(path)
    if existing is not None:
        return existing
    return Asset(asset_id=asset_id_for(path), path=str(path),
                 classification=UNKNOWN_RIGHTS,
                 evidence="never declared -- ZENO has no idea who owns this")


def all_assets() -> list[Asset]:
    return [Asset.from_dict(raw) for raw in _load().values()]


def forget(path_or_id: str) -> bool:
    with _lock:
        key = asset_id_for(path_or_id) if len(str(path_or_id)) != 16 else str(path_or_id)
        if _load().pop(key, None) is None:
            return False
        _save()
    return True


def reset_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def status() -> dict[str, Any]:
    assets = all_assets()
    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.classification] = counts.get(asset.classification, 0) + 1
    return {
        "state": "ONLINE",
        "assets": len(assets),
        "by_classification": counts,
        "publishable": sum(1 for a in assets if a.publishable),
        "classifications": list(CLASSIFICATIONS),
        "default": UNKNOWN_RIGHTS,
        "note": ("An asset nobody classified is UNKNOWN_RIGHTS and cannot be "
                 "published. Failing open here would mean the protection only "
                 "works for people who remember to use it."),
        "never": ("download full copyrighted works, rip a streaming service, "
                  "circumvent DRM, remove a watermark, or present someone else's "
                  "work as original"),
    }
