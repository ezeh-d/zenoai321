"""Long-running ZENO missions that survive a restart.

    ensure(title, steps)  ->  (mission, created)

`created is False` means ZENO already had this mission and is resuming it,
which is the whole point: a crash halfway through must not produce a second
copy. Identity comes from a key derived from the request and enforced by a
UNIQUE index, so two callers cannot race their way into duplicates.

Not for one-step commands or reminders -- those belong on the scheduler.
Temporal is assessed in `temporal_backend.py` and is a reference, not a
dependency.
"""

from __future__ import annotations

from reyes_agent.missions import store                    # no intra-package deps
from reyes_agent.missions import manager                  # needs store
from reyes_agent.missions import temporal_backend         # independent seam
from reyes_agent.missions.manager import (BLOCKED, CANCELLED, COMPLETED, CREATED,
                                          FAILED, PAUSED, QUEUED, RETRYING, RUNNING,
                                          STATES, WAITING, Mission)

__all__ = ["Mission", "STATES", "CREATED", "QUEUED", "RUNNING", "WAITING", "PAUSED",
           "RETRYING", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED",
           "store", "manager", "temporal_backend",
           "ensure", "get", "advance", "resume_all", "cancel", "history", "status"]

ensure = manager.ensure
get = manager.get
advance = manager.advance
resume_all = manager.resume_all
cancel = manager.cancel
history = manager.history
status = manager.status
