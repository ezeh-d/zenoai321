"""Sherpa-ONNX STT adapter status; no ASR model is silently downloaded."""


def status() -> dict:
    from reyes_agent.audio.local.sherpa_engine import status as sherpa_status

    return sherpa_status()

