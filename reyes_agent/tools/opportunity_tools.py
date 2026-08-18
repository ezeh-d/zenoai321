"""Lazy tools for the evidence-led Opportunity Engine."""

from __future__ import annotations

import json
from typing import Any

from reyes_agent.opportunity import get_opportunity_engine, research_plan
from reyes_agent.tools import register


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


@register(
    name="opportunity_plan",
    description=("Plan legitimate opportunity research using ZENO's existing specialists. "
                 "Returns research tasks, not invented market facts or guaranteed income."),
    input_schema={
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "skills": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["goal"],
    },
)
def opportunity_plan(goal: str, skills: list[str] | None = None,
                     constraints: list[str] | None = None) -> str:
    return _json(research_plan(goal, skills, constraints))


_FACTOR_PROPERTIES = {
    name: {"type": "number", "minimum": 0, "maximum": 10}
    for name in (
        "skill_fit", "startup_cost", "time_to_first_result", "market_demand",
        "competition", "repeatability", "scalability", "risk", "estimated_effort",
    )
}


@register(
    name="opportunity_assess",
    description=("Persist a transparent 0-100 relative opportunity assessment from supplied "
                 "0-10 factors and dated evidence. The score is not an income probability."),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"}, "category": {"type": "string"},
            "summary": {"type": "string"}, "opportunity_id": {"type": "string"},
            "factors": {"type": "object", "properties": _FACTOR_PROPERTIES,
                        "required": list(_FACTOR_PROPERTIES)},
            "observations": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["FACT", "ESTIMATE", "ASSUMPTION", "OPINION", "EXPERIMENT_RESULT"]},
                    "summary": {"type": "string"}, "source": {"type": "string"},
                    "observed_at": {"type": "number"}, "expires_at": {"type": "number"},
                },
                "required": ["kind", "summary"],
            }},
        },
        "required": ["name", "category", "summary", "factors"],
    },
)
def opportunity_assess(name: str, category: str, summary: str,
                       factors: dict[str, Any], observations: list[dict[str, Any]] | None = None,
                       opportunity_id: str = "") -> str:
    return _json(get_opportunity_engine().assess(
        name=name, category=category, summary=summary, factors=factors,
        observations=observations, opportunity_id=opportunity_id,
    ))


@register(
    name="opportunity_list",
    description="List saved opportunity assessments with evidence state and expiry counts.",
    input_schema={"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}},
)
def opportunity_list(limit: int = 20) -> str:
    return _json(get_opportunity_engine().list(limit=limit))


@register(
    name="opportunity_get",
    description="Read one saved opportunity assessment and its current/expired evidence.",
    input_schema={"type": "object", "properties": {"opportunity_id": {"type": "string"}},
                  "required": ["opportunity_id"]},
)
def opportunity_get(opportunity_id: str) -> str:
    result = get_opportunity_engine().get(opportunity_id)
    return _json(result) if result else "No opportunity assessment has that id."


@register(
    name="opportunity_delete",
    description="Delete one saved opportunity assessment. This never deletes project files.",
    input_schema={"type": "object", "properties": {"opportunity_id": {"type": "string"}},
                  "required": ["opportunity_id"]},
    requires_confirmation=True,
)
def opportunity_delete(opportunity_id: str) -> str:
    return ("Opportunity assessment deleted."
            if get_opportunity_engine().delete(opportunity_id)
            else "No opportunity assessment has that id.")
