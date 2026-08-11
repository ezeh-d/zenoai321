"""Design knowledge ZENO can consult instead of inventing a palette.

Data vendored from nextlevelbuilder/ui-ux-pro-max-skill (MIT) -- data only.
The loader is ZENO's own, because several upstream scripts make network
calls and vendoring one of those would turn a design library into an egress
path nobody reviewed.
"""

from __future__ import annotations

from reyes_agent.creative.design import library
from reyes_agent.creative.design import system

__all__ = ["library", "system", "DesignSystem", "search", "brief_guidance",
           "for_brief", "contrast", "tables", "status"]

search = library.search
brief_guidance = library.brief_guidance
tables = library.tables
for_brief = system.for_brief
contrast = system.contrast
DesignSystem = system.DesignSystem


def status() -> dict:
    return {**library.status(), "system": system.status()}
