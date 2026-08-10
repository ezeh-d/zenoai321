"""Single-stream local wake-word subsystem."""

from reyes_agent.wake.engine import WakeEngine, get_wake_engine
from reyes_agent.wake.state_machine import WakeState

__all__ = ["WakeEngine", "WakeState", "get_wake_engine"]
