"""Build a multi-condition owner profile from real model embeddings."""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from reyes_agent.identity.speaker.embeddings import EmbeddingBackend
from reyes_agent.identity.speaker.quality import analyse

MIN_CLIPS = 5
MAX_CLIPS = 8


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.clip(np.dot(left, right) / max(float(np.linalg.norm(left) * np.linalg.norm(right)), 1e-9), -1.0, 1.0))


def build_profile(clips: list[bytes], backend: EmbeddingBackend) -> dict[str, Any]:
    if not MIN_CLIPS <= len(clips) <= MAX_CLIPS:
        raise ValueError(f"Provide {MIN_CLIPS}-{MAX_CLIPS} separate recordings.")
    vectors: list[np.ndarray] = []
    quality_rows: list[dict[str, float]] = []
    inference_ms: list[float] = []
    for index, clip in enumerate(clips, 1):
        try:
            sample = analyse(clip)
            vector, elapsed = backend.embed(sample)
        except Exception as exc:
            raise ValueError(f"Recording {index}: {exc}") from exc
        vectors.append(vector)
        quality_rows.append(sample.diagnostics())
        inference_ms.append(float(elapsed))
    pairwise = [_cosine(left, right) for i, left in enumerate(vectors) for right in vectors[i + 1:]]
    median_similarity = float(np.median(pairwise))
    if median_similarity < 0.55:
        raise ValueError(
            "The recordings are not consistent enough for one owner profile. Record only Divine in a quieter room."
        )
    centroid = np.mean(np.stack(vectors), axis=0)
    centroid /= max(float(np.linalg.norm(centroid)), 1e-9)
    return {
        "format": 2,
        "enrolled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clips": len(vectors),
        "centroid": [round(float(value), 8) for value in centroid],
        "references": [[round(float(value), 8) for value in vector] for vector in vectors],
        "self_similarity_median": round(median_similarity, 4),
        "self_similarity_min": round(min(pairwise), 4),
        "quality": quality_rows,
        "embedding_inference_ms": [round(value, 2) for value in inference_ms],
        "backend": backend.name,
        "raw_audio_stored": False,
        "calibration": "Owner-only enrollment; unknown-speaker calibration is still required for measured accuracy.",
    }

