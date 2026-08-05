from __future__ import annotations

import sys
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.ai_core import AICore
from gui.hud_panel import HudPanel
from gui.theme import (
    BACKGROUND,
    BACKGROUND_ALT,
    BORDER,
    ERROR,
    FONT_FAMILY,
    GLOBAL_STYLESHEET,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    PANEL_BACKGROUND,
    PRIMARY,
    PRIMARY_SOFT,
    STATE_COLORS,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from gui.voice_controller import VoiceController, VoiceResult
from gui.wake_word_controller import WakeWordController

# =========================================================
# TRANSCRIPT PANEL
# =========================================================

class TranscriptPanel(QFrame):
    """
    Displays the latest user command and REYES response.

    This is not a chat box. It is a temporary HUD transcript.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setObjectName("TranscriptPanel")

        self.setMinimumHeight(150)
        self.setMaximumHeight(210)

        self._build_interface()
        self._apply_style()
        self._apply_shadow()

    def _build_interface(self) -> None:
        self.title_label = QLabel("LIVE INTERACTION")

        self.user_title = QLabel("USER INPUT")
        self.user_text = QLabel("Awaiting voice command...")

        self.reyes_title = QLabel("REYES RESPONSE")
        self.reyes_text = QLabel("Core systems ready.")

        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY_SOFT};
                font-family: "{FONT_FAMILY}";
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            """
        )

        for title in (
            self.user_title,
            self.reyes_title,
        ):
            title.setStyleSheet(
                f"""
                QLabel {{
                    background: transparent;
                    color: {TEXT_MUTED};
                    font-family: "{FONT_FAMILY}";
                    font-size: 9px;
                    font-weight: 700;
                    letter-spacing: 1px;
                }}
                """
            )

        self.user_text.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_PRIMARY};
                font-family: "{FONT_FAMILY}";
                font-size: 13px;
                font-weight: 500;
            }}
            """
        )

        self.reyes_text.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY_SOFT};
                font-family: "{FONT_FAMILY}";
                font-size: 13px;
                font-weight: 500;
            }}
            """
        )

        self.user_text.setWordWrap(True)
        self.reyes_text.setWordWrap(True)

        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            18,
            15,
            18,
            15,
        )

        layout.setSpacing(5)

        layout.addWidget(self.title_label)
        layout.addSpacing(3)

        layout.addWidget(self.user_title)
        layout.addWidget(self.user_text)

        layout.addSpacing(6)

        layout.addWidget(self.reyes_title)
        layout.addWidget(self.reyes_text)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#TranscriptPanel {{
                background-color: {PANEL_BACKGROUND};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            """
        )

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(self)

        shadow.setBlurRadius(25)
        shadow.setOffset(0, 5)

        shadow_color = QColor(PRIMARY)
        shadow_color.setAlpha(24)

        shadow.setColor(shadow_color)

        self.setGraphicsEffect(shadow)

    def set_user_text(
        self,
        text: str,
    ) -> None:
        cleaned = text.strip()

        self.user_text.setText(
            cleaned or "No voice input detected."
        )

    def set_reyes_text(
        self,
        text: str,
    ) -> None:
        cleaned = text.strip()

        self.reyes_text.setText(
            cleaned or "No response returned."
        )

    def set_error(
        self,
        message: str,
    ) -> None:
        self.reyes_text.setText(message)

        self.reyes_text.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {ERROR};
                font-family: "{FONT_FAMILY}";
                font-size: 13px;
                font-weight: 600;
            }}
            """
        )

    def reset_response_style(self) -> None:
        self.reyes_text.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY_SOFT};
                font-family: "{FONT_FAMILY}";
                font-size: 13px;
                font-weight: 500;
            }}
            """
        )


# =========================================================
# TOP STATUS BAR
# =========================================================

class TopStatusBar(QFrame):
    """
    Minimal REYES title and status bar.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setObjectName("TopStatusBar")
        self.setFixedHeight(78)

        self._build_interface()
        self._apply_style()

    def _build_interface(self) -> None:
        self.brand_label = QLabel("REYES")

        self.version_label = QLabel(
            "DESKTOP INTELLIGENCE SYSTEM"
        )

        self.state_label = QLabel("STANDBY")

        self.status_label = QLabel(
            "Awaiting voice activation"
        )

        self.brand_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY};
                font-family: "{FONT_FAMILY}";
                font-size: 28px;
                font-weight: 800;
                letter-spacing: 6px;
            }}
            """
        )

        self.version_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_MUTED};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
                font-weight: 600;
                letter-spacing: 2px;
            }}
            """
        )

        self.state_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
        )

        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
        )

        self.state_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY};
                font-family: "{FONT_FAMILY}";
                font-size: 15px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            """
        )

        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_SECONDARY};
                font-family: "{FONT_FAMILY}";
                font-size: 10px;
            }}
            """
        )

        left_layout = QVBoxLayout()

        left_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        left_layout.setSpacing(1)

        left_layout.addWidget(self.brand_label)
        left_layout.addWidget(self.version_label)

        right_layout = QVBoxLayout()

        right_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        right_layout.setSpacing(3)

        right_layout.addWidget(self.state_label)
        right_layout.addWidget(self.status_label)

        layout = QHBoxLayout(self)

        layout.setContentsMargins(
            22,
            10,
            22,
            10,
        )

        layout.addLayout(left_layout)
        layout.addStretch(1)
        layout.addLayout(right_layout)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#TopStatusBar {{
                background-color: {BACKGROUND_ALT};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            """
        )

    def set_state(
        self,
        state: str,
        message: str,
    ) -> None:
        normalized = state.strip().lower()

        display_names = {
            "standby": "STANDBY",
            "activated": "ONLINE",
            "listening": "LISTENING",
            "thinking": "PROCESSING",
            "speaking": "SPEAKING",
            "sleeping": "SLEEP MODE",
            "error": "SYSTEM ERROR",
            "stopped": "OFFLINE",
        }

        display_text = display_names.get(
            normalized,
            normalized.upper(),
        )

        color = STATE_COLORS.get(
            normalized,
            PRIMARY,
        )

        if normalized == "stopped":
            color = TEXT_MUTED

        self.state_label.setText(display_text)
        self.status_label.setText(message)

        self.state_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {color};
                font-family: "{FONT_FAMILY}";
                font-size: 15px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            """
        )


