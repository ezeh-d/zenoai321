"""Benchmark real consented clips without copying raw audio into ZENO.

Manifest JSONL rows:
{"path":"C:/audio/owner-normal.wav","speaker":"owner","condition":"quiet","transcript":"..."}

`speaker` is `owner` or `unknown`.  STT/WER runs only when explicitly enabled
because the primary backend may be billable.  Results contain no audio.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _words(text: str) -> list[str]:
    return " ".join(str(text or "").casefold().split()).split()


def _edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, lword in enumerate(left, 1):
        current = [i]
        for j, rword in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (lword != rword)))
        previous = current
    return previous[-1]


def run_manifest(manifest: Path, *, allow_stt: bool = False) -> dict[str, Any]:
    from reyes_agent import speaker_identity

    rows = []
    for line_number, line in enumerate(Path(manifest).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        path = Path(str(value.get("path") or "")).expanduser().resolve()
        if not path.is_file() or path.suffix.casefold() != ".wav":
            raise ValueError(f"Manifest line {line_number} is not a readable WAV file")
        speaker = str(value.get("speaker") or "").casefold()
        if speaker not in {"owner", "unknown"}:
            raise ValueError(f"Manifest line {line_number} requires speaker=owner|unknown")
        rows.append({**value, "path": path, "speaker": speaker})
    if not rows:
        raise ValueError("The benchmark manifest contains no real audio clips")

    process = None
    try:
        import psutil
        process = psutil.Process()
    except Exception:
        pass
    rss_before = process.memory_info().rss if process else None
    results: list[dict[str, Any]] = []
    for row in rows:
        audio = row["path"].read_bytes()
        started = time.perf_counter()
        identity = speaker_identity.identify(audio)
        identity_ms = (time.perf_counter() - started) * 1000.0
        predicted_owner = identity.get("status") in {
            speaker_identity.OWNER_CONFIRMED, speaker_identity.LIKELY_OWNER,
        }
        result = {
            "file": row["path"].name,
            "condition": str(row.get("condition") or "unspecified"),
            "expected_speaker": row["speaker"],
            "speaker_status": identity.get("status"),
            "speaker_similarity": identity.get("speaker_similarity"),
            "speaker_correct": predicted_owner == (row["speaker"] == "owner"),
            "speaker_wall_ms": round(identity_ms, 2),
            "audio_quality": identity.get("audio_quality"),
            "spoof_state": identity.get("spoof_state"),
        }
        expected = str(row.get("transcript") or "").strip()
        if allow_stt and expected:
            from reyes_agent.voice.stt import transcribe_result

            stt_started = time.perf_counter()
            heard = str(transcribe_result(audio)["transcript"])
            reference_words = _words(expected)
            distance = _edit_distance(reference_words, _words(heard))
            result.update({"stt_wall_ms": round((time.perf_counter() - stt_started) * 1000.0, 2),
                           "wer": round(distance / max(1, len(reference_words)), 4)})
        results.append(result)
    rss_after = process.memory_info().rss if process else None
    correct = [bool(row["speaker_correct"]) for row in results]
    latencies = sorted(float(row["speaker_wall_ms"]) for row in results)
    return {
        "measured": True,
        "clips": len(results),
        "owner_clips": sum(row["expected_speaker"] == "owner" for row in results),
        "unknown_clips": sum(row["expected_speaker"] == "unknown" for row in results),
        "speaker_accuracy": round(sum(correct) / len(correct), 4),
        "speaker_median_ms": round(latencies[len(latencies) // 2], 2),
        "rss_delta_mb": round((rss_after - rss_before) / 1048576, 2) if rss_after is not None else None,
        "stt_enabled": allow_stt,
        "raw_audio_stored": False,
        "results": results,
    }
