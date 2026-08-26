"""REYES's "second brain" mode: open-mic, wake-word driven, no key, no
typing. Say "Reyes", "Bro", "Yo", or "Hello bro" (configurable via
WAKE_PHRASES in .env), or clap twice, and REYES starts listening for
what you actually want -- same agent core, same tools, same memory as
every other front door.

Run: python -m reyes_agent.wake_cli
Don't run this at the same time as voice_cli.py (push-to-talk) -- both
want exclusive use of the microphone.
"""

from __future__ import annotations

import sys

import speech_recognition as sr

from reyes_agent import config, warmup
from reyes_agent.agent import run_agent
from reyes_agent.provider import ProviderError
from reyes_agent.voice.stt import STTError, transcribe
from reyes_agent.voice.tts import TTSError, speak
from reyes_agent.voice.wake import listen_for_wake

EXIT_WORDS = {"exit", "quit", "bye"}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    warmup.start_background_keepalive()

    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    print(f"{config.ASSISTANT_NAME} -- second-brain mode. Calibrating mic for ambient noise...")
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1.5)
    # Auto-calibration sets a threshold safely above ambient noise -- pull
    # it down (WAKE_SENSITIVITY < 1.0) so a whisper still crosses it and
    # registers as "speech starting" at all. Gain-boosting the captured
    # clip (audio_utils.normalize_gain) only helps once it's captured;
    # this is what makes the capture actually start on a whisper.
    recognizer.energy_threshold *= config.WAKE_SENSITIVITY
    phrases = ", ".join(f'"{p}"' for p in config.WAKE_PHRASES)
    print(f"Listening. Say {phrases}, or clap twice. Ctrl+C to quit.\n")

    history: list[dict] = []

    while True:
        try:
            with mic as source:
                command = listen_for_wake(recognizer, source)
        except KeyboardInterrupt:
            print()
            break
        except Exception as exc:  # noqa: BLE001 -- a bad listen cycle must never kill the loop
            print(f"[hiccup listening: {exc}]")
            continue

        if command is None:
            continue  # heard something, not a wake trigger -- stay quiet, keep listening

        if not command:
            # Woke on the phrase (or a clap) alone, no command attached yet.
            print("(woke -- listening for your command...)")
            _speak_and_print("Yes?")
            try:
                with mic as source:
                    audio = recognizer.listen(source, phrase_time_limit=12)
                command = transcribe(audio.get_wav_data()).strip()
            except (sr.WaitTimeoutError, STTError) as exc:
                print(f"[didn't catch that: {exc}]")
                continue

        if not command:
            continue

        print(f"you: {command}")
        if command.lower().strip(".!? ") in EXIT_WORDS:
            break

        turn_start = len(history)
        history.append({"role": "user", "content": command})
        try:
            run_agent(
                history,
                spoken=True,
                action_source="voice",
                owner_authenticated=False,
            )
            reply = history[-1]["content"]
        except ProviderError as exc:
            del history[turn_start:]
            reply = f"Sorry, I couldn't respond: {exc}"

        print(f"{config.ASSISTANT_NAME}: {reply}")
        _speak_and_print(reply)


def _speak_and_print(text: str) -> None:
    import threading

    try:
        speak(text, threading.Event())
    except TTSError as exc:
        print(f"[couldn't speak that: {exc}]")


if __name__ == "__main__":
    main()
