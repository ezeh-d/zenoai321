import customtkinter as ctk
from gui.ai_core import AICore


class ChatPanel(ctk.CTkFrame):

    def __init__(self, master):
        super().__init__(master)

        self.ai_core = AICore(self)
        self.ai_core.pack(pady=25)

        self.chat_box = ctk.CTkTextbox(self, state="disabled")
        self.chat_box.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    def add_message(self, sender, message):
        self.chat_box.configure(state="normal")
        self.chat_box.insert("end", f"{sender}: {message}\n\n")
        self.chat_box.configure(state="disabled")
        self.chat_box.see("end")

    def set_idle(self):
        self.ai_core.idle()

    def set_listening(self):
        self.ai_core.listening()

    def set_thinking(self):
        self.ai_core.thinking()

    def set_speaking(self):
        self.ai_core.speaking()