"""Run owner commands locally, so the phone app actually does something.

THE GAP THIS FILLS
------------------
The owner web app (/app) sends commands to /api/owner/command, which ENQUEUES
them. In the cloud-relay design a separate desktop agent dials in and drains
that queue. In the ZENO Anywhere tunnel design there is no separate agent --
the server IS the desktop -- so without this the queue fills and nothing runs.

This is that executor, run in-process by the same machine that hosts the
queue: it registers ONE pre-approved local device, enables remote control, and
runs `desktop_agent`'s existing executors (ask -> the ZENO brain, agent_status
-> the roster, status -> system health, open_app -> the desktop). The phone's
chat, roll-call and controls now return real results.

SECURITY IS UNCHANGED
---------------------
This does not widen who may issue commands. Enqueuing still requires an owner
SESSION on a TRUSTED (owner-approved) browser device -- the /api/owner/command
gate is untouched. This only executes what already passed that gate. The
device it registers is a loopback executor, not a remote entry point, and its
token never leaves the machine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from reyes_agent import config

_HOME = Path(os.environ.get("LOCALAPPDATA", str(config.PROJECT_ROOT))) / "ZENO" / "anywhere"
_CREDS = _HOME / "executor.json"
_PORT = int(config.PHONE_COMPANION_PORT)
_GATEWAY = f"http://127.0.0.1:{_PORT}"
# The executor may run the conversational and read actions the phone needs.
# It does NOT grant itself sensitive-device scope; those still route through
# the owner approval flow.
_SCOPES = ["talk", "standard_device", "read_only"]


def _load_creds() -> dict[str, str] | None:
    try:
        data = json.loads(_CREDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("device_id") and data.get("token"):
        return data
    return None


def ensure_device() -> dict[str, str]:
    """A stable, pre-approved loopback device. Reused across restarts so the
    token does not churn."""
    from reyes_agent.remote_access import device_link

    link = device_link.get_link()
    creds = _load_creds()
    if creds and link.authenticate(creds["device_id"], creds["token"]):
        return creds

    registered = link.register(label="ZENO Anywhere local executor",
                               platform="windows", approved=True, scopes=_SCOPES)
    link.approve_device(registered["device_id"], scopes=_SCOPES)
    creds = {"device_id": registered["device_id"], "token": registered["token"]}
    _HOME.mkdir(parents=True, exist_ok=True)
    _CREDS.write_text(json.dumps(creds), encoding="utf-8")
    try:
        # Restrict the creds file to the owner where the OS supports it.
        os.chmod(_CREDS, 0o600)
    except OSError:
        pass
    return creds


def enable() -> dict[str, Any]:
    """Register the device, turn remote control on, and export the environment
    the in-server desktop agent reads. Call before the server starts so it
    inherits the configuration."""
    from reyes_agent.remote_access import device_link

    creds = ensure_device()
    device_link.get_link().set_remote_control(True, requesting_device=creds["device_id"])
    os.environ["ZENO_GATEWAY_URL"] = _GATEWAY
    os.environ["ZENO_DEVICE_ID"] = creds["device_id"]
    os.environ["ZENO_DEVICE_TOKEN"] = creds["token"]
    return {"gateway": _GATEWAY, "device_id": creds["device_id"], "remote_control": True}


def run_standalone() -> int:
    """Run the executor as its own process (for testing or a separate worker).

    Blocks, draining the local queue until interrupted.
    """
    import time

    from reyes_agent.remote_access import desktop_agent

    enable()
    agent = desktop_agent.from_environment()
    if agent is None:
        print("could not configure the local executor")
        return 1
    agent.start()
    print(f"local executor draining {_GATEWAY} as {os.environ['ZENO_DEVICE_ID'][:16]}")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        agent.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_standalone())
