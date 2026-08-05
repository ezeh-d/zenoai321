import customtkinter as ctk
from gui.theme import TITLE_FONT, SIDEBAR_WIDTH


class Sidebar(ctk.CTkFrame):

    def __init__(self, master):
        super().__init__(master, width=SIDEBAR_WIDTH)

        self.pack_propagate(False)

        title = ctk.CTkLabel(
            self,
            text="🤖 REYES",
            font=TITLE_FONT
        )

        title.pack(pady=30)

        buttons = [
            "🏠 Home",
            "💬 Chats",
            "🧠 Memory",
            "📂 Projects",
            "⚙ Settings"
        ]

        for item in buttons:
            btn = ctk.CTkButton(
                self,
                text=item,
                height=42
            )

            btn.pack(
                padx=15,
                pady=8,
                fill="x"
            )