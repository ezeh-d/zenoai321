"""Permission Engine -- capability policy with installation profiles.

WHY PROFILES RATHER THAN A GLOBAL DEFAULT
-----------------------------------------
The owner of THIS installation has explicitly granted full local desktop
trust (2026-08-04). That is an installation-specific decision, not a
universal default, and it is recorded as one: the `trusted_local` profile
is selected by `INSTALLATION_PROFILE` in .env, and the shipped default
for any other install remains `cautious`. Copying this codebase elsewhere
does not copy the trust.

THE MODEL
---------
Every sensitive thing ZENO can do belongs to a CAPABILITY. Each profile
maps a capability to one of three states:

    ENABLED   -- runs immediately, still audited
    CONFIRM   -- queued for the human (Tier 6 confirmation gate)
    BLOCKED   -- never runs, no flag, not configurable in-band

Tools declare their capability; plugins declare the capabilities they
need in a manifest. Both then go through the same single decision
function, `check()`. That is the point of this module: one place decides,
instead of the autonomy rules living in tools/__init__.py, the plugin
rules living in the loader, and the two drifting apart.

FINANCIAL IS BLOCKED, NOT CONFIRM
---------------------------------
`financial` is BLOCKED in every profile including the fully-trusted one,
and there is no flag to change it. ZENO has no tool that moves money, and
the Investment Engine deliberately stops at a validated order ticket.
Money movement being unavailable is a property of the build, not a
setting -- see AGENT.md and tools/investing.py.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Literal

from reyes_agent import config

State = Literal["enabled", "confirm", "blocked"]

ENABLED: State = "enabled"
CONFIRM: State = "confirm"
BLOCKED: State = "blocked"

# --- capabilities -------------------------------------------------------
CAPABILITIES: dict[str, str] = {
    "filesystem_read":    "Read local files and folders",
    "filesystem_write":   "Create and modify local files",
    "filesystem_delete":  "Delete or move local files",
    "app_control":        "Launch, focus and close applications",
    "desktop_automation": "Keyboard, mouse and window control",
    "clipboard":          "Read and write the clipboard",
    "system_commands":    "Run shell commands",
    "browser_automation": "Drive a real browser session",
    "network_read":       "Fetch web pages, news, search results",
    "vision":             "Screen capture and webcam",
    "audio_capture":      "Capture microphone or system-loopback audio",
    "email_send":         "Send email on the user's behalf",
    "messaging_send":     "Send Slack/Telegram/chat messages",
    "social_post":        "Publish publicly to social platforms",
    "financial":          "Move money, place trades, make payments",
    "plugin_exec":        "Execute third-party plugin code",
}

# --- profiles -----------------------------------------------------------
# trusted_local: this installation. Full local desktop authority; things
# that leave the machine stay configurable; money stays blocked.
_TRUSTED_LOCAL: dict[str, State] = {
    "filesystem_read": ENABLED,
    "filesystem_write": ENABLED,
    "filesystem_delete": ENABLED,
    "app_control": ENABLED,
    "desktop_automation": ENABLED,
    "clipboard": ENABLED,
    "system_commands": ENABLED,
    "browser_automation": ENABLED,
    "network_read": ENABLED,
    "vision": ENABLED,
    "audio_capture": ENABLED,
    "plugin_exec": ENABLED,
    # Outward-facing: reaches other people, cannot be recalled. Owner can
    # move any of these to ENABLED via .env (see _env_overrides).
    "email_send": CONFIRM,
    "messaging_send": ENABLED,   # owner enabled 2026-08-04
    "social_post": CONFIRM,
    # Never, in any profile.
    "financial": BLOCKED,
}

# cautious: the shipped default for any other installation.
_CAUTIOUS: dict[str, State] = {
    "filesystem_read": ENABLED,
    "network_read": ENABLED,
    "vision": CONFIRM,
    "audio_capture": CONFIRM,
    "clipboard": ENABLED,
    "app_control": CONFIRM,
    "filesystem_write": CONFIRM,
    "filesystem_delete": CONFIRM,
    "desktop_automation": CONFIRM,
    "system_commands": CONFIRM,
    "browser_automation": CONFIRM,
    "plugin_exec": CONFIRM,
    "email_send": CONFIRM,
    "messaging_send": CONFIRM,
    "social_post": CONFIRM,
    "financial": BLOCKED,
}

PROFILES: dict[str, dict[str, State]] = {
    "trusted_local": _TRUSTED_LOCAL,
    "cautious": _CAUTIOUS,
}

_OVERRIDE_FILE = config.VAULT_PATH / "07-System" / "permissions" / "overrides.json"
_override_lock = threading.RLock()

ACTIVE_PROFILE = os.environ.get("INSTALLATION_PROFILE", "cautious").strip().lower()
if ACTIVE_PROFILE not in PROFILES:
    ACTIVE_PROFILE = "cautious"

# --- tool -> capability -------------------------------------------------
# Anything not listed is read-only/harmless and needs no capability.
TOOL_CAPABILITY: dict[str, str] = {
    "delete_file": "filesystem_delete",
    "move_file": "filesystem_delete",
    "run_command": "system_commands",
    "coding_inspect": "filesystem_read",
    "coding_execute": "system_commands",
    "mcp_discover": "plugin_exec",
    "mcp_read": "plugin_exec",
    "mcp_action": "plugin_exec",
    "skill_approve": "plugin_exec",
    "skill_disable": "plugin_exec",
    "skill_delete": "filesystem_delete",
    "skill_run": "plugin_exec",
    "device_observe": "vision",
    "device_execute": "desktop_automation",
    "episodic_search": "filesystem_read",
    "read_document_structured": "filesystem_read",
    "knowledge_graph_query": "filesystem_read",
    "knowledge_graph_remember": "filesystem_write",
    "engineering_backends": "filesystem_read",
    "mobile_device_status": "vision",
    "open_app": "app_control",
    "open_path": "app_control",
    "media_control": "app_control",
    "set_volume": "desktop_automation",
    "set_mic_level": "desktop_automation",
    "lock_screen": "desktop_automation",
    "write_clipboard": "clipboard",
    "read_clipboard": "clipboard",
    "write_note": "filesystem_write",
    "write_project_file": "filesystem_write",
    "create_3d_model": "filesystem_write",
    "take_screenshot": "vision",
    "take_webcam_photo": "vision",
    "understand_video": "vision",
    "recognize_audio": "audio_capture",
    "send_slack_message": "messaging_send",
    "send_telegram_message": "messaging_send",
    "browser_open": "browser_automation",
    "browser_click": "browser_automation",
    "browser_fill": "browser_automation",
    "browser_scroll": "browser_automation",
    "browser_vision_click": "browser_automation",
    "browser_extract": "browser_automation",
    "browser_read": "browser_automation",
    "browser_screenshot": "browser_automation",
    # The engine also checks each recorded step. This mapping protects the
    # explicit confirmation action itself in cautious installations.
    "workflow_confirm": "desktop_automation",
    # Reserved names: no such tool exists, and if one is ever added it
    # lands in a BLOCKED capability by default rather than an open one.
    "place_trade": "financial",
    "execute_trade": "financial",
    "transfer_funds": "financial",
    "withdraw_funds": "financial",
    "deposit_funds": "financial",
    "buy_asset": "financial",
    "sell_asset": "financial",
    "make_payment": "financial",
}


def _env_overrides() -> dict[str, State]:
    """Per-capability overrides, e.g. PERMISSION_EMAIL_SEND=enabled.

    Blocked capabilities cannot be overridden -- an override that tries is
    ignored rather than honoured.
    """
    out: dict[str, State] = {}
    for cap in CAPABILITIES:
        raw = os.environ.get(f"PERMISSION_{cap.upper()}", "").strip().lower()
        if raw in (ENABLED, CONFIRM, BLOCKED):
            out[cap] = raw  # type: ignore[assignment]
    return out


def _stored_overrides() -> dict[str, State]:
    try:
        raw = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    capabilities = raw.get("capabilities", {})
    if not isinstance(capabilities, dict):
        return {}
    return {
        cap: value for cap, value in capabilities.items()
        if cap in CAPABILITIES and value in {ENABLED, CONFIRM, BLOCKED}
        and cap != "financial"
    }


def set_state(capability: str, state: str) -> State:
    """Persist one owner setting and make it effective immediately.

    ``default`` removes the saved override. Financial execution remains
    structurally blocked and cannot be changed through this API.
    """
    capability = str(capability or "").strip().lower()
    state = str(state or "").strip().lower()
    if capability not in CAPABILITIES:
        raise ValueError(f"Unknown capability '{capability}'.")
    if capability == "financial":
        raise PermissionError("Financial execution is locked and cannot be enabled.")
    if state not in {ENABLED, CONFIRM, BLOCKED, "default"}:
        raise ValueError("State must be enabled, confirm, blocked, or default.")
    with _override_lock:
        data = _stored_overrides()
        if state == "default":
            data.pop(capability, None)
        else:
            data[capability] = state  # type: ignore[assignment]
        _OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = _OVERRIDE_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "schema_version": 1,
            "profile": ACTIVE_PROFILE,
            "capabilities": data,
        }, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(_OVERRIDE_FILE)
    try:
        from reyes_agent import audit
        audit.log("permission_changed", actor="owner", action_type="permission.update",
                  target=capability, policy=ACTIVE_PROFILE, outcome="updated",
                  state=state)
    except Exception:  # noqa: BLE001 -- policy update already persisted
        pass
    return state_for(capability)


def state_for(capability: str) -> State:
    base = PROFILES[ACTIVE_PROFILE]
    # financial is structurally blocked -- profile and env cannot open it.
    if capability == "financial":
        return BLOCKED
    override = _env_overrides().get(capability)
    if override is not None:
        return override
    stored = _stored_overrides().get(capability)
    if stored is not None:
        return stored
    return base.get(capability, CONFIRM)


def capability_for_tool(tool_name: str) -> str | None:
    return TOOL_CAPABILITY.get(tool_name)


def check(tool_name: str) -> State:
    """The single decision point for whether a tool may run unattended.

    A tool with no declared capability is read-only/harmless -> enabled.
    """
    cap = capability_for_tool(tool_name)
    if cap is None:
        return ENABLED
    return state_for(cap)


def describe() -> dict:
    """Full current policy -- what the GUI Permission Centre renders."""
    return {
        "profile": ACTIVE_PROFILE,
        "profile_note": (
            "Full local desktop trust, granted by the owner of this installation "
            "on 2026-08-04. Installation-specific, not a shipped default."
            if ACTIVE_PROFILE == "trusted_local"
            else "Conservative default: local changes and outward actions need confirmation."
        ),
        "capabilities": [
            {
                "name": cap,
                "description": desc,
                "state": state_for(cap),
                "overridden": (cap in _env_overrides() or cap in _stored_overrides()) and cap != "financial",
                "source": ("environment" if cap in _env_overrides() else
                           "saved" if cap in _stored_overrides() else "profile"),
                "locked": cap == "financial",
            }
            for cap, desc in CAPABILITIES.items()
        ],
        "settings_file": str(_OVERRIDE_FILE),
    }


# --- plugin permission manager -----------------------------------------
@dataclass
class PluginManifest:
    name: str
    version: str
    author: str
    description: str
    permissions: list[str]
    trusted: bool = False

    @property
    def unknown_permissions(self) -> list[str]:
        return [p for p in self.permissions if p not in CAPABILITIES]


_TRUST_FILE = config.VAULT_PATH / "07-System" / "plugins" / "trusted.json"


def _trusted_plugins() -> dict[str, str]:
    """name -> version the user approved. Re-approval is required when a
    plugin's version changes, so an update can't silently gain reach."""
    try:
        return json.loads(_TRUST_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def trust_plugin(name: str, version: str) -> None:
    _TRUST_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = _trusted_plugins()
    data[name] = version
    _TRUST_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def revoke_plugin(name: str) -> bool:
    data = _trusted_plugins()
    if name not in data:
        return False
    del data[name]
    _TRUST_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def load_manifest(py_path) -> PluginManifest | None:
    """Read `<plugin>.json` sitting beside `<plugin>.py`."""
    from pathlib import Path

    p = Path(py_path)
    manifest_path = p.with_suffix(".json")
    if not manifest_path.exists():
        return None
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    name = raw.get("name", p.stem)
    version = str(raw.get("version", "0"))
    return PluginManifest(
        name=name,
        version=version,
        author=raw.get("author", "unknown"),
        description=raw.get("description", ""),
        permissions=list(raw.get("permissions", [])),
        trusted=_trusted_plugins().get(name) == version,
    )


def may_load_plugin(manifest: PluginManifest | None, py_name: str) -> tuple[bool, str]:
    """Decide whether a plugin may be imported at all.

    Rules, in order:
      1. No manifest -> refuse. A plugin that won't declare what it needs
         doesn't run. This is the whole point of the manager.
      2. Unknown permission names -> refuse (typo or something invented).
      3. Requests a BLOCKED capability -> refuse outright.
      4. Not on the user's trusted list at this exact version -> refuse
         until approved.
      5. Otherwise load.
    """
    if manifest is None:
        return False, f"{py_name}: no manifest ({py_name}.json) declaring permissions -- not loaded."
    if manifest.unknown_permissions:
        return False, (f"{manifest.name}: declares unknown permission(s) "
                       f"{manifest.unknown_permissions} -- not loaded.")
    blocked = [p for p in manifest.permissions if state_for(p) == BLOCKED]
    if blocked:
        return False, f"{manifest.name}: requests blocked capability {blocked} -- not loaded."
    if not manifest.trusted:
        return False, (f"{manifest.name} v{manifest.version} is not approved. It requests: "
                       f"{', '.join(manifest.permissions) or 'nothing'}. "
                       "Approve it with trust_plugin to enable.")
    return True, f"{manifest.name} v{manifest.version} loaded."