# =========================================================
# CONTROL BUTTON
# =========================================================

class CoreButton(QPushButton):
    """
    Futuristic action button used under the AI core.
    """

    def __init__(
        self,
        text: str,
        accent: str = PRIMARY,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)

        self.accent = accent

        self.setMinimumHeight(42)

        self.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: #06151D;
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 10px;
                padding: 9px 16px;
                font-family: "{FONT_FAMILY}";
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }}

            QPushButton:hover {{
                background-color: #0A202B;
                color: {self.accent};
                border-color: {self.accent};
            }}

            QPushButton:pressed {{
                background-color: #031016;
                padding-top: 11px;
            }}

            QPushButton:disabled {{
                background-color: #050B0F;
                color: {TEXT_MUTED};
                border-color: #10232B;
            }}
            """
        )


# =========================================================
# MAIN REYES WINDOW
# =========================================================

class ReyesMainWindow(QMainWindow):
    """
    Main PySide6 interface for REYES.

    The window connects:

        AICore
        HudPanel
        VoiceController
        Existing voice.py
        Existing brain.py
        Existing speech.py
    """

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("REYES AI")

        self.resize(
            WINDOW_WIDTH,
            WINDOW_HEIGHT,
        )

        self.setMinimumSize(
            MIN_WINDOW_WIDTH,
            MIN_WINDOW_HEIGHT,
        )

        self._closing = False
        self._last_status_message = (
            "Awaiting voice activation"
        )

        self.voice_controller = VoiceController(
            parent=self
        )
        self.wake_word_controller = WakeWordController(
            parent=self
        )

        self._build_interface()
        self._connect_signals()
        self._create_shortcuts()
        self._apply_window_style()

        self._startup_sequence()

    # =====================================================
    # WAKE-WORD CONTROL
    # =====================================================

    def _start_wake_word_detection(self) -> None:
        """
        Start the background wake-word listener.
        """

        started = self.wake_word_controller.start()

        if started:
            self.top_bar.set_state(
                "standby",
                'Wake word active — say "Hey REYES"',
            )

            self.hud_panel.set_ai_state(
                "standby",
                'Waiting for "Hey REYES"',
            )

            self.core_hint_label.setText(
                'SAY "HEY REYES" OR PRESS SPACE'
            )

    def _toggle_wake_word(self) -> None:
        enabled = (
            self.wake_word_controller.toggle_enabled()
        )

        self.wake_word_button.setText(
            "WAKE WORD: ON"
            if enabled
            else "WAKE WORD: OFF"
        )

        if enabled:
            self.core_hint_label.setText(
                'SAY "HEY REYES" OR PRESS SPACE'
            )
        else:
            self.core_hint_label.setText(
                "PRESS SPACE OR CLICK ACTIVATE VOICE"
            )

    def _handle_wake_word(
        self,
        recognized_text: str,
        attached_command: str,
    ) -> None:
        """
        Activate REYES after the wake phrase is detected.

        Examples:
            "Hey REYES" -> begin normal listening
            "REYES open Chrome" -> process open Chrome immediately
        """

        if self._closing:
            return

        if self.voice_controller.is_active:
            return

        self.ai_core.set_state(
            "activated"
        )

        self.top_bar.set_state(
            "activated",
            f"Wake phrase detected: {recognized_text}",
        )

        self.hud_panel.set_ai_state(
            "activated",
            "Wake phrase detected",
        )

        self.transcript_panel.reset_response_style()

        if attached_command:
            self.transcript_panel.set_user_text(
                attached_command
            )

            self.transcript_panel.set_reyes_text(
                "Processing wake-word command..."
            )

            started = self.voice_controller.process_text(
                attached_command
            )

            if not started:
                self.wake_word_controller.resume()

            return

        self.transcript_panel.set_user_text(
            recognized_text
        )

        self.transcript_panel.set_reyes_text(
            "REYES activated. Speak your command."
        )

        QTimer.singleShot(
            350,
            self.voice_controller.start_listening,
        )

    def _handle_wake_status(
        self,
        message: str,
    ) -> None:
        if (
            not self.voice_controller.is_active
            and self.voice_controller.state != "sleeping"
        ):
            self._last_status_message = message

            self.top_bar.set_state(
                "standby",
                message,
            )

    def _handle_wake_error(
        self,
        message: str,
    ) -> None:
        print(
            f"[REYES Wake Word] {message}"
        )

        self.transcript_panel.set_error(
            message
        )

    # =====================================================
    # INTERFACE
    # =====================================================

    def _build_interface(self) -> None:
        central_widget = QWidget()

        central_widget.setObjectName(
            "CentralWidget"
        )

        self.setCentralWidget(
            central_widget
        )

        self.top_bar = TopStatusBar()

        self.ai_core = AICore()

        self.transcript_panel = TranscriptPanel()

        self.hud_panel = HudPanel(
            auto_start_monitor=True
        )

        self.listen_button = CoreButton(
            "ACTIVATE VOICE",
            accent=SUCCESS,
        )

        self.mute_button = CoreButton(
            "VOICE OUTPUT: ON",
            accent=WARNING,
        )

        self.continuous_button = CoreButton(
            "CONTINUOUS MODE: OFF",
            accent=PRIMARY_SOFT,
        )
        self.wake_word_button = CoreButton(
            "WAKE WORD: ON",
            accent=SUCCESS,
        )

        self.sleep_button = CoreButton(
            "SLEEP",
            accent=TEXT_SECONDARY,
        )

        self.cancel_button = CoreButton(
            "CANCEL",
            accent=ERROR,
        )

        self.cancel_button.setEnabled(False)

        self.core_container = QFrame()

        self.core_container.setObjectName(
            "CoreContainer"
        )

        self.core_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        core_layout = QVBoxLayout(
            self.core_container
        )

        core_layout.setContentsMargins(
            20,
            10,
            20,
            10,
        )

        core_layout.setSpacing(6)

        core_layout.addStretch(1)

        core_layout.addWidget(
            self.ai_core,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        self.core_hint_label = QLabel(
            "PRESS SPACE OR CLICK ACTIVATE VOICE"
        )

        self.core_hint_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.core_hint_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_MUTED};
                font-family: "{FONT_FAMILY}";
                font-size: 9px;
                font-weight: 600;
                letter-spacing: 2px;
            }}
            """
        )

        core_layout.addWidget(
            self.core_hint_label
        )

        controls_row_one = QHBoxLayout()
        controls_row_one.setSpacing(10)

        controls_row_one.addWidget(self.listen_button)
        controls_row_one.addWidget(self.mute_button)
        controls_row_one.addWidget(self.continuous_button)

        controls_row_two = QHBoxLayout()
        controls_row_two.setSpacing(10)

        controls_row_two.addWidget(self.wake_word_button)
        controls_row_two.addWidget(self.sleep_button)
        controls_row_two.addWidget(self.cancel_button)

        controls_layout = QVBoxLayout()

        controls_layout.setContentsMargins(
            10,
            8,
            10,
            0,
        )

        controls_layout.setSpacing(10)

        controls_layout.addLayout(controls_row_one)
        controls_layout.addLayout(controls_row_two)

        center_layout = QVBoxLayout()

        center_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        center_layout.setSpacing(14)

        center_layout.addWidget(
            self.core_container,
            stretch=1,
        )

        center_layout.addLayout(
            controls_layout
        )

        center_layout.addWidget(
            self.transcript_panel
        )

        content_layout = QHBoxLayout()

        content_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        content_layout.setSpacing(18)

        content_layout.addLayout(
            center_layout,
            stretch=1,
        )

        content_layout.addWidget(
            self.hud_panel
        )

        root_layout = QVBoxLayout(
            central_widget
        )

        root_layout.setContentsMargins(
            22,
            20,
            22,
            20,
        )

        root_layout.setSpacing(16)

        root_layout.addWidget(
            self.top_bar
        )

        root_layout.addLayout(
            content_layout,
            stretch=1,
        )

    def _apply_window_style(self) -> None:
        self.setStyleSheet(
            GLOBAL_STYLESHEET
            + f"""
            QWidget#CentralWidget {{
                background-color: {BACKGROUND};
            }}

            QFrame#CoreContainer {{
                background-color: transparent;
                border: none;
            }}
            """
        )

    # =====================================================
    # SIGNAL CONNECTIONS
    # =====================================================

    def _connect_signals(self) -> None:
        self.listen_button.clicked.connect(
            self._activate_voice
        )

        self.mute_button.clicked.connect(
            self._toggle_mute
        )

        self.continuous_button.clicked.connect(
            self._toggle_continuous_mode
        )

        self.sleep_button.clicked.connect(
            self._toggle_sleep_mode
        )

        self.cancel_button.clicked.connect(
            self.voice_controller.cancel_current_interaction
        )

        self.voice_controller.state_changed.connect(
            self._handle_state_change
        )

        self.voice_controller.status_changed.connect(
            self._handle_status_change
        )

        self.voice_controller.transcript_ready.connect(
            self._handle_transcript
        )

        self.voice_controller.response_ready.connect(
            self._handle_response
        )

        self.voice_controller.interaction_finished.connect(
            self._handle_interaction_finished
        )

        self.voice_controller.error_occurred.connect(
            self._handle_error
        )

        self.voice_controller.active_changed.connect(
            self._handle_active_changed
        )

        self.voice_controller.muted_changed.connect(
            self._handle_muted_changed
        )

        self.voice_controller.continuous_mode_changed.connect(
            self._handle_continuous_changed
        )

        self.voice_controller.backend_status_changed.connect(
            self._handle_backend_status
        )

        self.hud_panel.monitor_error.connect(
            self._handle_monitor_error
        )
        self.wake_word_button.clicked.connect(
            self._toggle_wake_word
        )

        self.wake_word_controller.wake_detected.connect(
            self._handle_wake_word
        )

        self.wake_word_controller.status_changed.connect(
            self._handle_wake_status
        )

        self.wake_word_controller.error_occurred.connect(
            self._handle_wake_error
        )

    # =====================================================
    # SHORTCUTS
    # =====================================================

    def _create_shortcuts(self) -> None:
        activate_action = QAction(
            self
        )

        activate_action.setShortcut(
            QKeySequence(
                Qt.Key.Key_Space
            )
        )

        activate_action.triggered.connect(
            self._activate_voice
        )

        self.addAction(
            activate_action
        )

        cancel_action = QAction(
            self
        )

        cancel_action.setShortcut(
            QKeySequence(
                Qt.Key.Key_Escape
            )
        )

        cancel_action.triggered.connect(
            self.voice_controller.cancel_current_interaction
        )

        self.addAction(
            cancel_action
        )

        fullscreen_action = QAction(
            self
        )

        fullscreen_action.setShortcut(
            QKeySequence("F11")
        )

        fullscreen_action.triggered.connect(
            self._toggle_fullscreen
        )

        self.addAction(
            fullscreen_action
        )

        mute_action = QAction(
            self
        )

        mute_action.setShortcut(
            QKeySequence("Ctrl+M")
        )

        mute_action.triggered.connect(
            self._toggle_mute
        )

        self.addAction(
            mute_action
        )

    # =====================================================
    # STARTUP
    # =====================================================

    def _startup_sequence(self) -> None:
        self.ai_core.set_state(
            "sleeping"
        )

        self.top_bar.set_state(
            "sleeping",
            "Initializing REYES systems",
        )

        self.hud_panel.set_ai_state(
            "sleeping",
            "Initializing interface",
        )

        QTimer.singleShot(
            450,
            lambda: self.ai_core.set_state(
                "activated"
            ),
        )

        QTimer.singleShot(
            450,
            lambda: self.top_bar.set_state(
                "activated",
                "REYES core online",
            ),
        )

        QTimer.singleShot(
            450,
            lambda: self.hud_panel.set_ai_state(
                "activated",
                "REYES core online",
            ),
        )

        QTimer.singleShot(
            1500,
            self._enter_standby,
        )

        QTimer.singleShot(
            1900,
            self._start_wake_word_detection,
        )

    def _enter_standby(self) -> None:
        if self.voice_controller.is_active:
            return

        self.ai_core.set_state(
            "standby"
        )

        self.top_bar.set_state(
            "standby",
            "Awaiting voice activation",
        )

        self.hud_panel.set_ai_state(
            "standby",
            "Awaiting voice activation",
        )

    # =====================================================
    # VOICE ACTIONS
    # =====================================================

    def _activate_voice(self) -> None:
        if self.voice_controller.state == "sleeping":
            self.voice_controller.wake()

            QTimer.singleShot(
                700,
                self.voice_controller.start_listening,
            )

            return

        started = (
            self.voice_controller.start_listening()
        )

        if not started:
            return

        self.transcript_panel.reset_response_style()

        self.transcript_panel.set_user_text(
            "Listening..."
        )

        self.transcript_panel.set_reyes_text(
            "Processing pipeline ready."
        )

    def _toggle_mute(self) -> None:
        self.voice_controller.toggle_muted()

    def _toggle_continuous_mode(self) -> None:
        self.voice_controller.toggle_continuous_mode()

    def _toggle_sleep_mode(self) -> None:
        if self.voice_controller.state == "sleeping":
            self.voice_controller.wake()

            self.wake_word_controller.resume()

            self.sleep_button.setText(
                "SLEEP"
            )

            self.core_hint_label.setText(
                'SAY "HEY REYES" OR PRESS SPACE'
            )

        else:
            self.wake_word_controller.pause()
            self.voice_controller.sleep()

            self.sleep_button.setText(
                "WAKE"
            )

    # =====================================================
    # STATE HANDLING
    # =====================================================

    def _handle_state_change(
        self,
        state: str,
    ) -> None:
        message = self._last_status_message

        visual_state = (
            state
            if state != "stopped"
            else "sleeping"
        )

        self.ai_core.set_state(
            visual_state
        )

        self.hud_panel.set_ai_state(
            visual_state,
            message,
        )

        self.top_bar.set_state(
            state,
            message,
        )

        state_messages = {
            "standby": 'SAY "HEY REYES" OR PRESS SPACE',
            "activated": "REYES CORE ONLINE",
            "listening": "VOICE INPUT ACTIVE",
            "thinking": "PROCESSING REQUEST",
            "speaking": "VOICE OUTPUT ACTIVE",
            "sleeping": "REYES IS IN SLEEP MODE",
            "error": "SYSTEM REQUIRES ATTENTION",
            "stopped": "REYES OFFLINE",
        }

        self.core_hint_label.setText(
            state_messages.get(
                state,
                state.upper(),
            )
        )

        self.sleep_button.setText(
            "WAKE"
            if state == "sleeping"
            else "SLEEP"
        )

        if state in {
            "listening",
            "thinking",
            "speaking",
            "sleeping",
            "stopped",
        }:
            self.wake_word_controller.pause()

        elif (
            state == "standby"
            and not self.voice_controller.is_active
        ):
            QTimer.singleShot(
                400,
                self.wake_word_controller.resume,
            )

    def _handle_status_change(
        self,
        message: str,
    ) -> None:
        self._last_status_message = message

        self.top_bar.set_state(
            self.voice_controller.state,
            message,
        )

        hud_state = self.voice_controller.state

        if hud_state == "stopped":
            hud_state = "sleeping"

        self.hud_panel.set_ai_state(
            hud_state,
            message,
        )

    def _handle_active_changed(
        self,
        active: bool,
    ) -> None:
        if active:
            self.wake_word_controller.pause()

        elif self.voice_controller.state != "sleeping":
            QTimer.singleShot(
                400,
                self.wake_word_controller.resume,
            )

        self.listen_button.setEnabled(
            not active
        )

        self.cancel_button.setEnabled(
            active
        )

        self.sleep_button.setEnabled(
            not active
        )

        self.listen_button.setText(
            "VOICE ACTIVE"
            if active
            else "ACTIVATE VOICE"
        )

    # =====================================================
    # TRANSCRIPT AND RESPONSE
    # =====================================================

    def _handle_transcript(
        self,
        text: str,
    ) -> None:
        self.transcript_panel.set_user_text(
            text
        )

    def _handle_response(
        self,
        text: str,
    ) -> None:
        self.transcript_panel.reset_response_style()

        self.transcript_panel.set_reyes_text(
            text
        )

    def _handle_interaction_finished(
        self,
        result: VoiceResult,
    ) -> None:
        if result.success:
            return

        if result.error:
            self.transcript_panel.set_error(
                result.error
            )

    # =====================================================
    # BUTTON STATE
    # =====================================================

    def _handle_muted_changed(
        self,
        muted: bool,
    ) -> None:
        self.mute_button.setText(
            "VOICE OUTPUT: OFF"
            if muted
            else "VOICE OUTPUT: ON"
        )

    def _handle_continuous_changed(
        self,
        enabled: bool,
    ) -> None:
        self.continuous_button.setText(
            "CONTINUOUS MODE: ON"
            if enabled
            else "CONTINUOUS MODE: OFF"
        )

    # =====================================================
    # BACKEND STATUS
    # =====================================================

    def _handle_backend_status(
        self,
        ready: bool,
        message: str,
    ) -> None:
        if ready:
            self.top_bar.set_state(
                "activated",
                message,
            )

            return

        self.top_bar.set_state(
            "error",
            message,
        )

        self.hud_panel.set_ai_state(
            "error",
            message,
        )

        self.transcript_panel.set_error(
            message
        )

    # =====================================================
    # ERRORS
    # =====================================================

    def _handle_error(
        self,
        message: str,
    ) -> None:
        self.transcript_panel.set_error(
            message
        )

        self.ai_core.set_state(
            "error"
        )

        self.top_bar.set_state(
            "error",
            message,
        )

        self.hud_panel.set_ai_state(
            "error",
            message,
        )

    def _handle_monitor_error(
        self,
        message: str,
    ) -> None:
        print(message)

    # =====================================================
    # WINDOW CONTROL
    # =====================================================

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F1:
            self._show_help()
            return

        super().keyPressEvent(event)

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "REYES Controls",
            (
                "SPACE  - Activate voice\n"
                "ESC    - Cancel current interaction\n"
                "CTRL+M - Toggle voice output\n"
                "F11    - Toggle fullscreen\n"
                "F1     - Show controls"
            ),
        )

    # =====================================================
    # CLEANUP
    # =====================================================

    def closeEvent(
        self,
        event: QCloseEvent,
    ) -> None:
        if self._closing:
            event.accept()
            return

        self._closing = True

        self.top_bar.set_state(
            "stopped",
            "Shutting down REYES",
        )

        self.ai_core.set_state(
            "sleeping"
        )

        self.hud_panel.stop_monitoring()

        self.wake_word_controller.shutdown(
            wait_timeout_seconds=1.0
        )

        self.voice_controller.shutdown(
            wait_timeout_seconds=1.0
        )

        event.accept()


# =========================================================
# APPLICATION ENTRY POINT
# =========================================================

def create_application() -> QApplication:
    """
    Create or return the active QApplication.
    """

    existing_app = QApplication.instance()

    if existing_app is not None:
        return existing_app

    app = QApplication(sys.argv)

    app.setApplicationName(
        "REYES AI"
    )

    app.setOrganizationName(
        "REYES"
    )

    app.setStyleSheet(
        GLOBAL_STYLESHEET
    )

    return app


def run() -> int:
    """
    Launch the REYES interface.
    """

    app = create_application()

    window = ReyesMainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(run())