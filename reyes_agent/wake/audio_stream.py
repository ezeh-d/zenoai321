"""Audio ownership contract for wake detection.

This module accepts frames; it intentionally has no microphone-open method.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioContract:
    owner: str = "WebView2 Mini Orb"
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2
    opens_microphone: bool = False


CONTRACT = AudioContract()


def status() -> dict:
    return {
        "owner": CONTRACT.owner,
        "format": f"pcm_s16le/{CONTRACT.sample_rate}/mono",
        "opens_microphone": CONTRACT.opens_microphone,
        "note": "Wake detection reuses the already-authorized WebView2 stream.",
    }
