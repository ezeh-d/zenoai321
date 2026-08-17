"""Four-band verification decisions from real speaker embeddings."""

from __future__ import annotations

from typing import Any

import numpy as np

from reyes_agent.identity.speaker.embeddings import EmbeddingBackend
from reyes_agent.identity.speaker.quality import analyse
from reyes_agent.identity.speaker.thresholds import SpeakerThresholds

OWNER_HIGH = "OWNER_HIGH"
OWNER_LIKELY = "OWNER_LIKELY"
UNCERTAIN = "UNCERTAIN"
UNKNOWN = "UNKNOWN"


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.clip(np.dot(left, right) / max(float(np.linalg.norm(left) * np.linalg.norm(right)), 1e-9), -1.0, 1.0))


def verify(audio: bytes, profile: dict[str, Any], backend: EmbeddingBackend,
           thresholds: SpeakerThresholds) -> dict[str, Any]:
    sample = analyse(audio)
    vector, inference_ms = backend.embed(sample)
    centroid = np.asarray(profile["centroid"], dtype=np.float32)
    centroid_similarity = _cosine(vector, centroid)
    references = [np.asarray(value, dtype=np.float32) for value in profile.get("references", [])]
    reference_scores = [_cosine(vector, value) for value in references]
    best_reference = max(reference_scores) if reference_scores else centroid_similarity
    # The centroid is stable across speaking styles; the closest reference
    # prevents a quiet/fast condition from being unfairly discarded.
    similarity = 0.75 * centroid_similarity + 0.25 * best_reference
    if sample.quality < thresholds.minimum_quality:
        status = UNCERTAIN
        reason = "Audio quality is too low for a trusted identity decision."
    elif similarity >= thresholds.high:
        status = OWNER_HIGH
        reason = "High speaker-model similarity to the enrolled owner profile."
    elif similarity >= thresholds.likely:
        status = OWNER_LIKELY
        reason = "Likely owner match; private data remains protected until confidence is high."
    elif similarity >= thresholds.uncertain:
        status = UNCERTAIN
        reason = "Speaker evidence is ambiguous; no owner privilege is granted."
    else:
        status = UNKNOWN
        reason = "Speaker model does not match the enrolled owner profile."
    # This is a display confidence derived from distance to the unknown/high
    # bands, not a spoof-resistant probability.
    confidence = max(0.0, min(1.0, (similarity - thresholds.uncertain) / max(thresholds.high - thresholds.uncertain, 1e-6)))
    return {
        "status": status,
        "confidence": round(confidence, 3),
        "speaker_similarity": round(similarity, 4),
        "centroid_similarity": round(centroid_similarity, 4),
        "best_reference_similarity": round(best_reference, 4),
        "audio_quality": sample.diagnostics(),
        "spoof_score": None,
        "spoof_state": "NOT_AVAILABLE",
        "inference_ms": round(float(inference_ms), 2),
        "model": backend.name,
        "stored_audio": False,
        "reason": reason,
    }

