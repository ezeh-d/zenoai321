"""Tools that let ZENO answer questions about his own team.

These are deliberately cheap. They read configuration dictionaries and never
start an agent, so "who is Apex" is answerable while APEX is unloaded --
which is exactly the failure this fixes.
"""

from __future__ import annotations

import json

from reyes_agent.agents import identity
from reyes_agent.tools import register


@register(name="agent_roster",
          description=("List every registered ZENO agent with role, workers "
                       "and status. Answers 'who are your agents', 'show me "
                       "all your agents', 'what agents do you have'. Does not "
                       "load any agent."),
          input_schema={"type": "object", "properties": {}})
def agent_roster() -> str:
    return json.dumps(identity.role_call(), default=str)


@register(name="who_is_agent",
          description=("Describe one ZENO agent by name or alias -- 'who is "
                       "Stark', 'who is Apex', 'what does Oracle do'. Works "
                       "while the agent is asleep."),
          input_schema={"type": "object", "properties": {
              "name": {"type": "string", "description": "Agent name or alias."}},
              "required": ["name"]})
def who_is_agent(name: str) -> str:
    return json.dumps(identity.identity(name), default=str)


@register(name="agent_role_call",
          description=("Full role call: every main agent announces its name, "
                       "role and worker team. Answers 'ZENO, role call'."),
          input_schema={"type": "object", "properties": {}})
def agent_role_call() -> str:
    return json.dumps(identity.role_call(), default=str)


@register(name="agent_workers",
          description=("List the workers reporting to one agent -- 'who works "
                       "under Apex', 'show Hermes' team', 'what workers does "
                       "Stark have'."),
          input_schema={"type": "object", "properties": {
              "name": {"type": "string"}}, "required": ["name"]})
def agent_workers(name: str) -> str:
    return json.dumps(identity.workers_of(name), default=str)
