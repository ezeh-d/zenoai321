"""Camera awareness -- off by default, and loud about being on.

OpenCV decides whether a frame is worth anything before a model ever sees
it. Boring frames are discarded locally, which is most of them.
"""

from __future__ import annotations

from reyes_agent.vision.camera import sensor
from reyes_agent.vision.camera.sensor import Frame

__all__ = ["sensor", "Frame", "open", "close", "capture", "active", "enabled", "status"]

open = sensor.open
close = sensor.close
capture = sensor.capture
active = sensor.active
enabled = sensor.enabled
status = sensor.status
