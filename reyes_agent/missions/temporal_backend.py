"""Temporal as an optional mission backend -- evaluated, deliberately not default.

THE ASSESSMENT
--------------
`temporalio/sdk-python` is the right tool for durable workflows at scale:
real replay semantics, versioned workflow code, distributed workers. It is
also a SERVICE. Using it means running a Temporal server (or paying for
Temporal Cloud) beside a desktop assistant, and the brief is explicit that
distributed infrastructure must not be added unless it genuinely improves
the architecture.

For one machine running one owner's missions, it does not. What Temporal
would buy here -- "survive a restart and continue from the last committed
step" -- is what `store.py` already does, in SQLite, with no server, no
port, and no second process to supervise or crash.

So: ARCHITECTURAL_REFERENCE. Temporal's *ideas* are used (idempotency keys,
per-step checkpoints, bounded retries, terminal states that never restart);
its runtime is not.

WHEN THIS SHOULD CHANGE
-----------------------
Attach Temporal when missions genuinely outgrow one machine: work spanning
several devices, missions that must survive the whole machine being off, or
more concurrent long-running missions than one process should hold. At that
point `manager.advance()` is the seam -- it already takes a runner and
checkpoints around it, so a Temporal activity slots in without the mission
model changing.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any

ENABLED_FLAG = "ZENO_TEMPORAL_ENABLED"


def installed() -> bool:
    return importlib.util.find_spec("temporalio") is not None


def enabled() -> bool:
    return os.environ.get(ENABLED_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def status() -> dict[str, Any]:
    have = installed()
    on = enabled()
    if on and not have:
        state = "DEGRADED"
    elif on:
        state = "STANDBY"
    else:
        state = "DISABLED"
    return {
        "state": state,
        "classification": "ARCHITECTURAL_REFERENCE",
        "installed": have,
        "enabled": on,
        "default_backend": "local durable store (SQLite, committed per step)",
        "why_not_default": ("Temporal needs a server beside the assistant. The property "
                            "it would provide here -- resume from the last committed step "
                            "after a restart -- is already provided locally with no extra "
                            "process to supervise."),
        "adopt_when": ("missions span multiple machines, must survive the machine being "
                       "off, or outnumber what one process should hold"),
        "seam": "missions.manager.advance() -- takes a runner and checkpoints around it",
    }
