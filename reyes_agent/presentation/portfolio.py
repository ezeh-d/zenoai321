"""What Divine has been learning, tied to where he actually used it.

    "Instead of 'I learned Python.' show: topic -> where used -> example."

That instruction is the whole design. "I learned Python" is unfalsifiable and
a supervisor knows it; "I used JSON for the agent registry, here is the file"
is checkable, and being checkable is what makes it worth saying.

So every topic here names a real file, and `portfolio()` DROPS any topic
whose file is not on disk. The failure mode is a shorter portfolio, never a
claim about work that cannot be pointed at.

CERTIFICATES ARE NOT CLAIMED
----------------------------
    "Do NOT claim completion certificates unless they actually exist."

None are claimed. The sources Divine gave -- W3Schools and Class Central --
are recorded as where he learned, not as qualifications he holds. A
supervisor asking "did you complete it?" should get "that's a question for
Divine", not a fabricated certificate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reyes_agent import config

# Supplied by the owner. Recorded as sources, never as credentials.
SOURCES = ("W3Schools", "Class Central")


@dataclass
class Topic:
    topic: str
    used_for: str
    evidence_path: str
    language: str = "Python"

    def as_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "used_for": self.used_for,
                "evidence": self.evidence_path, "language": self.language}


# Topic -> what it was used FOR -> the file that proves it. Every path is
# checked before the topic is shown.
_TOPICS: tuple[Topic, ...] = (
    Topic("Functions and modules",
          "Splitting the assistant into subsystems that can be tested on their own",
          "reyes_agent/tools/__init__.py"),
    Topic("Classes and dataclasses",
          "Modelling things like an agent, a route or a message as one object",
          "reyes_agent/remote_mic/routes.py"),
    Topic("JSON",
          "Configuration, the agent roster, and the presentation pack that "
          "works without internet",
          "reyes_agent/presentation/timeline.py"),
    Topic("APIs and HTTP",
          "Talking to the speech and language services, and serving the phone",
          "reyes_agent/web.py"),
    Topic("Async and threading",
          "Audio arriving continuously while the assistant is still answering",
          "reyes_agent/voice/stt/streaming.py"),
    Topic("Regular expressions",
          "Recognising the wake word across the spellings speech recognition "
          "produces",
          "reyes_agent/remote_mic/runtime.py"),
    Topic("Error handling",
          "Failing closed on a security check rather than guessing",
          "reyes_agent/creative/limits.py"),
    Topic("Testing with pytest",
          "Proving behaviour rather than asserting it -- including the cases "
          "that must NOT happen",
          "tests/test_conversation_continuity.py"),
    Topic("Git and version control",
          "Tracking the project's history, which is what the timeline is "
          "read from",
          ".git"),
    Topic("Networking",
          "Reaching the phone over Wi-Fi and the laptop hotspot, and telling "
          "local addresses from remote ones",
          "reyes_agent/remote_mic/routes.py"),
    Topic("Security thinking",
          "Deciding what a paired phone may do -- audio only, nothing else",
          "reyes_agent/phone_security.py"),
)


def portfolio() -> dict[str, Any]:
    """Only topics whose evidence is on disk right now."""
    kept, dropped = [], []
    for topic in _TOPICS:
        if (config.PROJECT_ROOT / topic.evidence_path).exists():
            kept.append(topic.as_dict())
        else:
            dropped.append(topic.topic)
    return {
        "learner": "Divine",
        "language": "Python",
        "sources": list(SOURCES),
        "certificates": ("Not claimed. These are where he learned, not "
                         "qualifications held -- ask Divine about completion."),
        "topics": kept,
        "dropped_for_lack_of_evidence": dropped,
        "why_python": ("It fits what the project needed: AI integration, "
                       "automation, APIs, and the backend that serves the "
                       "phone. Not a language chosen in the abstract."),
        "note": ("Each topic names a file. A topic whose file is missing is "
                 "removed rather than described."),
    }


def status() -> dict[str, Any]:
    data = portfolio()
    return {"state": "ONLINE", "topics": len(data["topics"]),
            "dropped": len(data["dropped_for_lack_of_evidence"]),
            "sources": list(SOURCES)}
