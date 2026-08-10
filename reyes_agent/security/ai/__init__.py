"""Guardrails on the model interaction layer.

`trust_context` is the boundary: content is judged by where it came from,
not by whether it looks like an attack. `guardrails` screens input, output
and tool calls, and explains what a page tried.

This does not replace `security/policy` or the permission engine -- those
decide whether an action is allowed; these decide whether the model was
manipulated into asking.
"""

from __future__ import annotations

from reyes_agent.security.ai import trust_context      # no intra-package deps
from reyes_agent.security.ai import guardrails         # needs trust_context

__all__ = ["trust_context", "guardrails", "screen_input", "screen_output",
           "screen_tool_call", "status"]

screen_input = guardrails.screen_input
screen_output = guardrails.screen_output
screen_tool_call = guardrails.screen_tool_call
status = guardrails.status
