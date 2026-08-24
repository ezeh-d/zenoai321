"""One local ALLOW/DENY/ASK decision over identity, device and consent."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from reyes_agent import config, permissions
from reyes_agent.conversation.consent import ConsentStateManager

ALLOW, DENY, ASK = "ALLOW", "DENY", "ASK"
OWNER, TRUSTED, TEMPORARY, UNTRUSTED, REVOKED = (
    "OWNER", "TRUSTED", "TEMPORARY", "UNTRUSTED", "REVOKED")
READ, LOW_RISK, EXTERNAL_COMMUNICATION, FILE_WRITE, SYSTEM_CHANGE, ADMIN, FINANCIAL, SENSITIVE = (
    "READ", "LOW_RISK", "EXTERNAL_COMMUNICATION", "FILE_WRITE", "SYSTEM_CHANGE",
    "ADMIN", "FINANCIAL", "SENSITIVE")

_PATH = config.VAULT_PATH / "07-System" / "permissions" / "device_trust.json"


class DeviceTrustManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _PATH
        self._lock = threading.RLock()
        self._trust = {"laptop": OWNER}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._trust.update({str(k): str(v) for k, v in raw.items()
                                    if v in {OWNER, TRUSTED, TEMPORARY, UNTRUSTED, REVOKED}})
        except (OSError, ValueError, TypeError):
            pass

    def set(self, device: str, trust: str) -> None:
        if trust not in {OWNER, TRUSTED, TEMPORARY, UNTRUSTED, REVOKED}:
            raise ValueError("unknown device trust")
        with self._lock:
            self._trust[str(device)] = trust
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._trust, indent=2), encoding="utf-8")
            temporary.replace(self.path)

    def get(self, device: str) -> str:
        with self._lock:
            return self._trust.get(str(device), UNTRUSTED)

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._trust)


class PermissionEngine:
    _CONSENT = {
        "microphone": "audio_processing", "meeting_transcription": "transcript_retention",
        "recording": "recording", "camera": "camera", "speaker_enrollment": "speaker_enrollment",
        "screen_streaming": "screen_streaming", "remote_control": "remote_control",
        "memory_retention": "memory_retention",
    }

    def __init__(self, trust: DeviceTrustManager | None = None) -> None:
        self.devices = trust or DeviceTrustManager()

    def evaluate(self, *, action_class: str, tool: str = "", device: str = "laptop",
                 consent: str = "") -> dict[str, Any]:
        trust = self.devices.get(device)
        if trust == REVOKED or action_class == FINANCIAL:
            return {"decision": DENY, "reason": "device revoked" if trust == REVOKED else "financial execution blocked"}
        if trust == UNTRUSTED and action_class != READ:
            return {"decision": DENY, "reason": "untrusted device cannot perform side effects"}
        if consent:
            from reyes_agent.conversation.consent import get_consent
            flag = self._CONSENT.get(consent, consent)
            if not get_consent().allowed(flag):
                return {"decision": ASK, "reason": f"{consent} consent is not active"}
        state = permissions.check(tool) if tool else permissions.ENABLED
        if state == permissions.BLOCKED:
            return {"decision": DENY, "reason": "permission policy blocks this action"}
        if state == permissions.CONFIRM or action_class in {ADMIN, SENSITIVE} or trust == TEMPORARY:
            return {"decision": ASK, "reason": "explicit owner confirmation required"}
        return {"decision": ALLOW, "reason": "local policy allows this action"}


_engine: PermissionEngine | None = None


def get_permission_engine() -> PermissionEngine:
    global _engine
    if _engine is None:
        _engine = PermissionEngine()
    return _engine
