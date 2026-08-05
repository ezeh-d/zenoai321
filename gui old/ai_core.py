import customtkinter as ctk
import math


class AICore(ctk.CTkCanvas):

    def __init__(self, master):
        super().__init__(
            master,
            width=300,
            height=300,
            bg="#242424",
            highlightthickness=0
        )

        self.center = 150
        self.core_radius = 42

        self.pulse = 0
        self.pulse_dir = 1

        self.angle1 = 0
        self.angle2 = 0

        self.color = "#00E5FF"

        self.core = self.create_oval(0, 0, 0, 0, fill=self.color, outline="")

        self.ring1 = self.create_arc(
            70, 70, 230, 230,
            start=0, extent=220,
            style="arc", width=4, outline=self.color
        )

        self.ring2 = self.create_arc(
            50, 50, 250, 250,
            start=120, extent=180,
            style="arc", width=3, outline="#7DF9FF"
        )

        self.outer_segments = []
        for i in range(0, 360, 30):
            seg = self.create_arc(
                25, 25, 275, 275,
                start=i, extent=15,
                style="arc", width=2, outline="#00BFFF"
            )
            self.outer_segments.append(seg)

        self.dots = []
        for _ in range(6):
            dot = self.create_oval(0, 0, 0, 0, fill=self.color, outline="")
            self.dots.append(dot)

        self.animate()

    def draw_core(self):
        r = self.core_radius + self.pulse
        c = self.center

        self.coords(self.core, c-r, c-r, c+r, c+r)

    def draw_orbiting_dots(self):
        c = self.center
        radius = 125

        for i, dot in enumerate(self.dots):
            angle = math.radians(self.angle1 + i * 60)
            x = c + math.cos(angle) * radius
            y = c + math.sin(angle) * radius

            self.coords(dot, x-4, y-4, x+4, y+4)

    def animate(self):

        self.pulse += 0.4 * self.pulse_dir

        if self.pulse > 8:
            self.pulse_dir = -1
        elif self.pulse < -5:
            self.pulse_dir = 1

        self.angle1 = (self.angle1 + 2) % 360
        self.angle2 = (self.angle2 - 3) % 360

        self.itemconfig(self.ring1, start=self.angle1)
        self.itemconfig(self.ring2, start=self.angle2)

        for idx, seg in enumerate(self.outer_segments):
            self.itemconfig(seg, start=(idx * 30 + self.angle2 * 0.5))

        self.draw_core()
        self.draw_orbiting_dots()

        self.after(16, self.animate)

    def set_state(self, color):
        self.color = color

        self.itemconfig(self.core, fill=color)
        self.itemconfig(self.ring1, outline=color)

        for dot in self.dots:
            self.itemconfig(dot, fill=color)

    def idle(self):
        self.set_state("#00E5FF")

    def listening(self):
        self.set_state("#10B981")

    def thinking(self):
        self.set_state("#A855F7")

    def speaking(self):
        self.set_state("#F97316")