"""The Evidence Hub, exposed as things ZENO can actually open.

One tool per screen, because a supervisor asks one question at a time and a
single "show everything" tool would answer all of them at once -- which is
the monologue failure in a different costume.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register


@register(name="siwes_evidence",
          description=("Open the SIWES Evidence Hub -- Divine's portfolio "
                       "overview: placement, project, real scale of the work. "
                       "Use for 'show my SIWES evidence', 'open my portfolio', "
                       "'show Engr Bello what I've worked on'."),
          input_schema={"type": "object", "properties": {}})
def siwes_evidence() -> str:
    from reyes_agent.presentation import evidence, pack, portfolio, timeline

    return json.dumps({
        "owner": "Divine",
        "institution": "Redeemer's University",
        "placement": "T21 Services",
        "period": f"{timeline.SIWES_START} to {timeline.SIWES_END}",
        "main_project": "REYES, later renamed ZENO",
        "scale": evidence.project_evidence(),
        "sections": ["project story", "timeline", "code proof", "learning",
                     "challenges", "feature status", "system status"],
        "learning_topics": len(portfolio.portfolio()["topics"]),
        "challenges": len(evidence.challenges()),
        "pack": pack.verify(),
    }, default=str)


@register(name="code_proof",
          description=("Show the real source file behind a capability -- "
                       "memory, voice, wake word, agents, desktop automation, "
                       "phone companion, messaging, security. Use for 'show "
                       "the code behind that' or 'is there real code'. Never "
                       "shows credentials."),
          input_schema={"type": "object", "properties": {
              "capability": {"type": "string"}}, "required": ["capability"]})
def code_proof(capability: str) -> str:
    from reyes_agent.presentation import evidence

    refusal = evidence.refuse_secret(capability)
    if refusal:
        return json.dumps({"refused": True, "say": refusal})
    return json.dumps(evidence.code_proof(capability).as_dict(), default=str)


@register(name="engineering_challenges",
          description=("Real problems Divine solved, each with cause, fix and "
                       "the git commit that proves it. Use for 'show problems "
                       "Divine solved' or 'what went wrong'."),
          input_schema={"type": "object", "properties": {}})
def engineering_challenges() -> str:
    from reyes_agent.presentation import evidence

    found = evidence.challenges()
    return json.dumps({
        "count": len(found), "challenges": found,
        "note": ("Each cites a commit that was checked to exist. Any without "
                 "a verifiable commit is dropped rather than shown."),
    }, default=str)


@register(name="learning_portfolio",
          description=("What Divine has been learning during SIWES, each topic "
                       "tied to the file where he used it. Use for 'show what "
                       "Divine learned'."),
          input_schema={"type": "object", "properties": {}})
def learning_portfolio() -> str:
    from reyes_agent.presentation import portfolio

    return json.dumps(portfolio.portfolio(), default=str)


@register(name="project_evolution",
          description=("The REYES to ZENO evolution, from real project "
                       "history, marking which stages git can prove and which "
                       "are the owner's account. Use for 'show how you "
                       "evolved'."),
          input_schema={"type": "object", "properties": {}})
def project_evolution() -> str:
    from reyes_agent.presentation import timeline

    data = timeline.build()
    return json.dumps({**data, "spoken_gap": timeline.gap()["say"]}, default=str)


@register(name="system_status",
          description=("Real subsystem health -- voice, STT, TTS, wake word, "
                       "memory, agents, phone, desktop tools. Runs live "
                       "checks. Use for 'show your status' or 'refresh system "
                       "status'."),
          input_schema={"type": "object", "properties": {}})
def system_status() -> str:
    from reyes_agent.presentation import readiness

    return json.dumps(readiness.run(), default=str)


@register(name="prepare_presentation_evidence",
          description=("Regenerate the local presentation pack so the visit "
                       "works even without internet: profiles, timeline, "
                       "features, evidence, learning, challenges. Use for "
                       "'prepare presentation evidence'."),
          input_schema={"type": "object", "properties": {}})
def prepare_presentation_evidence() -> str:
    from reyes_agent.presentation import pack

    written = pack.write()
    return json.dumps({**written, "verify": pack.verify()}, default=str)


@register(name="offline_presentation",
          description=("What ZENO can still explain with no internet, read "
                       "from the local pack. Use when the connection drops "
                       "during the visit."),
          input_schema={"type": "object", "properties": {}})
def offline_presentation() -> str:
    from reyes_agent.presentation import pack

    answer = pack.offline_answer()
    # The full pack is large; the caller needs to know WHAT is available and
    # what is not, then ask for the specific piece.
    answer.pop("data", None)
    return json.dumps(answer, default=str)


@register(name="should_divine_answer",
          description=("Check whether a visitor's question is about Divine's "
                       "personal experience, opinion or motive -- which ZENO "
                       "must not invent. Call before answering anything about "
                       "how Divine felt, what he found hard, or why he chose "
                       "something."),
          input_schema={"type": "object", "properties": {
              "question": {"type": "string"}}, "required": ["question"]})
def should_divine_answer(question: str) -> str:
    from reyes_agent.presentation import handoff

    return json.dumps(handoff.consider(question).as_dict(), default=str)


@register(name="presentation_recover",
          description=("Recovery for the visit: stop speech, cancel the "
                       "current task, close presentation panels and return to "
                       "listening. Use for the panic shortcut, 'ZENO close "
                       "that', or 'presentation safe mode'. Never deletes "
                       "data or restarts the application."),
          input_schema={"type": "object", "properties": {
              "safe_mode": {"type": "boolean",
                            "description": "Also disable heavy visuals."}}})
def presentation_recover(safe_mode: bool = False) -> str:
    from reyes_agent.presentation import recovery

    return json.dumps(recovery.recover(safe_mode=safe_mode), default=str)
