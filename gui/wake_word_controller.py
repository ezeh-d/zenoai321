# gui/wake_word_controller.py

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from wake_word import WakeWordDetector


class WakeWordController(QObject):
    """
    Qt-safe bridge between WakeWordDetector and the REYES GUI.

    WakeWordDetector runs in a Python background thread.
    This controller converts its callback into Qt signals so the
    GUI and VoiceController are never updated directly from that thread.
    """

    wake_detected = Signal(str, str)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    active_changed = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._lock = threading.Lock()
        self._enabled = True
        self._started = False

        self.detector = WakeWordDetector(
            on_wake=self._on_background_wake
        )

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def is_running(self) -> bool:
        return self.detector.is_running

    @property
    def is_paused(self) -> bool:
        return self.detector.is_paused

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # =====================================================
    # START AND STOP
    # =====================================================

    @Slot()
    def start(self) -> bool:
        """
        Start wake-word detection.
        """

        with self._lock:
            if self.detector.is_running:
                return False

            try:
                started = self.detector.start()

            except Exception as error:
                message = (
                    "Wake-word detector could not start: "
                    f"{error}"
                )

                self.error_occurred.emit(message)
                return False

            if started:
                self._started = True
                self.active_changed.emit(True)
                self.status_changed.emit(
                    'Wake word ready — say "ARIS"'
                )

            return started

    @Slot()
    def stop(self) -> None:
        """
        Stop wake-word detection.
        """

        with self._lock:
            try:
                self.detector.stop()

            except Exception as error:
                self.error_occurred.emit(
                    f"Wake-word stop error: {error}"
                )

            self._started = False
            self.active_changed.emit(False)

    def shutdown(
        self,
        wait_timeout_seconds: float = 2.0,
    ) -> None:
        """
        Stop and wait briefly for the background listener.
        """

        with self._lock:
            try:
                self.detector.stop()
                self.detector.join(
                    timeout=wait_timeout_seconds
                )

            except Exception as error:
                print(
                    f"[REYES Wake Shutdown Error] {error}"
                )

            self._started = False

    # =====================================================
    # PAUSE AND RESUME
    # =====================================================

    @Slot()
    def pause(self) -> None:
        """
        Pause wake detection while REYES uses the microphone,
        thinks, or speaks.
        """

        if not self.detector.is_running:
            return

        try:
            self.detector.pause()

        except Exception as error:
            self.error_occurred.emit(
                f"Wake-word pause error: {error}"
            )

    @Slot()
    def resume(self) -> None:
        """
        Resume listening for the wake word.
        """

        if not self._enabled:
            return

        if not self.detector.is_running:
            self.start()
            return

        try:
            self.detector.resume()

            self.status_changed.emit(
                'Waiting for "ARIS"'
            )

        except Exception as error:
            self.error_occurred.emit(
                f"Wake-word resume error: {error}"
            )

    # =====================================================
    # ENABLE CONTROL
    # =====================================================

    @Slot(bool)
    def set_enabled(
        self,
        enabled: bool,
    ) -> None:
        self._enabled = bool(enabled)

        if self._enabled:
            self.resume()
        else:
            self.pause()
            self.status_changed.emit(
                "Wake-word detection disabled"
            )

    @Slot()
    def toggle_enabled(self) -> bool:
        self.set_enabled(
            not self._enabled
        )

        return self._enabled

    # =====================================================
    # BACKGROUND CALLBACK
    # =====================================================

    def _on_background_wake(
        self,
        recognized_text: str,
        attached_command: str,
    ) -> None:
        """
        Called from WakeWordDetector's Python worker thread.

        Only emit a Qt signal here. Do not directly touch widgets.
        """

        if not self._enabled:
            return

        # Pause immediately to prevent duplicate activations while
        # the GUI processes this wake phrase.
        self.detector.pause()

        self.wake_detected.emit(
            str(recognized_text).strip(),
            str(attached_command).strip(),
        )