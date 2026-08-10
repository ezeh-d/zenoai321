"""One activity-context selector prevents Screenpipe/ActivityWatch duplication."""
from __future__ import annotations

from reyes_agent.context.episodic import get_provider


def status() -> dict:
    data = get_provider().status()
    data["exclusive_selection"] = True
    data["existing_digital_dna_monitor"] = "separate low-rate executable-name sampler"
    return data
