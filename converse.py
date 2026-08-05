"""
REYES conversation mode — talk to him like a mirror of yourself.

He listens, replies out loud, then listens again — no wake word needed each
turn. Just talk. Say "goodbye", "stop", or "that's all" to end.

Run:  python converse.py   (or pick it from python start.py)

Why it doesn't hear itself: each reply is spoken with wait=True, so REYES only
starts listening again *after* he's finished talking.
"""
from __future__ import annotations

from config import settings
from logger import log

EXIT_PHRASES = {
    "goodbye", "good bye", "bye", "stop", "exit", "quit",
    "that's all", "thats all", "that is all", "go to sleep", "sleep",
    "reyes stop", "shut down", "power down",
}

MAX_SILENCE = 6  # consecutive empty listens before he waits quietly


def _listen() -> str:
    from voice import listen
    return (listen() or "").strip()


def _speak(text: str, wait: bool = True) -> None:
    from speech import speak
    speak(text, wait=wait)


def converse() -> None:
    from brain import think

    name = settings.assistant_name
    print(f"\n  {name} conversation mode — just talk. Say 'goodbye' to end.\n")
    _speak(f"I'm here. Talk to me whenever you're ready.", wait=True)

    silence = 0
    while True:
        try:
            text = _listen()
        except KeyboardInterrupt:
            _speak("Talk soon.", wait=False)
            break
        except Exception as e:
            log.warning("listen failed: %s", e)
            continue

        if not text:
            silence += 1
            if silence >= MAX_SILENCE:
                _speak("I'll be right here when you need me.", wait=True)
                break
            continue

        silence = 0
        print(f"  you › {text}")

        cleaned = text.lower().strip(" .!?,")
        if cleaned in EXIT_PHRASES:
            _speak("Talk soon.", wait=True)
            break

        try:
            reply = think(text)
        except Exception as e:
            log.warning("think failed: %s", e)
            reply = "Sorry, something went wrong on that one."

        # wait=True so he finishes speaking before listening again (no echo)
        _speak(reply, wait=True)


def main() -> None:
    try:
        converse()
    except KeyboardInterrupt:
        print("\nConversation ended.")


if __name__ == "__main__":
    main()