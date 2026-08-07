"""Static regression checks for the lightweight Event-Bus Subspace view."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
web = (ROOT / "reyes_agent" / "web.py").read_text(encoding="utf-8")
ui = (ROOT / "reyes_agent" / "static" / "index.html").read_text(encoding="utf-8")

checks = {
    "hierarchy endpoint uses the existing runtime": "def agent_hierarchy()" in web and "agent_runtime.health()" in web,
    "Subspace is explicitly opened on demand": "async function openSubspace()" in ui and "fetch('/api/hierarchy')" in ui,
    "Subspace consumes real worker events": "agent.worker_started" in ui and "agent.worker_finished" in ui and "ingestSubspaceEvent(update)" in ui,
    "Subspace has no polling loop": "subspaceTimer" not in ui and "setInterval(() => renderSubspace" not in ui,
    "hidden Subspace releases its projection": "subspaceState.activity.clear();" in ui and "subspaceBody.replaceChildren();" in ui,
    "worker teams are collapsed by default": "const workers = expanded ?" in ui,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'} {name}")
if failed:
    print("FAILED:", ", ".join(failed))
    sys.exit(1)
print("all Subspace projection checks passed")
