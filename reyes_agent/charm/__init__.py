"""Lazy public API for ZENO's native Charm Engine."""

from reyes_agent.charm.models import (
    CandidateScores,
    CharmCandidate,
    CharmFeature,
    CharmMode,
    CharmRequest,
    CharmResult,
    ContextSignals,
    Recommendation,
    StyleProfile,
)


def get_charm_engine():
    """Return the shared engine without loading it during normal startup."""
    from reyes_agent.charm.engine import get_charm_engine as get_engine

    return get_engine()

__all__ = [
    "CandidateScores",
    "CharmCandidate",
    "CharmFeature",
    "CharmMode",
    "CharmRequest",
    "CharmResult",
    "ContextSignals",
    "Recommendation",
    "StyleProfile",
    "get_charm_engine",
]
