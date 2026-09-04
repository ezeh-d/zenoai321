"""The one tool humor mode needs: recording who won a battle round.

Everything else about jokes/roasts/battles is prompt-level (see
reyes_agent/humor.py's build_context) -- the model generates the actual
line, this tool only updates the deterministic scoreboard, so battle state
stays testable state machinery even though the JUDGING is the model's call.
Registered light=True: it can never do anything but increment a counter.
"""

from __future__ import annotations

from reyes_agent.tools import register


@register(
    name="battle_score",
    description=(
        "Record who won ONE exchange of an active dark-humor or comeback "
        "battle (see HUMOR MODE in your instructions). Call this once per "
        "round, right after you deliver your line -- never as a standalone "
        "action outside a battle."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "who_won": {
                "type": "string",
                "enum": ["user", "zeno", "tie"],
                "description": "Your honest, playful judgment of who won this exchange.",
            },
            "reason": {
                "type": "string",
                "description": "One short phrase for why -- shown nowhere, just for the record.",
            },
        },
        "required": ["who_won"],
    },
    light=True,
)
def battle_score(who_won: str, reason: str = "") -> str:
    from reyes_agent import humor

    state = humor.record_round_result(who_won)
    if not state.active:
        return (f"Battle over. Final score: ZENO {state.score_zeno} - "
                f"{state.score_user} owner.")
    return (f"Round recorded ({who_won}). Score: ZENO {state.score_zeno} - "
            f"{state.score_user} owner. Round {state.round} of {state.max_rounds} next.")
