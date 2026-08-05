"""Tier 3: push-to-talk voice, wrapping the exact same brain as cli.py.

Only the two ends of a turn change: input comes from transcribed speech
instead of typed text, and output gets spoken aloud in addition to printed.
`agent.run_agent` -- tools and all -- is untouched. The text path
(cli.py) stays alive; this is a second front door, not a replacement.
"""

from __future__ import annotations

import sys
import threading

import keyboard

from reyes_agent import config, warmup
from reyes_agent.agent import run_agent
from reyes_agent.provider import ProviderError
from reyes_agent.voice.capture import record_ptt
from reyes_agent.voice.stt import STTError, transcribe
from reyes_agent.voice.tts import TTSError, speak

EXIT_WORDS = {"exit", "quit", "bye"}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    warmup.start_background_keepalive()

    speaking = threading.Event()
    stop_speech = threading.Event()

    def _on_ptt_press(_event=None) -> None:
        # Fires on every press, including the one that starts a normal
        # recording -- only matters when REYES is mid-sentence, which is
        # exactly when we want a press to interrupt it.
        if speaking.is_set():
            stop_speech.set()

    keyboard.on_press_key(config.PTT_KEY, _on_ptt_press)

    history: list[dict] = []
    print(f"{config.ASSISTANT_NAME} -- voice online. Hold [{config.PTT_KEY}] to talk.")
    print("(Text mode is still available separately: python -m reyes_agent)")
    print("Ctrl+C to quit.\n")

    while True:
        print(f"\n(hold {config.PTT_KEY} to talk...)")
        try:
            _turn(history, speaking, stop_speech)
        except KeyboardInterrupt:
            print()
            break
        except Exception as exc:  # noqa: BLE001 -- a bad turn must never kill the loop
            print(f"[hiccup: {exc}]")


def _turn(history: list[dict], speaking: threading.Event, stop_speech: threading.Event) -> None:
    audio = record_ptt()
    if not audio:
        return

    try:
        transcript = transcribe(audio).strip()
    except STTError as exc:
        print(f"[couldn't hear that: {exc}]")
        return

    if not transcript:
        print("[heard nothing]")
        return

    print(f"you (heard): {transcript}")
    if transcript.lower().strip(".!? ") in EXIT_WORDS:
        raise KeyboardInterrupt

    turn_start = len(history)
    history.append({"role": "user", "content": transcript})

    print(f"{config.ASSISTANT_NAME}> ", end="", flush=True)
    reply_parts: list[str] = []

    def on_text(chunk: str) -> None:
        print(chunk, end="", flush=True)
        reply_parts.append(chunk)

    def on_tool_call(name: str, tool_input: dict, _id: str) -> None:
        print(f"\n  [using {name}({tool_input})]")
        print(f"{config.ASSISTANT_NAME}> ", end="", flush=True)

    try:
        run_agent(history, on_text=on_text, on_tool_call=on_tool_call)
        print()
    except ProviderError as exc:
        message = f"Sorry, I couldn't respond: {exc}"
        print(f"\n[{message}]")
        del history[turn_start:]
        _speak_safely(message, speaking, stop_speech)
        return

    _speak_safely("".join(reply_parts), speaking, stop_speech)


def _speak_safely(text: str, speaking: threading.Event, stop_speech: threading.Event) -> None:
    stop_speech.clear()
    speaking.set()
    try:
        speak(text, stop_speech)
    except TTSError as exc:
        print(f"[couldn't speak that: {exc}]")
    finally:
        speaking.clear()


if __name__ == "__main__":
    main()
