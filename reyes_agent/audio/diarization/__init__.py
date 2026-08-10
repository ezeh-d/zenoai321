"""Speaking turns, without inventing who spoke them."""

from __future__ import annotations

from reyes_agent.audio.diarization import router
from reyes_agent.audio.diarization.router import Diarization, Turn

__all__ = ["router", "Turn", "Diarization", "diarize", "segment", "should_diarize", "status"]

diarize = router.diarize
segment = router.segment
should_diarize = router.should_diarize
status = router.status
