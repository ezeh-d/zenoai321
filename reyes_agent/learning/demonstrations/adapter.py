"""OpenAdapt-style contract backed by the existing verified workflow engine."""
from __future__ import annotations

import os


def workflow_engine():
    from reyes_agent.workflow_engine import get_workflow_engine
    return get_workflow_engine()


def status() -> dict:
    enabled = os.environ.get("ZENO_OPENADAPT_ENABLED", "true").casefold() in {"1", "true", "yes", "on"}
    return {"state": "STANDBY" if enabled else "DISABLED", "enabled": enabled,
            "authority": "reyes_agent.workflow_engine", "raw_coordinate_replay": False,
            "review_required": True, "step_verification": True,
            "note": "OpenAdapt source is not embedded; ZENO already has the required bounded recorder/compiler/replay lifecycle."}
