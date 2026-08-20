"""Run owner commands locally, so the phone app actually does something.

THE GAP THIS FILLS
------------------
The owner web app (/app) sends commands to /api/owner/command, which ENQUEUES
them. In the cloud-relay design a separate desktop agent dials in and drains
that queue. In the ZENO Anywhere tunnel design there is no separate agent --
the server IS the desktop -- so without this the queue fills and nothing runs.

This is that executor, run in-process by the same machine that hosts the
queue: it registers ONE pre-approved local device and runs `desktop_agent`'s
existing executors (ask -> the ZENO brain, agent_status -> the roster, status
-> system health, open_app -> the desktop). The phone's chat, roll-call and
controls now return real results. The owner's durable remote-control switch is
never changed here.

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
_TOKEN_KEY = "ZENO_ANYWHERE_LOCAL_EXECUTOR_TOKEN"
_DEFAULT_DEVICE_ID = "dev_zeno_anywhere_local"
_PORT = int(config.PHONE_COMPANION_PORT)
_GATEWAY = f"http://127.0.0.1:{_PORT}"
# The executor may run the conversational and read actions the phone needs.
# It does NOT grant itself sensitive-device scope; those still route through
# the owner approval flow.
_SCOPES = ["talk", "standard_device", "read_only"]


def _metadata() -> dict[str, str]:
    try:
        data = json.loads(_CREDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_metadata(device_id: str) -> None:
    """Persist only the non-secret device identifier, atomically."""
    _HOME.mkdir(parents=True, exist_ok=True)
    temporary = _CREDS.with_suffix(".tmp")
    temporary.write_text(json.dumps({"device_id": device_id}), encoding="utf-8")
    os.replace(temporary, _CREDS)


def _store_token(token: str) -> None:
    from reyes_agent.security.secrets import manager as secrets

    ok, reason = secrets.put(_TOKEN_KEY, token)
    if not ok:
        raise RuntimeError(f"local executor credential store unavailable: {reason}")


def _load_creds() -> dict[str, str] | None:
    """Load the token from Windows Credential Manager.

    Older builds wrote the token into ``executor.json``.  Migrate that value
    once, then immediately replace the file with non-secret metadata.  The
    token is never logged or returned by a status API.
    """
    from reyes_agent.security.secrets import manager as secrets

    data = _metadata()
    device_id = str(data.get("device_id", "")).strip()
    token = secrets.get(_TOKEN_KEY).strip()
    legacy_token = str(data.get("token", "")).strip()
    if legacy_token:
        if not token:
            _store_token(legacy_token)
            token = legacy_token
        if device_id:
            _write_metadata(device_id)
    if device_id and token:
        return {"device_id": device_id, "token": token}
    return None


def ensure_device() -> dict[str, str]:
    """A stable, pre-approved loopback device. Reused across restarts so the
    token does not churn."""
    from reyes_agent.remote_access import device_link

    link = device_link.get_link()
    metadata = _metadata()
    creds = _load_creds()
    if creds and link.authenticate(creds["device_id"], creds["token"]):
        return creds

    # Reuse the known identifier when a token was lost or invalidated.  This
    # rotates the token in place instead of accumulating approved ghost
    # devices after profile recovery.
    device_id = str(metadata.get("device_id", "")).strip() or _DEFAULT_DEVICE_ID
    registered = link.register(
        label="ZENO Anywhere local executor", platform="windows",
        device_id=device_id, approved=True, scopes=_SCOPES,
    )
    creds = {"device_id": registered["device_id"], "token": registered["token"]}
    try:
        _store_token(creds["token"])
        _write_metadata(creds["device_id"])
    except Exception:
        # Never leave a newly approved device whose one-time token was not
        # secured durably.  A later startup can register it again safely.
        link.revoke_device(creds["device_id"])
        raise
    return creds


def enable() -> dict[str, Any]:
    """Register the device and export the in-server connector environment.

    The durable remote-control kill switch is deliberately left unchanged.
    Restarting ZENO Anywhere must never undo an explicit owner disable.
    """
    from reyes_agent.remote_access import device_link

    creds = ensure_device()
    link = device_link.get_link()
    os.environ["ZENO_GATEWAY_URL"] = _GATEWAY
    os.environ["ZENO_DEVICE_ID"] = creds["device_id"]
    os.environ["ZENO_DEVICE_TOKEN"] = creds["token"]
    return {"gateway": _GATEWAY, "device_id": creds["device_id"],
            "remote_control": link.remote_control_enabled()}


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
