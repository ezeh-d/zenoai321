"""Event-driven screen/video understanding without a continuous model loop."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from reyes_agent import visual_awareness


def _ocr_frame(jpeg: bytes) -> dict[str, Any]:
    """Use the existing local Windows OCR engine, then remove its temp file."""
    from reyes_agent import ocr

    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="zeno-visual-", suffix=".jpg", delete=False) as handle:
            handle.write(jpeg)
            path = Path(handle.name)
        return ocr.extract_image_text(path).as_dict()
    finally:
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _describe_frame(jpeg: bytes, question: str) -> str:
    from reyes_agent import config

    if not config.GEMINI_API_KEY:
        return ""
    # Existing capture tools expose a private in-memory model helper. Calling
    # it here avoids changing their persistent-capture contract: this frame
    # remains memory-only and the temporary OCR file is deleted.
    from reyes_agent.tools.vision import _describe_image

    guarded_question = (
        "Describe only visible evidence relevant to this question: " + question + "\n"
        "Do not identify an unknown person. Do not name a film, show, song or real-world identity unless "
        "the frame itself contains specific supporting evidence. If evidence is insufficient, say so."
    )
    return _describe_image(jpeg, guarded_question)


def _select_frames(frames, maximum: int = 4):
    if len(frames) <= maximum:
        return list(frames)
    positions = [round(i * (len(frames) - 1) / (maximum - 1)) for i in range(maximum)]
    return [frames[i] for i in positions]


def analyze(question: str, *, lookback_seconds: int = 0) -> dict[str, Any]:
    """Analyse an explicit current screen or the opted-in bounded timeline.

    A direct request obtains one frame.  "What happened N seconds ago" uses
    only the in-memory rolling buffer and never backfills a historical claim
    from one current screenshot.
    """
    question = str(question or "Describe what is visible.").strip()[:800]
    try:
        lookback_seconds = max(0, min(300, int(lookback_seconds)))
    except (TypeError, ValueError):
        lookback_seconds = 0
    _emit("visual.analysis_started", {"lookback_seconds": lookback_seconds})
    try:
        if lookback_seconds:
            frames = visual_awareness.recent_frames(lookback_seconds)
            if not frames:
                result = {
                    "ok": False,
                    "confidence": None,
                    "reason": (
                        f"No rolling visual history exists for the last {lookback_seconds}s. "
                        "Enable Visual Awareness and Rolling Buffer before asking about past video."
                    ),
                    "evidence": {"frames": 0, "stored_to_disk": False},
                }
                return result
            source = "rolling-buffer"
        else:
            frames = [visual_awareness.capture_screen_sample(reason="direct-analysis")]
            source = "direct-screen-sample"
        selected = _select_frames(frames)
        ocr_results = [_ocr_frame(sample.jpeg) for sample in selected]
        ocr_text = [item.get("text", "").strip()[:1200] for item in ocr_results if item.get("text", "").strip()]
        ocr_scores = [float(item.get("confidence", 0.0)) for item in ocr_results if item.get("ok")]
        description = ""
        try:
            # One vision request for one representative frame, never every
            # frame.  OCR and motion carry the temporal context locally.
            description = _describe_frame(selected[-1].jpeg, question)
        except Exception as exc:  # noqa: BLE001
            description = f"Vision model was unavailable: {type(exc).__name__}."
        motion_count = sum(1 for sample in selected if sample.motion > 0)
        audio_evidence: dict[str, Any] | None = None
        # Audio/video fusion is opt-in. A video request does not quietly open
        # loopback capture; it uses sound only when the owner has enabled the
        # visible System Audio Recognition control.
        if visual_awareness.settings().get("system_audio_recognition"):
            try:
                from reyes_agent import audio_recognition

                audio_evidence = audio_recognition.recognize_current(source="system", seconds=6)
            except Exception as exc:  # noqa: BLE001 -- visual evidence remains useful alone
                audio_evidence = {"matched": False, "reason": f"System audio unavailable: {type(exc).__name__}"}
        result = {
            "ok": bool(description or ocr_text),
            "source": source,
            "confidence": round(sum(ocr_scores) / len(ocr_scores), 3) if ocr_scores else None,
            "confidence_basis": "local OCR heuristic only; model descriptions do not expose calibrated confidence",
            "description": description,
            "ocr_text": ocr_text,
            "evidence": {
                "frames": len(selected),
                "time_span_s": round(max(0.0, selected[-1].captured_at - selected[0].captured_at), 1),
                "changed_frames": motion_count,
                "ocr_frames": sum(1 for result in ocr_results if result.get("ok")),
                "stored_to_disk": False,
                "camera_used": False,
            },
            "identity_note": "Unknown people are described, not identified. No stranger biometric profile is created.",
            "audio_evidence": audio_evidence,
        }
        return result
    finally:
        # Keep status events deliberately sparse: start/finish around actual
        # requests, no event per captured rolling frame.
        _emit("visual.analysis_finished", {"lookback_seconds": lookback_seconds})


def format_result(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return result.get("reason") or "ZENO could not obtain enough visual evidence."
    lines = [result.get("description") or "I could not obtain a model description; local evidence follows."]
    if result.get("ocr_text"):
        lines.append("Visible text (local OCR): " + " | ".join(result["ocr_text"])[:2400])
    audio = result.get("audio_evidence")
    if audio and audio.get("matched"):
        lines.append(f"Audio evidence: {audio.get('artist', '')} — {audio.get('title', '')} (source: {audio.get('provider', 'unknown')}).")
    elif audio:
        lines.append("Audio evidence: " + str(audio.get("reason") or "no confident match"))
    evidence = result.get("evidence", {})
    lines.append(
        f"Evidence: {evidence.get('frames', 0)} sampled frame(s), {evidence.get('changed_frames', 0)} changed; "
        f"stored to disk: {evidence.get('stored_to_disk', False)}."
    )
    if result.get("confidence") is None:
        lines.append("Confidence: unknown for the model description; ZENO will not turn it into a certain identification.")
    else:
        lines.append(f"OCR confidence: {result['confidence']:.0%} ({result.get('confidence_basis')}).")
    return "\n\n".join(lines)


def _emit(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from reyes_agent import event_bus

        event_bus.publish(event_type, payload, source="video_recognition")
    except Exception:  # noqa: BLE001
        pass
