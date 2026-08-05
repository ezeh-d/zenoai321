# gui/voice_controller.py

from __future__ import annotations

import inspect
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot


# =========================================================
# VOICE RESULT MODEL
# =========================================================

@dataclass
class VoiceResult:
    """
    One complete REYES voice interaction.
    """

    user_text: str
    assistant_text: str
    success: bool
    error: str | None = None


# =========================================================
# BACKEND ADAPTER
# =========================================================

class ReyesBackendAdapter:
    """
    Connects the new PySide6 GUI to the existing REYES backend.

    The adapter attempts to use these project modules:

        voice.py
            listen()

        speech.py
            speak(text)

        brain.py
            think(text)

    It also supports some common alternative function names.
    """

    LISTEN_FUNCTION_NAMES = (
        "listen",
        "listen_for_command",
        "recognize_speech",
        "take_command",
        "get_voice_input",
    )

    THINK_FUNCTION_NAMES = (
        "think",
        "process_command",
        "handle_command",
        "ask",
        "respond",
    )

    SPEAK_FUNCTION_NAMES = (
        "speak",
        "say",
        "speak_text",
        "text_to_speech",
    )

    def __init__(self) -> None:
        self.listen_function: Callable[..., Any] | None = None
        self.think_function: Callable[..., Any] | None = None
        self.speak_function: Callable[..., Any] | None = None

        self.import_errors: list[str] = []

        self.reload()

    # =====================================================
    # MODULE LOADING
    # =====================================================

    def reload(self) -> None:
        """
        Reload references to the REYES backend functions.
        """

        self.listen_function = self._find_function(
            module_name="voice",
            function_names=self.LISTEN_FUNCTION_NAMES,
        )

        self.think_function = self._find_function(
            module_name="brain",
            function_names=self.THINK_FUNCTION_NAMES,
        )

        self.speak_function = self._find_function(
            module_name="speech",
            function_names=self.SPEAK_FUNCTION_NAMES,
        )

    def _find_function(
        self,
        module_name: str,
        function_names: tuple[str, ...],
    ) -> Callable[..., Any] | None:
        """
        Import a module and return the first matching function.
        """

        try:
            module = __import__(
                module_name,
                fromlist=["*"],
            )
        except Exception as error:
            self.import_errors.append(
                f"{module_name}.py: {error}"
            )
            return None

        for name in function_names:
            candidate = getattr(
                module,
                name,
                None,
            )

            if callable(candidate):
                return candidate

        self.import_errors.append(
            f"{module_name}.py does not contain any supported "
            f"function: {', '.join(function_names)}"
        )

        return None

    # =====================================================
    # AVAILABILITY
    # =====================================================

    @property
    def can_listen(self) -> bool:
        return callable(self.listen_function)

    @property
    def can_think(self) -> bool:
        return callable(self.think_function)

    @property
    def can_speak(self) -> bool:
        return callable(self.speak_function)

    @property
    def ready(self) -> bool:
        return (
            self.can_listen
            and self.can_think
            and self.can_speak
        )

    def status_message(self) -> str:
        """
        Return a readable backend status message.
        """

        missing: list[str] = []

        if not self.can_listen:
            missing.append("voice.listen")

        if not self.can_think:
            missing.append("brain.think")

        if not self.can_speak:
            missing.append("speech.speak")

        if not missing:
            return "REYES backend connected"

        return (
            "Missing backend function(s): "
            + ", ".join(missing)
        )

    # =====================================================
    # BACKEND CALLS
    # =====================================================

    def listen(self) -> str:
        """
        Capture one spoken command.
        """

        if self.listen_function is None:
            raise RuntimeError(
                "No supported listening function was found in voice.py"
            )

        result = self._call_function(
            self.listen_function
        )

        return self._normalize_text(result)

    def think(self, command: str) -> str:
        """
        Process one user command through the REYES brain.
        """

        if self.think_function is None:
            raise RuntimeError(
                "No supported processing function was found in brain.py"
            )

        result = self._call_function(
            self.think_function,
            command,
        )

        return self._normalize_response(result)

    def speak(self, text: str) -> None:
        """
        Speak one response through the REYES TTS system.
        """

        if not text.strip():
            return

        if self.speak_function is None:
            raise RuntimeError(
                "No supported speaking function was found in speech.py"
            )

        self._call_function(
            self.speak_function,
            text,
        )

    # =====================================================
    # FUNCTION COMPATIBILITY
    # =====================================================

    @staticmethod
    def _call_function(
        function: Callable[..., Any],
        *args: Any,
    ) -> Any:
        """
        Call backend functions while handling simple signature differences.
        """

        try:
            signature = inspect.signature(
                function
            )
        except (TypeError, ValueError):
            return function(*args)

        parameters = list(
            signature.parameters.values()
        )

        required_positional = [
            parameter
            for parameter in parameters
            if parameter.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
            and parameter.default
            is inspect.Parameter.empty
        ]

        accepts_varargs = any(
            parameter.kind
            == inspect.Parameter.VAR_POSITIONAL
            for parameter in parameters
        )

        if accepts_varargs:
            return function(*args)

        if not required_positional:
            return function()

        return function(*args)

    # =====================================================
    # RESPONSE NORMALIZATION
    # =====================================================

    @staticmethod
    def _normalize_text(
        result: Any,
    ) -> str:
        """
        Convert speech-recognition output into plain text.
        """

        if result is None:
            return ""

        if isinstance(result, str):
            return result.strip()

        if isinstance(result, dict):
            for key in (
                "text",
                "command",
                "query",
                "transcript",
                "message",
            ):
                value = result.get(key)

                if isinstance(value, str):
                    return value.strip()

        if isinstance(result, (list, tuple)):
            for value in result:
                if isinstance(value, str):
                    return value.strip()

        return str(result).strip()

    @staticmethod
    def _normalize_response(
        result: Any,
    ) -> str:
        """
        Convert brain output into a user-facing response.
        """

        if result is None:
            return ""

        if isinstance(result, str):
            return result.strip()

        if isinstance(result, dict):
            for key in (
                "response",
                "answer",
                "text",
                "message",
                "content",
                "result",
            ):
                value = result.get(key)

                if isinstance(value, str):
                    return value.strip()

        if isinstance(result, (list, tuple)):
            for value in result:
                if isinstance(value, str):
                    return value.strip()

        response_attribute = getattr(
            result,
            "response",
            None,
        )

        if isinstance(response_attribute, str):
            return response_attribute.strip()

        content_attribute = getattr(
            result,
            "content",
            None,
        )

        if isinstance(content_attribute, str):
            return content_attribute.strip()

        return str(result).strip()


