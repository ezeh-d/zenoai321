# wake_word.py

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

from voice import listen


# =========================================================
# REYES WAKE-WORD CONFIGURATION
# =========================================================

WAKE_WORDS = (
    "gee how far",
    "whats good",
    "what's good",
    "reyes",
    "gee",
    "guy",
    "blood",
    "hey reyes",
    "hello reyes",
)

SLEEP_COMMANDS = (
    "sleep",
    "go to sleep",
    "standby",
    "stand by",
    "reyes sleep",
)

WAKE_LISTEN_TIMEOUT = 2.5
WAKE_PHRASE_TIME_LIMIT = 5

WAKE_LANGUAGES = (
    "en-NG",
    "en-GB",
    "en-US",
)


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def normalize_wake_text(text: str) -> str:
    """
    Normalize recognized speech before wake-word matching.
    """

    normalized = str(text).lower().strip()

    normalized = re.sub(
        r"[^a-z0-9\s]",
        " ",
        normalized,
    )

    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    )

    return normalized.strip()


# =========================================================
# WAKE-WORD MATCHING
# =========================================================

def contains_wake_word(text: str) -> bool:
    """
    Return True when recognized speech contains a REYES wake word.
    """

    normalized = normalize_wake_text(text)

    if not normalized:
        return False

    for wake_word in WAKE_WORDS:
        normalized_wake_word = normalize_wake_text(
            wake_word
        )

        if normalized == normalized_wake_word:
            return True

        if normalized.startswith(
            normalized_wake_word + " "
        ):
            return True

        if f" {normalized_wake_word} " in (
            f" {normalized} "
        ):
            return True

    return False


def contains_sleep_command(text: str) -> bool:
    """
    Return True when the text requests sleep or standby.
    """

    normalized = normalize_wake_text(text)

    return normalized in {
        normalize_wake_text(command)
        for command in SLEEP_COMMANDS
    }


def remove_wake_word(text: str) -> str:
    """
    Remove the wake phrase and return any command that follows it.

    Examples:
        "Hey REYES open Chrome" -> "open chrome"
        "REYES" -> ""
    """

    normalized = normalize_wake_text(text)

    for wake_word in sorted(
        WAKE_WORDS,
        key=len,
        reverse=True,
    ):
        normalized_wake_word = normalize_wake_text(
            wake_word
        )

        if normalized == normalized_wake_word:
            return ""

        if normalized.startswith(
            normalized_wake_word + " "
        ):
            return normalized[
                len(normalized_wake_word):
            ].strip()

    return normalized


# =========================================================
# SINGLE WAKE-WORD CHECK
# =========================================================

def listen_for_wake_word_once() -> tuple[bool, str]:
    """
    Listen briefly and check for the REYES wake word.

    Returns:
        (wake_detected, recognized_text)
    """

    try:
        recognized_text = listen(
            timeout=WAKE_LISTEN_TIMEOUT,
            phrase_time_limit=WAKE_PHRASE_TIME_LIMIT,
            languages=list(WAKE_LANGUAGES),
            normalize_pidgin=False,
            duck_audio=False,
        )

    except Exception as error:
        print(
            f"[REYES Wake Word Error] {error}"
        )
        return False, ""

    if not recognized_text:
        return False, ""

    detected = contains_wake_word(
        recognized_text
    )

    if detected:
        print(
            "REYES: Wake word detected: "
            f"{recognized_text}"
        )

    return detected, recognized_text


# =========================================================
# BLOCKING WAKE-WORD LISTENER
# =========================================================

def wait_for_wake_word(
    stop_event: threading.Event | None = None,
) -> str:
    """
    Block until a REYES wake word is detected.

    This remains compatible with older REYES main.py versions
    that import wait_for_wake_word().
    """

    print(
        "REYES: Wake-word detector active."
    )

    while True:
        if (
            stop_event is not None
            and stop_event.is_set()
        ):
            return ""

        detected, recognized_text = (
            listen_for_wake_word_once()
        )

        if detected:
            return recognized_text

        time.sleep(0.1)


# =========================================================
# BACKGROUND WAKE-WORD DETECTOR
# =========================================================

class WakeWordDetector:
    """
    Background REYES wake-word listener.

    The callback is executed whenever a wake word is detected.
    """

    def __init__(
        self,
        on_wake: Callable[[str, str], None] | None = None,
    ) -> None:
        self.on_wake = on_wake

        self._running = threading.Event()
        self._paused = threading.Event()

        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and self._running.is_set()
        )

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def start(self) -> bool:
        """
        Start wake-word detection in a daemon thread.
        """

        if self.is_running:
            return False

        self._running.set()
        self._paused.clear()

        self._thread = threading.Thread(
            target=self._worker,
            name="REYES-Wake-Word",
            daemon=True,
        )

        self._thread.start()

        return True

    def pause(self) -> None:
        """
        Temporarily pause microphone checks.
        """

        self._paused.set()

    def resume(self) -> None:
        """
        Resume microphone checks.
        """

        if self._running.is_set():
            self._paused.clear()

    def stop(self) -> None:
        """
        Request clean detector shutdown.
        """

        self._running.clear()
        self._paused.clear()

    def join(
        self,
        timeout: float = 2.0,
    ) -> None:
        """
        Wait briefly for the detector thread to finish.
        """

        thread = self._thread

        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(
                timeout=max(0.0, timeout)
            )

    def shutdown(self) -> None:
        """
        Stop and briefly wait for the detector.
        """

        self.stop()
        self.join()

    def _worker(self) -> None:
        print(
            "REYES: Background wake-word detector started."
        )

        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.15)
                continue

            detected, recognized_text = (
                listen_for_wake_word_once()
            )

            if not self._running.is_set():
                break

            if not detected:
                time.sleep(0.1)
                continue

            command = remove_wake_word(
                recognized_text
            )

            callback = self.on_wake

            if callback is not None:
                try:
                    callback(
                        recognized_text,
                        command,
                    )

                except Exception as error:
                    print(
                        "[REYES Wake Callback Error] "
                        f"{error}"
                    )

            # Prevent the same phrase from activating repeatedly.
            time.sleep(0.8)

        print(
            "REYES: Background wake-word detector stopped."
        )


# =========================================================
# TERMINAL TEST
# =========================================================

def run_wake_word_test() -> None:
    """
    Test wake-word detection without opening the GUI.
    """

    print("=" * 60)
    print("REYES WAKE-WORD TEST")
    print("=" * 60)
    print("Say:")
    print("  Hey REYES")
    print("  REYES open Chrome")
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    try:
        while True:
            detected_text = wait_for_wake_word()

            if not detected_text:
                continue

            command = remove_wake_word(
                detected_text
            )

            print(
                f"\nWake phrase: {detected_text}"
            )

            if command:
                print(
                    f"Attached command: {command}"
                )
            else:
                print(
                    "No attached command. "
                    "REYES should now begin normal listening."
                )

            print(
                "\nWaiting for another wake phrase...\n"
            )

    except KeyboardInterrupt:
        print(
            "\nREYES wake-word test stopped."
        )


if __name__ == "__main__":
    run_wake_word_test()