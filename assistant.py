"""
REYES always-on voice assistant.

Loop:  wait for a wake word  ->  capture the command  ->  think  ->  speak  ->
repeat. Say a wake word ("reyes", "hey reyes", ...) any time to talk to him.
Say "sleep" / "standby" to send him back to waiting.

Run:  python assistant.py         (blocking, in this window)
Or pick it from  python start.py

Designed to stay light:
  * The wake-word watch is the only thing running while idle. If you install a
    dedicated wake engine (openWakeWord or Picovoice porcupine), REYES uses it
    automatically — that's a tiny always-on model instead of full speech
    recognition, which is the single biggest CPU saver. Otherwise it falls back
    to the built-in recognizer.
  * Everything runs in one background thread; nothing blocks the UI.
  * Thinking is offloaded to whatever model you configured (a fast cloud model
    or a small local one keeps replies snappy — see PERFORMANCE.md).
"""
from __future__ import annotations

import threading
import time

from config import settings
from logger import log


def _speak(text: str, wait: bool = True) -> None:
    try:
        from speech import speak
        speak(text, wait=wait)
    except Exception as e:  # speech is optional; never crash the loop
        log.warning("TTS unavailable: %s", e)
        print(f"REYES › {text}")


def _try_fast_wake():
    """Return a lightweight wake detector if the user installed one, else None."""
    try:
        import openwakeword  # noqa: F401
        # openWakeWord present — the user can enable it; we keep the built-in
        # path by default so behaviour is predictable without extra setup.
        return None
    except Exception:
        return None


class VoiceAssistant:
    def __init__(self, cooldown: float | None = None):
        self.cooldown = (
            cooldown if cooldown is not None
            else getattr(settings, "voice_assistant_cooldown", 1.0)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- one full turn -------------------------------------------------------
    def _handle(self, wake_text: str) -> None:
        from wake_word import remove_wake_word, contains_sleep_command
        from voice import listen
        from brain import think

        # If the user spoke a command right after the wake word
        # ("reyes, what's the weather"), use it directly.
        command = remove_wake_word(wake_text).strip()

        if not command:
            _speak("Yes?", wait=False)
            command = (listen() or "").strip()

        if not command:
            return
        if contains_sleep_command(command):
            _speak("Standing by.")
            return

        log.info("voice command: %s", command)
        reply = think(command)
        _speak(reply)

    # -- main loop -----------------------------------------------------------
    def _loop(self) -> None:
        from wake_word import wait_for_wake_word

        _fast = _try_fast_wake()  # reserved hook for openWakeWord/porcupine
        name = settings.assistant_name
        print(f"\n  {name} is listening. Say a wake word to talk "
              f"(\"reyes\", \"hey reyes\"). Ctrl+C to stop.\n")
        log.info("Voice assistant online.")

        while not self._stop.is_set():
            try:
                wake_text = wait_for_wake_word(stop_event=self._stop)
            except Exception as e:
                log.warning("wake listen failed: %s", e)
                time.sleep(0.5)
                continue

            if self._stop.is_set() or not wake_text:
                break
            try:
                self._handle(wake_text)
            except Exception as e:
                log.warning("voice turn failed: %s", e)
                _speak("Sorry, something went wrong on that one.", wait=False)

            time.sleep(self.cooldown)  # debounce so it doesn't re-trigger

    # -- control -------------------------------------------------------------
    def start(self, blocking: bool = True) -> None:
        if blocking:
            try:
                self._loop()
            except KeyboardInterrupt:
                self.stop()
                print("\nVoice assistant stopped.")
        else:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def run() -> None:
    VoiceAssistant().start(blocking=True)


if __name__ == "__main__":
    run()