# =========================================================
# VOICE CONTROLLER
# =========================================================

class VoiceController(QObject):
    """
    Thread-safe controller for one full REYES voice interaction.

    Interaction flow:

        standby
        listening
        thinking
        speaking
        standby

    The worker thread performs microphone, brain, and speech work.
    The GUI remains responsive throughout the interaction.
    """

    state_changed = Signal(str)
    status_changed = Signal(str)

    listening_started = Signal()
    listening_finished = Signal(str)

    thinking_started = Signal(str)
    thinking_finished = Signal(str)

    speaking_started = Signal(str)
    speaking_finished = Signal(str)

    transcript_ready = Signal(str)
    response_ready = Signal(str)

    interaction_finished = Signal(object)

    error_occurred = Signal(str)

    backend_status_changed = Signal(
        bool,
        str,
    )

    active_changed = Signal(bool)
    muted_changed = Signal(bool)
    continuous_mode_changed = Signal(bool)

    VALID_STATES = {
        "standby",
        "activated",
        "listening",
        "thinking",
        "speaking",
        "sleeping",
        "error",
        "stopped",
    }

    def __init__(
        self,
        parent: QObject | None = None,
        auto_continue_delay_ms: int = 500,
    ) -> None:
        super().__init__(parent)

        self.backend = ReyesBackendAdapter()

        self._state = "standby"

        self._active = False
        self._muted = False
        self._continuous_mode = False

        self._stop_requested = threading.Event()
        self._cancel_requested = threading.Event()

        self._worker_thread: threading.Thread | None = None

        self._command_queue: queue.Queue[str] = queue.Queue()

        self.auto_continue_delay_ms = max(
            100,
            int(auto_continue_delay_ms),
        )

        self._continuous_timer = QTimer(self)
        self._continuous_timer.setSingleShot(True)
        self._continuous_timer.timeout.connect(
            self._continue_listening
        )

        self._emit_backend_status()

    # =====================================================
    # PROPERTIES
    # =====================================================

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_muted(self) -> bool:
        return self._muted

    @property
    def continuous_mode(self) -> bool:
        return self._continuous_mode

    @property
    def backend_ready(self) -> bool:
        return self.backend.ready

    # =====================================================
    # BACKEND STATUS
    # =====================================================

    @Slot()
    def reload_backend(self) -> None:
        """
        Reconnect to voice.py, brain.py, and speech.py.
        """

        self.backend.import_errors.clear()
        self.backend.reload()
        self._emit_backend_status()

    def _emit_backend_status(self) -> None:
        self.backend_status_changed.emit(
            self.backend.ready,
            self.backend.status_message(),
        )

    # =====================================================
    # STATE MANAGEMENT
    # =====================================================

    def _set_state(
        self,
        state: str,
        message: str | None = None,
    ) -> None:
        normalized = state.strip().lower()

        if normalized not in self.VALID_STATES:
            normalized = "standby"

        self._state = normalized
        self.state_changed.emit(normalized)

        default_messages = {
            "standby": "Awaiting voice activation",
            "activated": "REYES voice system activated",
            "listening": "Listening for your command",
            "thinking": "Processing your request",
            "speaking": "Delivering response",
            "sleeping": "Voice system sleeping",
            "error": "Voice system error",
            "stopped": "Voice controller stopped",
        }

        self.status_changed.emit(
            message
            or default_messages[normalized]
        )

    # =====================================================
    # START LISTENING
    # =====================================================

    @Slot()
    def start_listening(self) -> bool:
        """
        Start one complete voice interaction.

        Returns True when a worker starts.
        """

        if self._active:
            self.status_changed.emit(
                "REYES is already processing"
            )
            return False

        if not self.backend.can_listen:
            self._set_state(
                "error",
                "voice.py is not connected",
            )

            self.error_occurred.emit(
                self.backend.status_message()
            )

            return False

        self._stop_requested.clear()
        self._cancel_requested.clear()

        self._active = True
        self.active_changed.emit(True)

        self._worker_thread = threading.Thread(
            target=self._voice_interaction_worker,
            name="REYES-Voice-Worker",
            daemon=True,
        )

        self._worker_thread.start()

        return True

    @Slot()
    def activate(self) -> bool:
        """
        Alias for starting voice input.
        """

        return self.start_listening()

    # =====================================================
    # TEXT COMMANDS
    # =====================================================

    @Slot(str)
    def process_text(
        self,
        command: str,
    ) -> bool:
        """
        Process text through the same brain and speech pipeline.

        This is useful for testing the GUI without a microphone.
        """

        cleaned_command = command.strip()

        if not cleaned_command:
            self.status_changed.emit(
                "No command was provided"
            )
            return False

        if self._active:
            self.status_changed.emit(
                "REYES is already processing"
            )
            return False

        if not self.backend.can_think:
            self._set_state(
                "error",
                "brain.py is not connected",
            )

            self.error_occurred.emit(
                self.backend.status_message()
            )

            return False

        self._stop_requested.clear()
        self._cancel_requested.clear()

        self._active = True
        self.active_changed.emit(True)

        self._worker_thread = threading.Thread(
            target=self._text_interaction_worker,
            args=(cleaned_command,),
            name="REYES-Text-Worker",
            daemon=True,
        )

        self._worker_thread.start()

        return True

    # =====================================================
    # VOICE WORKER
    # =====================================================

    def _voice_interaction_worker(self) -> None:
        user_text = ""
        assistant_text = ""

        try:
            self._safe_set_state(
                "listening",
                "Listening for your command",
            )

            self.listening_started.emit()

            user_text = self.backend.listen()

            if self._stop_requested.is_set():
                return

            if self._cancel_requested.is_set():
                self._safe_finish_cancelled()
                return

            if not user_text:
                message = (
                    "I did not hear a command. "
                    "Please try again."
                )

                self.listening_finished.emit("")
                self._safe_set_state(
                    "standby",
                    message,
                )

                self.interaction_finished.emit(
                    VoiceResult(
                        user_text="",
                        assistant_text="",
                        success=False,
                        error=message,
                    )
                )

                return

            self.listening_finished.emit(
                user_text
            )

            self.transcript_ready.emit(
                user_text
            )

            assistant_text = self._process_command(
                user_text
            )

            if self._stop_requested.is_set():
                return

            if self._cancel_requested.is_set():
                self._safe_finish_cancelled()
                return

            self._deliver_response(
                assistant_text
            )

            self.interaction_finished.emit(
                VoiceResult(
                    user_text=user_text,
                    assistant_text=assistant_text,
                    success=True,
                )
            )

        except Exception as error:
            self._handle_worker_error(
                error=error,
                user_text=user_text,
                assistant_text=assistant_text,
            )

        finally:
            self._finish_worker()

    # =====================================================
    # TEXT WORKER
    # =====================================================

    def _text_interaction_worker(
        self,
        command: str,
    ) -> None:
        assistant_text = ""

        try:
            self.transcript_ready.emit(
                command
            )

            assistant_text = self._process_command(
                command
            )

            if self._stop_requested.is_set():
                return

            if self._cancel_requested.is_set():
                self._safe_finish_cancelled()
                return

            self._deliver_response(
                assistant_text
            )

            self.interaction_finished.emit(
                VoiceResult(
                    user_text=command,
                    assistant_text=assistant_text,
                    success=True,
                )
            )

        except Exception as error:
            self._handle_worker_error(
                error=error,
                user_text=command,
                assistant_text=assistant_text,
            )

        finally:
            self._finish_worker()

    # =====================================================
    # COMMAND PROCESSING
    # =====================================================

    def _process_command(
        self,
        command: str,
    ) -> str:
        if not self.backend.can_think:
            raise RuntimeError(
                "brain.py does not expose a supported command function"
            )

        self._safe_set_state(
            "thinking",
            "Analyzing your request",
        )

        self.thinking_started.emit(
            command
        )

        response = self.backend.think(
            command
        )

        if not response:
            response = (
                "I completed the request, but no spoken "
                "response was returned."
            )

        self.thinking_finished.emit(
            response
        )

        self.response_ready.emit(
            response
        )

        return response

    def _deliver_response(
        self,
        response: str,
    ) -> None:
        if self._muted:
            self._safe_set_state(
                "standby",
                "Response ready. Voice output is muted.",
            )
            return

        if not self.backend.can_speak:
            self._safe_set_state(
                "standby",
                "Response ready. Speech output is unavailable.",
            )
            return

        self._safe_set_state(
            "speaking",
            "Delivering response",
        )

        self.speaking_started.emit(
            response
        )

        self.backend.speak(
            response
        )

        self.speaking_finished.emit(
            response
        )

    # =====================================================
    # THREAD-SAFE GUI STATE
    # =====================================================

    def _safe_set_state(
        self,
        state: str,
        message: str,
    ) -> None:
        """
        Emit signals from the worker thread.

        Qt delivers these safely to connected GUI objects.
        """

        self._state = state
        self.state_changed.emit(state)
        self.status_changed.emit(message)

    def _safe_finish_cancelled(self) -> None:
        self._safe_set_state(
            "standby",
            "Interaction cancelled",
        )

    # =====================================================
    # ERROR HANDLING
    # =====================================================

    def _handle_worker_error(
        self,
        error: Exception,
        user_text: str,
        assistant_text: str,
    ) -> None:
        message = (
            f"{type(error).__name__}: {error}"
        )

        self._safe_set_state(
            "error",
            message,
        )

        self.error_occurred.emit(
            message
        )

        self.interaction_finished.emit(
            VoiceResult(
                user_text=user_text,
                assistant_text=assistant_text,
                success=False,
                error=message,
            )
        )

    # =====================================================
    # WORKER COMPLETION
    # =====================================================

    def _finish_worker(self) -> None:
        # Return music/application audio to exactly the volume it had before
        # REYES entered command-listening mode.
        try:
            from audio_control import restore_music
            restore_music()
        except Exception as error:
            print(f"[REYES Audio Restore Warning] {error}")

        self._active = False
        self.active_changed.emit(False)

        if self._stop_requested.is_set():
            self._safe_set_state(
                "stopped",
                "Voice controller stopped",
            )
            return

        if self._state != "error":
            self._safe_set_state(
                "standby",
                "Awaiting voice activation",
            )

        if (
            self._continuous_mode
            and not self._stop_requested.is_set()
            and not self._cancel_requested.is_set()
        ):
            self._continuous_timer.start(
                self.auto_continue_delay_ms
            )

    @Slot()
    def _continue_listening(self) -> None:
        if (
            self._continuous_mode
            and not self._active
            and not self._stop_requested.is_set()
        ):
            self.start_listening()

    # =====================================================
    # MUTE CONTROL
    # =====================================================

    @Slot(bool)
    def set_muted(
        self,
        muted: bool,
    ) -> None:
        self._muted = bool(muted)

        self.muted_changed.emit(
            self._muted
        )

        if self._muted:
            self.status_changed.emit(
                "Voice output muted"
            )
        else:
            self.status_changed.emit(
                "Voice output enabled"
            )

    @Slot()
    def toggle_muted(self) -> bool:
        self.set_muted(
            not self._muted
        )

        return self._muted

    # =====================================================
    # CONTINUOUS MODE
    # =====================================================

    @Slot(bool)
    def set_continuous_mode(
        self,
        enabled: bool,
    ) -> None:
        self._continuous_mode = bool(
            enabled
        )

        self.continuous_mode_changed.emit(
            self._continuous_mode
        )

        if not self._continuous_mode:
            self._continuous_timer.stop()

        self.status_changed.emit(
            "Continuous listening enabled"
            if self._continuous_mode
            else "Continuous listening disabled"
        )

    @Slot()
    def toggle_continuous_mode(self) -> bool:
        self.set_continuous_mode(
            not self._continuous_mode
        )

        return self._continuous_mode

    # =====================================================
    # CANCEL AND STOP
    # =====================================================

    @Slot()
    def cancel_current_interaction(self) -> None:
        """
        Request cancellation of the current pipeline.

        Blocking microphone or TTS calls cannot always be interrupted
        instantly, but the remaining stages will not continue.
        """

        self._cancel_requested.set()
        self._continuous_timer.stop()

        self.status_changed.emit(
            "Cancelling current interaction"
        )

    @Slot()
    def sleep(self) -> None:
        """
        Stop continuous listening and enter sleep mode.
        """

        self._continuous_mode = False
        self.continuous_mode_changed.emit(
            False
        )

        self._continuous_timer.stop()
        self._cancel_requested.set()

        self._set_state(
            "sleeping",
            "Voice system sleeping",
        )

    @Slot()
    def wake(self) -> None:
        """
        Return from sleep mode.
        """

        self._stop_requested.clear()
        self._cancel_requested.clear()

        self._set_state(
            "activated",
            "REYES voice system online",
        )

        QTimer.singleShot(
            600,
            lambda: self._set_state(
                "standby",
                "Awaiting voice activation",
            ),
        )

    @Slot()
    def stop(self) -> None:
        """
        Shut down the controller.
        """

        self._stop_requested.set()
        self._cancel_requested.set()

        self._continuous_mode = False

        self._continuous_timer.stop()

        self.continuous_mode_changed.emit(
            False
        )

        self._set_state(
            "stopped",
            "Voice controller stopped",
        )

    # =====================================================
    # CLEANUP
    # =====================================================

    def shutdown(
        self,
        wait_timeout_seconds: float = 1.5,
    ) -> None:
        """
        Stop the controller and briefly wait for its worker.
        """

        self.stop()

        worker = self._worker_thread

        if (
            worker is not None
            and worker.is_alive()
            and worker is not threading.current_thread()
        ):
            worker.join(
                timeout=max(
                    0.0,
                    wait_timeout_seconds,
                )
            )


