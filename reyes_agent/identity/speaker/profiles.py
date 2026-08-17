"""DPAPI-protected local speaker embedding profile storage."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any


class ProfileError(ValueError):
    pass


def _protect(data: bytes) -> tuple[str, bytes]:
    if os.name == "nt":
        try:
            import win32crypt

            value = win32crypt.CryptProtectData(data, "ZENO Divine voice profile", None, None, None, 0)
            return "dpapi", bytes(value[1] if isinstance(value, tuple) else value)
        except Exception as exc:
            raise ProfileError(f"Windows could not protect the voice profile: {exc}") from exc
    return "plain-development", data


def _unprotect(data: bytes, mode: str) -> bytes:
    if mode != "dpapi":
        return data
    if os.name != "nt":
        raise ProfileError("This profile is protected for a Windows user and cannot be opened here.")
    try:
        import win32crypt

        value = win32crypt.CryptUnprotectData(data, None, None, None, 0)
        return bytes(value[1] if isinstance(value, tuple) else value)
    except Exception as exc:
        raise ProfileError("This Windows user cannot unlock the voice profile.") from exc


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any] | None:
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            raw = _unprotect(base64.b64decode(envelope["payload"]), str(envelope.get("protection", "")))
            profile = json.loads(raw.decode("utf-8"))
        except FileNotFoundError:
            return None
        except Exception as exc:
            if isinstance(exc, ProfileError):
                raise
            raise ProfileError(f"The voice profile cannot be read safely: {exc}") from exc
        if profile.get("format") != 2 or not isinstance(profile.get("centroid"), list):
            raise ProfileError("The existing voice profile uses the retired heuristic format; re-enrol Divine's voice.")
        return profile

    def save(self, profile: dict[str, Any]) -> None:
        raw = json.dumps(profile, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        protection, payload = _protect(raw)
        envelope = {"format": 2, "protection": protection, "payload": base64.b64encode(payload).decode("ascii")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(envelope), encoding="utf-8")
        temporary.replace(self.path)

    def delete(self) -> bool:
        existed = self.path.exists()
        self.path.unlink(missing_ok=True)
        return existed

