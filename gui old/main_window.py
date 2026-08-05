# gui old/main_window.py

from __future__ import annotations

import threading
import time
from datetime import datetime

import customtkinter as ctk

from brain import think
from speech import speak
from voice import listen

from gui.ai_core import AICore
from gui.clap_detector import detect_double_clap


# =========================================================
# CUSTOMTKINTER CONFIGURATION
# =========================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# =========================================================
# REYES GUI
# =========================================================

class ReyesGUI(ctk.CTk):
    """
    Voice-first futuristic REYES desktop interface.

    States:
        standby
        activated
        listening
        thinking
        speaking
        sleeping
        error
    """

    def __init__(self) -> None:
        super().__init__()

        # -------------------------------------------------
        # WINDOW CONFIGURATION
        # -------------------------------------------------

        self.title("REYES AI")
        self.geometry("1280x760")
        self.minsize(1000, 650)

        self.configure(fg_color="#05080D")

        self.protocol(
            "WM_DELETE_WINDOW",
            self.close_reyes,
        )

        # -------------------------------------------------
        # RUNTIME STATE
        # -------------------------------------------------

        self.running = True
        self.voice_session_active = False
        self.clap_listener_active = False
        self.processing_command = False

        self.current_state = "standby"

        # -------------------------------------------------
        # MAIN LAYOUT
        # -------------------------------------------------

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.main_container = ctk.CTkFrame(
            self,
            fg_color="#05080D",
            corner_radius=0,
        )

        self.main_container.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(1, weight=0)
        self.main_container.grid_rowconfigure(2, weight=0)

        # -------------------------------------------------
        # TOP HUD
        # -------------------------------------------------

        self.top_hud = ctk.CTkFrame(
            self.main_container,
            fg_color="transparent",
            height=70,
        )

        self.top_hud.place(
            relx=0.0,
            rely=0.0,
            relwidth=1.0,
        )

        self.brand_label = ctk.CTkLabel(
            self.top_hud,
            text="R E Y E S",
            font=ctk.CTkFont(
                family="Segoe UI",
                size=22,
                weight="bold",
            ),
            text_color="#00E5FF",
        )

        self.brand_label.pack(
            side="left",
            padx=30,
            pady=22,
        )

        self.clock_label = ctk.CTkLabel(
            self.top_hud,
            text="",
            font=ctk.CTkFont(
                family="Consolas",
                size=16,
            ),
            text_color="#8EDFFF",
        )

        self.clock_label.pack(
            side="right",
            padx=30,
            pady=22,
        )

        # -------------------------------------------------
        # CENTRAL CORE AREA
        # -------------------------------------------------

        self.core_container = ctk.CTkFrame(
            self.main_container,
            fg_color="transparent",
        )

        self.core_container.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        self.core_container.grid_columnconfigure(0, weight=1)
        self.core_container.grid_rowconfigure(0, weight=1)

        self.ai_core = AICore(
            self.core_container,
        )

        self.ai_core.grid(
            row=0,
            column=0,
        )

        # -------------------------------------------------
        # STATUS AREA
        # -------------------------------------------------

        self.status_frame = ctk.CTkFrame(
            self.main_container,
            fg_color="transparent",
        )

        self.status_frame.grid(
            row=1,
            column=0,
            pady=(0, 8),
        )

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="STANDBY",
            font=ctk.CTkFont(
                family="Segoe UI",
                size=24,
                weight="bold",
            ),
            text_color="#00E5FF",
        )

        self.status_label.pack()

        self.sub_status_label = ctk.CTkLabel(
            self.status_frame,
            text="Waiting for double clap",
            font=ctk.CTkFont(
                family="Segoe UI",
                size=14,
            ),
            text_color="#6D8794",
        )

        self.sub_status_label.pack(
            pady=(5, 0),
        )

        # -------------------------------------------------
        # TRANSCRIPT AREA
        # -------------------------------------------------

        self.transcript_frame = ctk.CTkFrame(
            self.main_container,
            fg_color="#080D14",
            corner_radius=18,
            border_width=1,
            border_color="#14303B",
            width=820,
            height=120,
        )

        self.transcript_frame.grid(
            row=2,
            column=0,
            padx=80,
            pady=(8, 30),
            sticky="ew",
        )

        self.transcript_frame.grid_propagate(False)
        self.transcript_frame.grid_columnconfigure(0, weight=1)
        self.transcript_frame.grid_rowconfigure(0, weight=1)

        self.transcript_label = ctk.CTkLabel(
            self.transcript_frame,
            text=(
                "REYES is online.\n"
                "Double clap to activate."
            ),
            font=ctk.CTkFont(
                family="Segoe UI",
                size=16,
            ),
            text_color="#B8DDE8",
            justify="center",
            wraplength=760,
        )

        self.transcript_label.grid(
            row=0,
            column=0,
            padx=30,
            pady=20,
            sticky="nsew",
        )

        # -------------------------------------------------
        # WINDOW SHORTCUTS
        # -------------------------------------------------

        self.bind(
            "<Escape>",
            lambda event: self.sleep_reyes(),
        )

        self.bind(
            "<F11>",
            lambda event: self.toggle_fullscreen(),
        )

        self.bind(
            "<Control-q>",
            lambda event: self.close_reyes(),
        )

        # -------------------------------------------------
        # STARTUP TASKS
        # -------------------------------------------------

        self.update_clock()

        self.after(
            800,
            self.start_clap_listener,
        )

    # =====================================================
    # UI HELPERS
    # =====================================================

    def update_clock(self) -> None:
        """
        Update the clock shown in the top-right corner.
        """

        if not self.running:
            return

        now = datetime.now()

        self.clock_label.configure(
            text=now.strftime("%H:%M:%S  |  %d %b %Y")
        )

        self.after(
            1000,
            self.update_clock,
        )

    def set_transcript(self, text: str) -> None:
        """
        Update the visible transcript safely.
        """

        self.transcript_label.configure(
            text=text
        )

    def set_status(
        self,
        state: str,
        primary: str,
        secondary: str,
        color: str,
    ) -> None:
        """
        Update REYES visual state.
        """

        self.current_state = state

        self.status_label.configure(
            text=primary,
            text_color=color,
        )

        self.sub_status_label.configure(
            text=secondary,
        )

        if state in {
            "standby",
            "activated",
        }:
            self.ai_core.idle()

        elif state == "listening":
            self.ai_core.listening()

        elif state == "thinking":
            self.ai_core.thinking()

        elif state == "speaking":
            self.ai_core.speaking()

        elif state == "sleeping":
            self.ai_core.idle()

        elif state == "error":
            self.ai_core.set_state("#EF4444")

    # =====================================================
    # REYES STATES
    # =====================================================

    def show_standby(self) -> None:
        self.set_status(
            state="standby",
            primary="STANDBY",
            secondary="Waiting for double clap",
            color="#00E5FF",
        )

    def show_activated(self) -> None:
        self.set_status(
            state="activated",
            primary="REYES ACTIVE",
            secondary="Voice session started",
            color="#00E5FF",
        )

    def show_listening(self) -> None:
        self.set_status(
            state="listening",
            primary="LISTENING",
            secondary="Speak now",
            color="#10B981",
        )

    def show_thinking(self) -> None:
        self.set_status(
            state="thinking",
            primary="THINKING",
            secondary="Processing your request",
            color="#A855F7",
        )

    def show_speaking(self) -> None:
        self.set_status(
            state="speaking",
            primary="SPEAKING",
            secondary="REYES is responding",
            color="#F97316",
        )

    def show_sleeping(self) -> None:
        self.set_status(
            state="sleeping",
            primary="SLEEPING",
            secondary="Double clap to activate",
            color="#64748B",
        )

    def show_error(self, message: str) -> None:
        self.set_status(
            state="error",
            primary="SYSTEM ERROR",
            secondary=message,
            color="#EF4444",
        )

    # =====================================================
    # CLAP ACTIVATION
    # =====================================================

    def start_clap_listener(self) -> None:
        """
        Start the background double-clap detector.
        """

        if self.clap_listener_active:
            return

        self.clap_listener_active = True

        thread = threading.Thread(
            target=self.clap_listener_loop,
            daemon=True,
        )

        thread.start()

    def clap_listener_loop(self) -> None:
        """
        Wait for a double clap and activate REYES.
        """

        while self.running:

            if self.voice_session_active:
                time.sleep(0.2)
                continue

            self.after(
                0,
                self.show_standby,
            )

            self.after(
                0,
                lambda: self.set_transcript(
                    "REYES is in standby.\n"
                    "Double clap to activate."
                ),
            )

            try:
                detect_double_clap()

            except Exception as error:
                self.after(
                    0,
                    lambda err=str(error): self.show_error(err),
                )

                time.sleep(2)
                continue

            if not self.running:
                return

            self.voice_session_active = True

            self.after(
                0,
                self.show_activated,
            )

            self.after(
                0,
                lambda: self.set_transcript(
                    "REYES activated."
                ),
            )

            self.voice_session_loop()

    # =====================================================
    # VOICE SESSION
    # =====================================================

    def voice_session_loop(self) -> None:
        """
        Keep REYES awake until the user gives a sleep command.
        """

        while self.running and self.voice_session_active:

            if self.processing_command:
                time.sleep(0.1)
                continue

            self.after(
                0,
                self.show_listening,
            )

            self.after(
                0,
                lambda: self.set_transcript(
                    "Listening..."
                ),
            )

            try:
                message = listen()

            except Exception as error:
                self.after(
                    0,
                    lambda err=str(error): self.show_error(err),
                )

                time.sleep(1)
                continue

            if not message:
                continue

            clean_message = str(message).strip()

            if not clean_message:
                continue

            command = clean_message.lower()

            self.after(
                0,
                lambda text=clean_message: self.set_transcript(
                    f"You said:\n{text}"
                ),
            )

            if command in {
                "sleep",
                "go to sleep",
                "stand by",
                "standby",
                "lock",
                "deactivate",
                "reyes sleep",
            }:
                self.sleep_reyes()
                return

            if command in {
                "shutdown",
                "shutdown reyes",
                "close reyes",
                "exit reyes",
                "quit reyes",
            }:
                self.after(
                    0,
                    self.close_reyes,
                )
                return

            self.process_voice_command(
                clean_message
            )

    # =====================================================
    # COMMAND PROCESSING
    # =====================================================

    def process_voice_command(
        self,
        message: str,
    ) -> None:
        """
        Send a voice command through brain.think().
        """

        self.processing_command = True

        self.after(
            0,
            self.show_thinking,
        )

        try:
            reply = think(message)

            if reply is None:
                reply = "I could not generate a response."

            reply_text = str(reply).strip()

            if not reply_text:
                reply_text = "I could not generate a response."

            self.after(
                0,
                lambda text=reply_text: self.set_transcript(
                    f"REYES:\n{text}"
                ),
            )

            self.after(
                0,
                self.show_speaking,
            )

            speak(reply_text)

        except Exception as error:
            error_message = str(error)

            self.after(
                0,
                lambda err=error_message: self.show_error(err),
            )

            self.after(
                0,
                lambda err=error_message: self.set_transcript(
                    f"Error:\n{err}"
                ),
            )

        finally:
            self.processing_command = False

            if self.running and self.voice_session_active:
                self.after(
                    0,
                    self.show_activated,
                )

    # =====================================================
    # SLEEP AND SHUTDOWN
    # =====================================================

    def sleep_reyes(self) -> None:
        """
        Put REYES back into standby mode.
        """

        if not self.voice_session_active:
            self.show_standby()
            return

        self.voice_session_active = False
        self.processing_command = False

        self.after(
            0,
            self.show_sleeping,
        )

        self.after(
            0,
            lambda: self.set_transcript(
                "REYES is returning to standby."
            ),
        )

        try:
            speak("Going to standby.")

        except Exception:
            pass

        self.after(
            1200,
            self.show_standby,
        )

    def close_reyes(self) -> None:
        """
        Close the GUI safely.
        """

        if not self.running:
            return

        self.running = False
        self.voice_session_active = False
        self.processing_command = False

        try:
            speak("REYES shutting down.")

        except Exception:
            pass

        self.after(
            100,
            self.destroy,
        )

    # =====================================================
    # WINDOW MODES
    # =====================================================

    def toggle_fullscreen(self) -> None:
        """
        Toggle fullscreen mode with F11.
        """

        current = bool(
            self.attributes("-fullscreen")
        )

        self.attributes(
            "-fullscreen",
            not current,
        )


# =========================================================
# APPLICATION ENTRY POINT
# =========================================================

def main() -> None:
    app = ReyesGUI()
    app.mainloop()


if __name__ == "__main__":
    main()