# =========================================================
# STANDALONE TEST
# =========================================================

if __name__ == "__main__":
    import sys

    from PySide6.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from gui.theme import (
        BACKGROUND,
        GLOBAL_STYLESHEET,
        PRIMARY,
        TEXT_PRIMARY,
    )

    app = QApplication(sys.argv)
    app.setStyleSheet(
        GLOBAL_STYLESHEET
    )

    window = QWidget()
    window.setWindowTitle(
        "REYES Voice Controller Test"
    )
    window.resize(
        620,
        420,
    )

    window.setStyleSheet(
        f"background-color: {BACKGROUND};"
    )

    controller = VoiceController(
        parent=window
    )

    title_label = QLabel(
        "REYES VOICE CONTROLLER"
    )

    title_label.setStyleSheet(
        f"""
        QLabel {{
            color: {PRIMARY};
            font-size: 24px;
            font-weight: 700;
        }}
        """
    )

    state_label = QLabel(
        "STATE: STANDBY"
    )

    status_label = QLabel(
        controller.backend.status_message()
    )

    transcript_label = QLabel(
        "YOU: --"
    )

    response_label = QLabel(
        "REYES: --"
    )

    for label in (
        state_label,
        status_label,
        transcript_label,
        response_label,
    ):
        label.setWordWrap(True)
        label.setStyleSheet(
            f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: 13px;
                padding: 8px;
            }}
            """
        )

    listen_button = QPushButton(
        "START LISTENING"
    )

    test_text_button = QPushButton(
        "TEST TEXT COMMAND"
    )

    mute_button = QPushButton(
        "MUTE: OFF"
    )

    continuous_button = QPushButton(
        "CONTINUOUS: OFF"
    )

    cancel_button = QPushButton(
        "CANCEL"
    )

    def update_state(
        state: str,
    ) -> None:
        state_label.setText(
            f"STATE: {state.upper()}"
        )

    def update_status(
        message: str,
    ) -> None:
        status_label.setText(
            message
        )

    def update_transcript(
        text: str,
    ) -> None:
        transcript_label.setText(
            f"YOU: {text}"
        )

    def update_response(
        text: str,
    ) -> None:
        response_label.setText(
            f"REYES: {text}"
        )

    def toggle_mute() -> None:
        muted = controller.toggle_muted()

        mute_button.setText(
            "MUTE: ON"
            if muted
            else "MUTE: OFF"
        )

    def toggle_continuous() -> None:
        enabled = (
            controller.toggle_continuous_mode()
        )

        continuous_button.setText(
            "CONTINUOUS: ON"
            if enabled
            else "CONTINUOUS: OFF"
        )

    controller.state_changed.connect(
        update_state
    )

    controller.status_changed.connect(
        update_status
    )

    controller.transcript_ready.connect(
        update_transcript
    )

    controller.response_ready.connect(
        update_response
    )

    controller.error_occurred.connect(
        lambda message: response_label.setText(
            f"ERROR: {message}"
        )
    )

    listen_button.clicked.connect(
        controller.start_listening
    )

    test_text_button.clicked.connect(
        lambda: controller.process_text(
            "Hello REYES, introduce yourself briefly."
        )
    )

    mute_button.clicked.connect(
        toggle_mute
    )

    continuous_button.clicked.connect(
        toggle_continuous
    )

    cancel_button.clicked.connect(
        controller.cancel_current_interaction
    )

    button_row = QHBoxLayout()

    button_row.addWidget(
        listen_button
    )

    button_row.addWidget(
        test_text_button
    )

    button_row.addWidget(
        cancel_button
    )

    option_row = QHBoxLayout()

    option_row.addWidget(
        mute_button
    )

    option_row.addWidget(
        continuous_button
    )

    layout = QVBoxLayout(window)

    layout.setContentsMargins(
        30,
        30,
        30,
        30,
    )

    layout.setSpacing(14)

    layout.addWidget(
        title_label
    )

    layout.addWidget(
        state_label
    )

    layout.addWidget(
        status_label
    )

    layout.addWidget(
        transcript_label
    )

    layout.addWidget(
        response_label
    )

    layout.addStretch(1)

    layout.addLayout(
        button_row
    )

    layout.addLayout(
        option_row
    )

    window.show()

    exit_code = app.exec()

    controller.shutdown()

    sys.exit(exit_code)