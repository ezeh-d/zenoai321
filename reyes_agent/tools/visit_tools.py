"""The SIWES visit, exposed to ZENO as things it can actually do.

Deliberately NOT one "present the project" tool. A single tool that returns
the whole story invites exactly the behaviour the owner forbade: ZENO says
all of it, and Engr Bello never gets a turn. These are separate steps because
a conversation is separate steps.
"""

from __future__ import annotations

import json

from reyes_agent.tools import register


@register(name="prepare_for_visit",
          description=("Run the real pre-visit readiness check before Engr "
                       "Bello arrives -- microphone, speech, wake word, "
                       "agents, phone mic, presentation facts. Returns READY, "
                       "PARTIAL or FAILED per item with the real reason. Use "
                       "for 'ZENO, prepare for Engr Bello'."),
          input_schema={"type": "object", "properties": {}})
def prepare_for_visit() -> str:
    from reyes_agent.presentation import readiness, timeline, visit

    visit.write_profile()
    timeline.write()
    result = readiness.run()
    return json.dumps(result, default=str)


@register(name="start_visitor_session",
          description=("Begin the SIWES visitor conversation with Engr Bello. "
                       "Use when Divine says 'ZENO, Engr Bello is here' or "
                       "'speak to Engr Bello'. Returns the opening line -- ONE "
                       "greeting and ONE question, then ZENO must stop and "
                       "listen."),
          input_schema={"type": "object", "properties": {}})
def start_visitor_session() -> str:
    from reyes_agent.presentation import visit

    opening = visit.session().start()
    return json.dumps({
        **opening,
        "visitor": visit.VISITOR["visitor"],
        "do_not_invent": list(visit.DO_NOT_INVENT),
        "guest_boundary": ("Presentation facts only -- no private memory, "
                           "mail, files or shell."),
    }, default=str)


@register(name="visitor_said",
          description=("Record what Engr Bello just said and get guidance for "
                       "replying naturally -- what has already been covered, "
                       "what technical depth he wants, and whether to pause. "
                       "Call this before answering him."),
          input_schema={"type": "object", "properties": {
              "utterance": {"type": "string"}}, "required": ["utterance"]})
def visitor_said(utterance: str) -> str:
    from reyes_agent.presentation import visit

    session = visit.session()
    if not session.active:
        return json.dumps({"error": "No visitor session is active. Start one "
                                    "with start_visitor_session."})
    heard = session.heard(utterance)
    pause, why = session.should_pause(0)
    return json.dumps({**heard, "should_pause": pause, "pause_reason": why,
                       "suggest_next": session.suggest_next()}, default=str)


@register(name="visit_topic",
          description=("Get the material for one topic of the visit and mark "
                       "it covered, so it is never explained twice. Topics: "
                       "siwes, origin, rename, evolution, architecture, "
                       "supervision, agents, contribution, ai_assistance, company, python, "
                       "challenges, learned, status, future."),
          input_schema={"type": "object", "properties": {
              "topic": {"type": "string"},
              "question": {"type": "string", "description": (
                  "The visitor's exact question when asking about supervision; "
                  "used to hand requests for incident details to Divine.")}},
              "required": ["topic"]})
def visit_topic(topic: str, question: str = "") -> str:
    from reyes_agent.presentation import facts, timeline, visit

    session = visit.session()
    key = (topic or "").strip().lower()
    found = next((t for t in session.topics if t.key == key), None)
    if found is None:
        return json.dumps({"error": f"No such topic '{topic}'.",
                           "topics": [t.key for t in session.topics]})

    repeat = session.repeat_guard(key)
    payload = {"topic": found.key, "heading": found.heading,
               "substance": found.substance,
               "budget_seconds": found.seconds,
               "already_covered": bool(repeat), "repeat_guidance": repeat,
               "technical_depth": session.technical_depth}

    # Topics whose content must come from the record, not from memory.
    if key in ("evolution", "rename"):
        payload["timeline"] = timeline.build()
    if key == "status":
        payload["features"] = facts.feature_status()
    if key == "agents":
        from reyes_agent.agents import identity

        payload["roster"] = identity.role_call()
    story_key = "placement" if key == "siwes" else key
    comment = visit.presentation_comment(story_key)
    if comment["available"]:
        payload["optional_comment"] = comment
    if key == "supervision":
        payload["supervision"] = visit.supervision_response(question)
        payload["substance"] = payload["supervision"]["say"]
        payload["do_not_invent_incident"] = True

    session.mark(key, found.seconds)
    pause, why = session.should_pause(found.seconds)
    payload["should_pause_after"] = pause
    payload["pause_reason"] = why
    return json.dumps(payload, default=str)


@register(name="owner_directive",
          description=("Apply an instruction Divine gives during the visit -- "
                       "'keep it short', 'explain technically', 'move on', "
                       "'show him', 'let him ask', 'end presentation', "
                       "'standby'. The owner outranks the visitor."),
          input_schema={"type": "object", "properties": {
              "directive": {"type": "string"}}, "required": ["directive"]})
def owner_directive(directive: str) -> str:
    from reyes_agent.presentation import visit

    session = visit.session()
    result = session.owner_says(directive)
    if result["action"] == "END":
        result["say"] = session.end()
    return json.dumps(result, default=str)


@register(name="visit_status",
          description=("Where the visit conversation has got to: which topics "
                       "are covered, how long ZENO has been talking, what was "
                       "last asked."),
          input_schema={"type": "object", "properties": {}})
def visit_status() -> str:
    from reyes_agent.presentation import visit

    return json.dumps(visit.status(), default=str)


@register(name="rehearse_visit",
          description=("Rehearse the visit WITH DIVINE -- this is practice, "
                       "not a claim that Engr Bello is present. Returns "
                       "realistic supervisor questions to practise answering."),
          input_schema={"type": "object", "properties": {
              "count": {"type": "integer"}}})
def rehearse_visit(count: int = 8) -> str:
    from reyes_agent.presentation import visit

    questions = [
        ("What exactly is ZENO?", "origin"),
        ("Why did you decide to build it?", "origin"),
        ("What is the difference between REYES and ZENO?", "rename"),
        ("What programming language did you use, and why?", "python"),
        ("Did you build all of this from scratch?", "contribution"),
        ("Did you use AI to build the AI?", "ai_assistance"),
        ("What part of it actually works today?", "status"),
        ("What is still under development?", "status"),
        ("What challenges did you run into?", "challenges"),
        ("How does the multi-agent part work?", "agents"),
        ("What have you learned during the placement?", "learned"),
        ("What work did you do for the company itself?", "company"),
        ("How does this relate to your SIWES?", "siwes"),
        ("What do you plan to do next with it?", "future"),
    ]
    take = max(1, min(len(questions), int(count or 8)))
    return json.dumps({
        "mode": "REHEARSAL",
        "not_a_visit": ("This is practice with Divine. Engr Bello is not "
                        "here and must not be spoken about as if present."),
        "questions": [{"ask": q, "topic": t} for q, t in questions[:take]],
        "coaching": ("Answer in one or two sentences first, then offer more. "
                     "Say 'that part is under development' where it is true -- "
                     "it is more credible than overclaiming, and a supervisor "
                     "can tell the difference."),
        "topics_available": [t.key for t in visit.session().topics],
    }, default=str)
