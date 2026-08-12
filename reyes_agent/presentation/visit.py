"""Hosting a SIWES supervision visit as a conversation, not a recital.

THE FAILURE THIS IS BUILT AGAINST
---------------------------------
    "DO NOT MAKE ZENO RECITE A HUGE SPEECH WITHOUT ALLOWING THE VISITOR
     TO TALK."

An assistant handed a story and told to present it will deliver the story --
all of it, in order, regardless of what the person in the room says. That is
the natural failure mode, and it is worse than saying nothing, because a
supervisor who cannot get a word in learns nothing about the student.

So the story lives here as TOPICS THAT CAN BE VISITED, not as a script with a
next line. Nothing advances automatically. Each topic knows whether it has
been covered, so it is never explained twice; the session knows what was just
asked, so "how did he do that" resolves; and the opening is two sentences and
a question, because the visitor has just travelled from Osun State and the
first thing he should get is a chance to answer.

WHAT THE GUEST CAN AND CANNOT REACH
-----------------------------------
Engr Bello may talk to ZENO. That is not the same as being Divine. The guest
session carries the presentation facts and nothing else -- no private memory,
no mail, no files, no shell. `conversation.targets` already enforces the guest
boundary; this supplies the material a guest is allowed to hear.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reyes_agent import config

# Supplied by the owner for this visit. Deliberately minimal: ZENO must not
# elaborate on a real person beyond what Divine actually said.
VISITOR = {
    "visitor": "Engr Bello",
    "address_as": ["Engr Bello", "sir"],
    "institution": "Redeemer's University",
    "context": "SIWES supervision visit",
    "field": "Civil Engineering lecturer, as supplied by the owner",
    "travelling_from": "Osun State",
    "visiting": "Ado-Ekiti",
    "owner": "Divine",
    "siwes_start": "2026-07-01",
    "siwes_end": "2026-09-30",
    "placement": "T21 Services",
    "project_original_name": "REYES",
    "project_current_name": "ZENO",
}

# Anything ZENO must not infer about a real person it has never met.
DO_NOT_INVENT = ("exact academic title", "rank", "department position",
                 "personal history", "private information", "publications",
                 "years of service")


@dataclass
class Topic:
    key: str
    heading: str
    substance: str
    seconds: int = 20          # how long this should take SPOKEN
    covered: bool = False
    asked_about: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "heading": self.heading,
                "seconds": self.seconds, "covered": self.covered,
                "asked_about": self.asked_about}


def _topics() -> list[Topic]:
    """The material, as things that can be asked about in any order."""
    return [
        Topic("greeting", "Arrival and journey",
              "Greet him, ask how the journey from Osun State to Ado-Ekiti "
              "was, and then stop talking and let him answer.", 8),
        Topic("yesterday", "His other SIWES visits",
              "Ask how the previous day's visits to other students went. One "
              "question, then listen.", 8),
        Topic("siwes", "Divine's SIWES",
              "Three months at T21 Services, 1 July to 30 September 2026.", 15),
        Topic("origin", "How the project began",
              "Mr BJ and Mr K called Divine and the others together and "
              "encouraged them to build something of their own during the "
              "training. Divine decided to build an AI assistant.", 30),
        Topic("rename", "REYES became ZENO",
              "It was called REYES first and grew into ZENO as the direction "
              "changed. The package is still named reyes_agent, which is the "
              "part of that history that survives in the code.", 20),
        Topic("evolution", "How it developed",
              "Voice, then listening, then memory, then tools, then agents. "
              "Dates come from the timeline, and the stretch before version "
              "control is stated as unrecorded rather than guessed.", 60),
        Topic("architecture", "How it works",
              "Speech in, understanding, routing to memory or an agent or a "
              "tool, the real action, verification, then the reply.", 45),
        Topic("agents", "The specialist agents",
              "ZENO is the executive; specialists handle categories and can "
              "delegate to their own workers. Read from the real registry.", 40),
        Topic("contribution", "What Divine actually did",
              "Architecture, integration, configuration, testing, debugging "
              "and iteration -- not inventing Python, the models or the "
              "libraries.", 40),
        Topic("ai_assistance", "Whether AI helped build it",
              "Yes. Claude Code and Codex were used. Divine directs the "
              "project, decides what it should do, tests it and fixes it.", 25),
        Topic("company", "Company work during SIWES",
              "ZENO was the main technical project but not the only work: NHS "
              "job applications, interview requests and follow-ups, and "
              "general computer and operational tasks.", 30),
        Topic("python", "Learning Python",
              "Learned deliberately alongside the project, using W3Schools and "
              "Class Central, with something real to apply it to.", 25),
        Topic("challenges", "What went wrong",
              "Only real ones, from the project record.", 40),
        Topic("learned", "What he has learned",
              "Only what the work supports.", 30),
        Topic("status", "What works today",
              "Feature status straight from the honest register: working, "
              "partial, or under development.", 35),
        Topic("future", "Where it goes next", "Plans, stated as plans.", 20),
    ]


@dataclass
class VisitSession:
    """Short-term conversational state for one visit. Guest-scoped."""

    active: bool = False
    started_at: float = 0.0
    visitor: str = VISITOR["visitor"]
    topics: list[Topic] = field(default_factory=_topics)
    last_question: str = ""
    last_topic: str = ""
    visitor_said: list[str] = field(default_factory=list)
    technical_depth: str = "normal"     # simple | normal | technical
    owner_directives: list[str] = field(default_factory=list)
    spoken_seconds: float = 0.0

    # -- lifecycle ----------------------------------------------------
    def start(self) -> dict[str, Any]:
        self.active = True
        self.started_at = time.time()
        self.topics = _topics()
        self.visitor_said.clear()
        self.owner_directives.clear()
        self.last_question = self.last_topic = ""
        self.technical_depth = "normal"
        self.spoken_seconds = 0.0
        return self.opening()

    def end(self) -> str:
        self.active = False
        return ("It was really nice meeting you, Engr Bello. Thank you for "
                "coming to see what Divine has been working on. Safe journey "
                "back, sir.")

    # -- the opening --------------------------------------------------
    def opening(self) -> dict[str, Any]:
        """Two sentences and ONE question. Then silence.

        The temptation is to introduce the project here. He has just come off
        a road from Osun State -- the first thing he should get is a turn.
        """
        self.mark("greeting")
        self.last_question = "How was your journey?"
        return {
            "say": ("Good afternoon, Engr Bello. It's nice to meet you, sir -- "
                    "I'm ZENO. How was the journey down from Osun State?"),
            "then": "WAIT_FOR_ANSWER",
            "do_not": "Do not continue into the project. He has not spoken yet.",
        }

    # -- turn taking --------------------------------------------------
    def heard(self, utterance: str) -> dict[str, Any]:
        """Record what the visitor said and suggest what to do with it."""
        said = (utterance or "").strip()
        if said:
            self.visitor_said.append(said[:400])
        low = said.lower()

        depth = self.technical_depth
        if any(w in low for w in ("architecture", "how does it work", "stack",
                                  "framework", "algorithm", "implementation",
                                  "protocol", "latency", "database")):
            depth = "technical"
        elif any(w in low for w in ("simply", "in simple terms", "layman",
                                    "briefly", "short")):
            depth = "simple"
        self.technical_depth = depth

        return {
            "acknowledge_first": True,
            "technical_depth": depth,
            "already_covered": [t.key for t in self.topics if t.covered],
            "guidance": ("Answer what he actually asked. React to his answer "
                         "before moving on -- a person responds to what was "
                         "said, then continues."),
        }

    def suggest_next(self) -> dict[str, Any]:
        """What could come next -- a suggestion, never an instruction.

        Returned only when the visitor has stopped and nothing is pending. It
        does not fire on its own, because a conversation that advances by
        itself is a recital with pauses in it.
        """
        pending = [t for t in self.topics if not t.covered]
        if not pending:
            return {"suggest": "", "note": "Everything has been covered. Let "
                                           "him lead."}
        nxt = pending[0]
        return {"suggest": nxt.key, "heading": nxt.heading,
                "opening_line": ("Divine asked me to tell you a little about "
                                 "what he's been doing here." if nxt.key == "siwes"
                                 else ""),
                "budget_seconds": nxt.seconds}

    # -- pacing -------------------------------------------------------
    def mark(self, key: str, spoken_seconds: float = 0.0) -> None:
        for topic in self.topics:
            if topic.key == key:
                topic.covered = True
                topic.asked_about += 1
                self.last_topic = key
        self.spoken_seconds += spoken_seconds

    def should_pause(self, about_to_speak_seconds: float) -> tuple[bool, str]:
        """Has ZENO been talking too long to keep going.

            "If ZENO has just spoken for 60-90 seconds: prefer pausing."
        """
        if about_to_speak_seconds > 90:
            return True, ("That is too long for one turn. Give the short "
                          "version and offer the rest.")
        if self.spoken_seconds > 90:
            return True, ("You have been talking for a while. Hand him the "
                          "turn: 'That's the short version -- would you like "
                          "the technical side?'")
        return False, ""

    def covered(self, key: str) -> bool:
        return any(t.key == key and t.covered for t in self.topics)

    def repeat_guard(self, key: str) -> str:
        """What to say instead of explaining something twice."""
        if self.covered(key):
            return ("Already covered. Refer back to it rather than repeating: "
                    "'Aside from the Python we talked about...'")
        return ""

    # -- owner control ------------------------------------------------
    def owner_says(self, directive: str) -> dict[str, Any]:
        """Divine's instructions outrank the visitor's, immediately."""
        text = (directive or "").strip().lower()
        self.owner_directives.append(text[:120])
        rules = [
            (("keep it short", "shorter", "briefly"), "BRIEF",
             "One or two sentences per answer until told otherwise."),
            (("explain technically", "more technical", "go deeper"), "TECHNICAL",
             "Increase depth; he wants the engineering."),
            (("don't mention", "do not mention", "skip that"), "SUPPRESS",
             "Do not raise that subject again this visit."),
            (("move on", "next"), "MOVE_ON", "Change topic now."),
            (("show him", "demonstrate"), "DEMO_ALLOWED",
             "A demonstration is now authorised by the owner."),
            (("come back to me", "talk to me"), "OWNER", "Address Divine again."),
            (("let him ask", "let him talk"), "LISTEN",
             "Stop presenting. Wait for the visitor."),
            (("end presentation", "that's all", "wrap up"), "END",
             "Close warmly and stop."),
            (("standby", "stand by"), "STANDBY", "Go quiet until called."),
        ]
        for triggers, action, note in rules:
            if any(t in text for t in triggers):
                if action == "TECHNICAL":
                    self.technical_depth = "technical"
                if action == "BRIEF":
                    self.technical_depth = "simple"
                return {"action": action, "note": note, "obey": "immediately"}
        return {"action": "NOTED", "note": "Follow it as stated.",
                "obey": "immediately"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "active": self.active, "visitor": self.visitor,
            "elapsed_s": round(time.time() - self.started_at, 1) if self.started_at else 0,
            "technical_depth": self.technical_depth,
            "last_question": self.last_question, "last_topic": self.last_topic,
            "visitor_turns": len(self.visitor_said),
            "spoken_seconds": round(self.spoken_seconds, 1),
            "topics": [t.as_dict() for t in self.topics],
            "owner_directives": self.owner_directives[-5:],
        }


_session = VisitSession()


def session() -> VisitSession:
    return _session


def profile_path() -> Path:
    return config.PROJECT_ROOT / "presentation" / "engr_bello_visit.json"


def write_profile() -> Path:
    target = profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({**VISITOR, "do_not_invent": list(DO_NOT_INVENT)},
                                 indent=2), encoding="utf-8")
    return target


def briefing() -> dict[str, Any]:
    """Everything ZENO may draw on for this visit -- and nothing more."""
    from reyes_agent.presentation import facts, timeline

    try:
        feature_status = facts.feature_status()
    except Exception:  # noqa: BLE001
        feature_status = []
    return {
        "visitor": VISITOR,
        "do_not_invent": list(DO_NOT_INVENT),
        "timeline": timeline.build(),
        "features": feature_status,
        "guest_boundary": ("Presentation facts only. No private memory, mail, "
                           "files, credentials or shell -- talking to ZENO is "
                           "not the same as being Divine."),
        "tone": ("Warm, respectful, confident, relaxed. Not overexcited, not "
                 "advertising, not terrified."),
    }


def status() -> dict[str, Any]:
    return {"state": "ACTIVE" if _session.active else "STANDBY",
            "session": _session.as_dict(),
            "profile": str(profile_path()),
            "principle": ("Topics can be visited in any order. Nothing "
                          "advances on its own -- a conversation that "
                          "advances by itself is a recital with pauses.")}
