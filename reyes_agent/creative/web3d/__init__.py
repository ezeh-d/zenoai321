"""3D websites where deleting the canvas still leaves a working page."""

from __future__ import annotations

from reyes_agent.creative.web3d import budget            # no intra-package deps
from reyes_agent.creative.web3d import generator         # needs budget
from reyes_agent.creative.web3d.generator import SCENES, Section, SiteSpec

__all__ = ["budget", "generator", "SiteSpec", "Section", "SCENES",
           "generate", "measure", "status"]

generate = generator.generate
measure = budget.measure
status = generator.status
