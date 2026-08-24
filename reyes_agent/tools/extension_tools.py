"""Owner-facing tools for the inspected self-extension lifecycle."""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.tools import register


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


@register(
    name="extension_inspect",
    description=("Read and statically inspect an owner-supplied GitHub URL, package reference, "
                 "MCP/plugin/skill reference or local source. Unknown code is never executed; "
                 "security, license, compatibility, permissions and sandbox state are recorded."),
    input_schema={"type": "object", "properties": {
        "source": {"type": "string", "maxLength": 2000},
        "focus": {"type": "string", "maxLength": 200}}, "required": ["source"]},
)
def extension_inspect(source: str, focus: str = "") -> str:
    from reyes_agent.extensions import get_extension_engine
    return _json(get_extension_engine().inspect(source, focus=focus))


@register(
    name="extension_status",
    description=("Show the real extension catalog or one extension's doctor report, including "
                 "state, health, tests, permissions and quarantine reason."),
    input_schema={"type": "object", "properties": {
        "extension_id": {"type": "string", "maxLength": 100}}},
)
def extension_status(extension_id: str = "") -> str:
    from reyes_agent.extensions import get_extension_engine
    engine = get_extension_engine()
    return _json(engine.doctor(extension_id) if extension_id else engine.status())


@register(
    name="extension_search",
    description=("Search GitHub for owner-requested capability candidates and return bounded "
                 "metadata only. Search results are never installed automatically."),
    input_schema={"type": "object", "properties": {
        "capability": {"type": "string", "maxLength": 200},
        "limit": {"type": "integer"}}, "required": ["capability"]},
)
def extension_search(capability: str, limit: int = 5) -> str:
    from reyes_agent.extensions import CapabilityHunter
    return _json(CapabilityHunter().search(capability, limit=max(1, min(10, int(limit)))))


@register(
    name="extension_approve",
    description=("Approve an extension for canary only after its inspection and sandbox gates. "
                 "Confirmation alone cannot turn a generated manifest into executable code."),
    input_schema={"type": "object", "properties": {
        "extension_id": {"type": "string", "maxLength": 100},
        "confirmed": {"type": "boolean"}}, "required": ["extension_id", "confirmed"]},
    requires_confirmation=True,
)
def extension_approve(extension_id: str, confirmed: bool) -> str:
    if not confirmed:
        return _json({"ok": False, "state": "CONFIRMATION_REQUIRED"})
    from reyes_agent.extensions import get_extension_engine
    return _json(get_extension_engine().approve(extension_id))


@register(
    name="extension_rollback",
    description="Select the previous tested known-good extension version and disable it pending a fresh canary.",
    input_schema={"type": "object", "properties": {
        "extension_id": {"type": "string", "maxLength": 100},
        "confirmed": {"type": "boolean"}}, "required": ["extension_id", "confirmed"]},
    requires_confirmation=True,
)
def extension_rollback(extension_id: str, confirmed: bool) -> str:
    if not confirmed:
        return _json({"ok": False, "state": "CONFIRMATION_REQUIRED"})
    from reyes_agent.extensions import get_extension_engine
    return _json(get_extension_engine().rollback(extension_id))


@register(
    name="extension_remove",
    description=("Disable and remove registry-owned extension metadata without deleting unrelated "
                 "project files or environments."),
    input_schema={"type": "object", "properties": {
        "extension_id": {"type": "string", "maxLength": 100},
        "confirmed": {"type": "boolean"}}, "required": ["extension_id", "confirmed"]},
    requires_confirmation=True,
)
def extension_remove(extension_id: str, confirmed: bool) -> str:
    if not confirmed:
        return _json({"ok": False, "state": "CONFIRMATION_REQUIRED"})
    from reyes_agent.extensions import get_extension_engine
    return _json(get_extension_engine().remove(extension_id))


@register(
    name="extension_update_check",
    description="Explain the pinned extension update path; never installs latest blindly.",
    input_schema={"type": "object", "properties": {
        "extension_id": {"type": "string", "maxLength": 100}}, "required": ["extension_id"]},
)
def extension_update_check(extension_id: str) -> str:
    from reyes_agent.extensions import ExtensionUpdateManager, get_extension_engine
    engine = get_extension_engine()
    return _json(ExtensionUpdateManager(engine).check(extension_id))
