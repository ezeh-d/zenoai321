from __future__ import annotations

import os
import shutil

from reyes_agent.devices.bridge.interface import BridgeStatus


def status() -> BridgeStatus:
    enabled = os.environ.get("ZENO_KDE_CONNECT_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
    available = bool(shutil.which("kdeconnect-cli"))
    return BridgeStatus("kde-connect", "STANDBY" if enabled and available else ("DEGRADED" if enabled else "DISABLED"),
                        False, ("notifications", "clipboard", "files", "url"))
