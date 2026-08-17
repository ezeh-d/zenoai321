"""Authoritative speaker enrollment/verification coordinator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from reyes_agent.identity.speaker.embeddings import EmbeddingBackend, get_backend
from reyes_agent.identity.speaker.enrollment import MAX_CLIPS, MIN_CLIPS, build_profile
from reyes_agent.identity.speaker.profiles import ProfileError, ProfileStore
from reyes_agent.identity.speaker.thresholds import DEFAULT_THRESHOLDS, SpeakerThresholds
from reyes_agent.identity.speaker.verifier import verify


class SpeakerManager:
    def __init__(self, profile_path: Path, *, backend: EmbeddingBackend | None = None,
                 thresholds: SpeakerThresholds = DEFAULT_THRESHOLDS) -> None:
        self.store = ProfileStore(profile_path)
        self.backend = backend or get_backend()
        self.thresholds = thresholds

    def status(self) -> dict[str, Any]:
        backend = self.backend.status()
        try:
            profile = self.store.load()
        except ProfileError as exc:
            return {"enrolled": False, "required_clips": MIN_CLIPS, "stored_audio": False,
                    "backend": backend, "error": str(exc)}
        if not profile:
            return {"enrolled": False, "required_clips": MIN_CLIPS, "maximum_clips": MAX_CLIPS,
                    "stored_audio": False, "backend": backend,
                    "security_note": "No model-backed owner voice profile exists yet."}
        return {"enrolled": True, "enrolled_at": profile.get("enrolled_at"),
                "clips": profile.get("clips"), "stored_audio": False,
                "protection": "Windows DPAPI (current Windows user)",
                "model": profile.get("backend"), "backend": backend,
                "thresholds": self.thresholds.__dict__,
                "accuracy": "NOT_MEASURED_WITH_OWNER_AND_IMPOSTOR_AUDIO",
                "limitation": "Voice evidence is not authentication or spoof-proof."}

    def enroll(self, clips: list[bytes]) -> dict[str, Any]:
        if self.backend.status().get("state") != "READY":
            raise ValueError(f"Speaker model is not ready: {self.backend.status().get('state')}")
        profile = build_profile(clips, self.backend)
        self.store.save(profile)
        return {"ok": True, **self.status()}

    def identify(self, audio: bytes) -> dict[str, Any]:
        try:
            profile = self.store.load()
        except ProfileError as exc:
            return {"status": "NO_PROFILE", "confidence": None, "reason": str(exc),
                    "stored_audio": False, "model": self.backend.name}
        if not profile:
            return {"status": "NO_PROFILE", "confidence": None,
                    "reason": "Divine has not enrolled a model-backed voice profile.",
                    "stored_audio": False, "model": self.backend.name}
        try:
            return verify(audio, profile, self.backend, self.thresholds)
        except Exception as exc:
            return {"status": "INSUFFICIENT_AUDIO", "confidence": None,
                    "reason": str(exc), "stored_audio": False, "model": self.backend.name}

    def delete(self) -> dict[str, Any]:
        return {"ok": True, "deleted": self.store.delete(), "stored_audio": False}

    def fingerprint(self) -> str:
        profile = self.store.load()
        if not profile:
            return ""
        return hashlib.sha256(json.dumps(profile["centroid"]).encode()).hexdigest()[:12]

