# gui/ai_core.py

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from gui.theme import (
    ANIMATION_INTERVAL_MS,
    BACKGROUND,
    CORE_GLOW_LAYERS,
    CORE_INNER_RADIUS,
    CORE_MIDDLE_RADIUS,
    CORE_OUTER_RADIUS,
    CORE_PARTICLE_COUNT,
    CORE_PULSE_SPEED,
    CORE_ROTATION_SPEED_FAST,
    CORE_ROTATION_SPEED_MEDIUM,
    CORE_ROTATION_SPEED_SLOW,
    CORE_SIZE,
    FONT_FAMILY,
    GLOBAL_STYLESHEET,
    PRIMARY,
    STATE_COLORS,
    TEXT_MUTED,
    TEXT_PRIMARY,
)


# =========================================================
# PARTICLE MODEL
# =========================================================

@dataclass
class CoreParticle:
    angle: float
    radius: float
    speed: float
    size: float
    alpha: int
    direction: int


# =========================================================
# AI CORE WIDGET
# =========================================================

class AICore(QWidget):
    """
    Animated futuristic REYES AI core.

    Supported states:

        standby
        activated
        listening
        thinking
        speaking
        sleeping
        error

    Public methods:

        set_state(state)
        idle()
        standby()
        activated()
        listening()
        thinking()
        speaking()
        sleeping()
        error()
    """

    VALID_STATES = {
        "standby",
        "activated",
        "listening",
        "thinking",
        "speaking",
        "sleeping",
        "error",
    }

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setMinimumSize(
            CORE_SIZE,
            CORE_SIZE,
        )

        self.setMaximumSize(
            CORE_SIZE + 100,
            CORE_SIZE + 100,
        )

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

        self._state = "standby"

        self._current_color = QColor(
            STATE_COLORS["standby"]
        )

        self._target_color = QColor(
            STATE_COLORS["standby"]
        )

        self._rotation_slow = 0.0
        self._rotation_medium = 0.0
        self._rotation_fast = 0.0

        self._pulse_phase = 0.0
        self._radar_angle = 0.0
        self._wave_phase = 0.0
        self._transition_progress = 1.0

        self._activity_level = 0.35
        self._target_activity = 0.35

        self._particles = self._create_particles()

        self._animation_timer = QTimer(self)

        self._animation_timer.timeout.connect(
            self._animate
        )

        self._animation_timer.start(
            ANIMATION_INTERVAL_MS
        )

    # =====================================================
    # STATE CONTROL
    # =====================================================

    @property
    def state(self) -> str:
        return self._state

    def set_state(
        self,
        state: str,
    ) -> None:
        normalized = state.strip().lower()

        if normalized == "idle":
            normalized = "standby"

        if normalized not in self.VALID_STATES:
            normalized = "standby"

        self._state = normalized

        self._target_color = QColor(
            STATE_COLORS.get(
                normalized,
                PRIMARY,
            )
        )

        activity_map = {
            "standby": 0.30,
            "activated": 0.65,
            "listening": 0.80,
            "thinking": 1.00,
            "speaking": 0.88,
            "sleeping": 0.10,
            "error": 1.00,
        }

        self._target_activity = activity_map[
            normalized
        ]

        self._transition_progress = 0.0

        self.update()

    def idle(self) -> None:
        self.set_state("standby")

    def standby(self) -> None:
        self.set_state("standby")

    def activated(self) -> None:
        self.set_state("activated")

    def listening(self) -> None:
        self.set_state("listening")

    def thinking(self) -> None:
        self.set_state("thinking")

    def speaking(self) -> None:
        self.set_state("speaking")

    def sleeping(self) -> None:
        self.set_state("sleeping")

    def error(self) -> None:
        self.set_state("error")

    # =====================================================
    # PARTICLES
    # =====================================================

    def _create_particles(
        self,
    ) -> list[CoreParticle]:
        particles: list[CoreParticle] = []

        for index in range(
            CORE_PARTICLE_COUNT
        ):
            direction = (
                1
                if index % 2 == 0
                else -1
            )

            particle = CoreParticle(
                angle=random.uniform(
                    0.0,
                    360.0,
                ),
                radius=random.uniform(
                    CORE_MIDDLE_RADIUS + 20,
                    CORE_OUTER_RADIUS + 38,
                ),
                speed=random.uniform(
                    0.15,
                    0.75,
                ),
                size=random.uniform(
                    1.2,
                    3.2,
                ),
                alpha=random.randint(
                    70,
                    220,
                ),
                direction=direction,
            )

            particles.append(
                particle
            )

        return particles

    # =====================================================
    # ANIMATION
    # =====================================================

    def _animate(self) -> None:
        speed_multiplier = (
            0.3
            + self._activity_level
        )

        self._rotation_slow += (
            CORE_ROTATION_SPEED_SLOW
            * speed_multiplier
        )

        self._rotation_medium -= (
            CORE_ROTATION_SPEED_MEDIUM
            * speed_multiplier
        )

        self._rotation_fast += (
            CORE_ROTATION_SPEED_FAST
            * speed_multiplier
        )

        self._radar_angle += (
            1.0
            + self._activity_level * 3.0
        )

        self._pulse_phase += (
            CORE_PULSE_SPEED
            * (
                0.5
                + self._activity_level
            )
        )

        self._wave_phase += (
            0.06
            + self._activity_level * 0.04
        )

        self._rotation_slow %= 360.0
        self._rotation_medium %= 360.0
        self._rotation_fast %= 360.0
        self._radar_angle %= 360.0

        self._activity_level += (
            self._target_activity
            - self._activity_level
        ) * 0.08

        if self._transition_progress < 1.0:
            self._transition_progress = min(
                1.0,
                self._transition_progress + 0.05,
            )

            self._current_color = self._blend_colors(
                self._current_color,
                self._target_color,
                0.08,
            )

        for particle in self._particles:
            particle.angle += (
                particle.speed
                * particle.direction
                * speed_multiplier
            )

            particle.angle %= 360.0

        self.update()

    @staticmethod
    def _blend_colors(
        first: QColor,
        second: QColor,
        amount: float,
    ) -> QColor:
        amount = max(
            0.0,
            min(1.0, amount),
        )

        red = int(
            first.red()
            + (
                second.red()
                - first.red()
            ) * amount
        )

        green = int(
            first.green()
            + (
                second.green()
                - first.green()
            ) * amount
        )

        blue = int(
            first.blue()
            + (
                second.blue()
                - first.blue()
            ) * amount
        )

        alpha = int(
            first.alpha()
            + (
                second.alpha()
                - first.alpha()
            ) * amount
        )

        return QColor(
            red,
            green,
            blue,
            alpha,
        )

    # =====================================================
    # PAINTING
    # =====================================================

    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )

        center = QPointF(
            self.width() / 2.0,
            self.height() / 2.0,
        )

        scale = min(
            self.width(),
            self.height(),
        ) / float(CORE_SIZE)

        painter.save()
        painter.translate(center)
        painter.scale(scale, scale)

        self._draw_outer_glow(painter)
        self._draw_grid(painter)
        self._draw_particles(painter)
        self._draw_outer_ring(painter)
        self._draw_middle_ring(painter)
        self._draw_inner_ring(painter)
        self._draw_radar_sweep(painter)
        self._draw_center_core(painter)
        self._draw_state_text(painter)

        painter.restore()
        painter.end()

    # =====================================================
    # GLOW
    # =====================================================

    def _draw_outer_glow(
        self,
        painter: QPainter,
    ) -> None:
        pulse = (
            math.sin(
                self._pulse_phase
            )
            + 1.0
        ) / 2.0

        base_radius = (
            CORE_OUTER_RADIUS
            + 38
            + pulse * 8
        )

        for layer in range(
            CORE_GLOW_LAYERS,
            0,
            -1,
        ):
            ratio = (
                layer
                / CORE_GLOW_LAYERS
            )

            radius = (
                base_radius
                + layer * 4
            )

            color = QColor(
                self._current_color
            )

            alpha = int(
                8
                + 22
                * ratio
                * self._activity_level
            )

            color.setAlpha(alpha)

            painter.setPen(
                Qt.PenStyle.NoPen
            )

            painter.setBrush(color)

            painter.drawEllipse(
                QPointF(0.0, 0.0),
                radius,
                radius,
            )

    # =====================================================
    # BACKGROUND GRID
    # =====================================================

    def _draw_grid(
        self,
        painter: QPainter,
    ) -> None:
        color = QColor(
            self._current_color
        )

        color.setAlpha(
            20
            if self._state != "sleeping"
            else 7
        )

        pen = QPen(color)
        pen.setWidthF(0.7)

        painter.setPen(pen)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        for radius in (
            CORE_INNER_RADIUS + 18,
            CORE_MIDDLE_RADIUS + 22,
            CORE_OUTER_RADIUS + 18,
        ):
            painter.drawEllipse(
                QPointF(0.0, 0.0),
                radius,
                radius,
            )

        for angle in range(
            0,
            360,
            30,
        ):
            radians = math.radians(
                angle
            )

            x = math.cos(
                radians
            ) * (
                CORE_OUTER_RADIUS + 34
            )

            y = math.sin(
                radians
            ) * (
                CORE_OUTER_RADIUS + 34
            )

            painter.drawLine(
                QPointF(0.0, 0.0),
                QPointF(x, y),
            )

    # =====================================================
    # PARTICLES
    # =====================================================

    def _draw_particles(
        self,
        painter: QPainter,
    ) -> None:
        for index, particle in enumerate(
            self._particles
        ):
            radians = math.radians(
                particle.angle
            )

            wobble = math.sin(
                self._wave_phase
                + index * 0.7
            ) * 4.0

            radius = (
                particle.radius
                + wobble
            )

            x = math.cos(
                radians
            ) * radius

            y = math.sin(
                radians
            ) * radius

            color = QColor(
                self._current_color
            )

            alpha = int(
                particle.alpha
                * (
                    0.3
                    + self._activity_level * 0.7
                )
            )

            if self._state == "sleeping":
                alpha = int(
                    alpha * 0.2
                )

            color.setAlpha(
                max(
                    5,
                    min(255, alpha),
                )
            )

            painter.setPen(
                Qt.PenStyle.NoPen
            )

            painter.setBrush(color)

            particle_size = (
                particle.size
                * (
                    0.8
                    + self._activity_level * 0.5
                )
            )

            painter.drawEllipse(
                QPointF(x, y),
                particle_size,
                particle_size,
            )

    # =====================================================
    # OUTER RING
    # =====================================================

    def _draw_outer_ring(
        self,
        painter: QPainter,
    ) -> None:
        painter.save()
        painter.rotate(
            self._rotation_slow
        )

        color = QColor(
            self._current_color
        )

        color.setAlpha(
            170
            if self._state != "sleeping"
            else 45
        )

        pen = QPen(color)
        pen.setWidthF(2.0)
        pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(pen)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        rect = QRectF(
            -CORE_OUTER_RADIUS,
            -CORE_OUTER_RADIUS,
            CORE_OUTER_RADIUS * 2,
            CORE_OUTER_RADIUS * 2,
        )

        segment_count = 24
        gap = 5.0
        segment_angle = (
            360.0 / segment_count
        )

        for index in range(
            segment_count
        ):
            start = (
                index
                * segment_angle
                + gap / 2.0
            )

            span = (
                segment_angle
                - gap
            )

            if index % 4 == 0:
                pen.setWidthF(4.0)
            else:
                pen.setWidthF(1.5)

            painter.setPen(pen)

            painter.drawArc(
                rect,
                int(start * 16),
                int(span * 16),
            )

        painter.restore()

    # =====================================================
    # MIDDLE RING
    # =====================================================

    def _draw_middle_ring(
        self,
        painter: QPainter,
    ) -> None:
        painter.save()
        painter.rotate(
            self._rotation_medium
        )

        rect = QRectF(
            -CORE_MIDDLE_RADIUS,
            -CORE_MIDDLE_RADIUS,
            CORE_MIDDLE_RADIUS * 2,
            CORE_MIDDLE_RADIUS * 2,
        )

        color = QColor(
            self._current_color
        )

        color.setAlpha(
            200
            if self._state != "sleeping"
            else 55
        )

        pen = QPen(color)
        pen.setWidthF(3.0)
        pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(pen)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        arcs = (
            (0, 52),
            (72, 44),
            (132, 70),
            (222, 42),
            (282, 58),
        )

        for start, span in arcs:
            painter.drawArc(
                rect,
                start * 16,
                span * 16,
            )

        marker_radius = (
            CORE_MIDDLE_RADIUS + 9
        )

        for angle in (
            25,
            145,
            265,
        ):
            radians = math.radians(
                angle
            )

            x = math.cos(
                radians
            ) * marker_radius

            y = math.sin(
                radians
            ) * marker_radius

            painter.setPen(
                Qt.PenStyle.NoPen
            )

            painter.setBrush(color)

            painter.drawEllipse(
                QPointF(x, y),
                3.0,
                3.0,
            )

        painter.restore()

    # =====================================================
    # INNER RING
    # =====================================================

    def _draw_inner_ring(
        self,
        painter: QPainter,
    ) -> None:
        painter.save()
        painter.rotate(
            self._rotation_fast
        )

        color = QColor(
            self._current_color
        )

        color.setAlpha(
            220
            if self._state != "sleeping"
            else 65
        )

        pen = QPen(color)
        pen.setWidthF(2.4)

        painter.setPen(pen)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        radius = (
            CORE_INNER_RADIUS + 17
        )

        rect = QRectF(
            -radius,
            -radius,
            radius * 2,
            radius * 2,
        )

        for index in range(8):
            start = (
                index * 45
                + 5
            )

            painter.drawArc(
                rect,
                start * 16,
                24 * 16,
            )

        painter.restore()

    # =====================================================
    # RADAR
    # =====================================================

    def _draw_radar_sweep(
        self,
        painter: QPainter,
    ) -> None:
        if self._state in {
            "sleeping",
            "standby",
        }:
            return

        painter.save()
        painter.rotate(
            self._radar_angle
        )

        gradient = QLinearGradient(
            0.0,
            0.0,
            CORE_OUTER_RADIUS,
            0.0,
        )

        transparent = QColor(
            self._current_color
        )
        transparent.setAlpha(0)

        visible = QColor(
            self._current_color
        )
        visible.setAlpha(
            int(
                90
                * self._activity_level
            )
        )

        gradient.setColorAt(
            0.0,
            visible,
        )

        gradient.setColorAt(
            1.0,
            transparent,
        )

        path = QPainterPath()
        path.moveTo(0.0, 0.0)

        sweep_radius = (
            CORE_OUTER_RADIUS + 22
        )

        path.arcTo(
            QRectF(
                -sweep_radius,
                -sweep_radius,
                sweep_radius * 2,
                sweep_radius * 2,
            ),
            -16.0,
            32.0,
        )

        path.closeSubpath()

        painter.setPen(
            Qt.PenStyle.NoPen
        )

        painter.setBrush(gradient)
        painter.drawPath(path)

        painter.restore()

    # =====================================================
    # CENTER CORE
    # =====================================================

    def _draw_center_core(
        self,
        painter: QPainter,
    ) -> None:
        pulse = (
            math.sin(
                self._pulse_phase
            )
            + 1.0
        ) / 2.0

        radius = (
            CORE_INNER_RADIUS
            + pulse
            * 7.0
            * self._activity_level
        )

        gradient = QRadialGradient(
            QPointF(0.0, 0.0),
            radius * 1.6,
        )

        center_color = QColor(
            self._current_color
        )
        center_color.setAlpha(
            220
            if self._state != "sleeping"
            else 55
        )

        middle_color = QColor(
            self._current_color
        )
        middle_color.setAlpha(
            95
            if self._state != "sleeping"
            else 20
        )

        edge_color = QColor(
            self._current_color
        )
        edge_color.setAlpha(0)

        gradient.setColorAt(
            0.0,
            center_color,
        )

        gradient.setColorAt(
            0.45,
            middle_color,
        )

        gradient.setColorAt(
            1.0,
            edge_color,
        )

        painter.setPen(
            Qt.PenStyle.NoPen
        )

        painter.setBrush(gradient)

        painter.drawEllipse(
            QPointF(0.0, 0.0),
            radius * 1.6,
            radius * 1.6,
        )

        core_color = QColor(
            self._current_color
        )

        core_color.setAlpha(
            230
            if self._state != "sleeping"
            else 70
        )

        painter.setBrush(
            core_color
        )

        painter.drawEllipse(
            QPointF(0.0, 0.0),
            radius * 0.56,
            radius * 0.56,
        )

        highlight = QColor(
            255,
            255,
            255,
            170
            if self._state != "sleeping"
            else 35,
        )

        painter.setBrush(
            highlight
        )

        painter.drawEllipse(
            QPointF(
                -radius * 0.16,
                -radius * 0.18,
            ),
            radius * 0.10,
            radius * 0.10,
        )

        self._draw_audio_wave(
            painter,
            radius,
        )

    # =====================================================
    # AUDIO WAVE
    # =====================================================

    def _draw_audio_wave(
        self,
        painter: QPainter,
        radius: float,
    ) -> None:
        if self._state not in {
            "listening",
            "speaking",
            "thinking",
        }:
            return

        color = QColor(
            TEXT_PRIMARY
        )

        color.setAlpha(210)

        pen = QPen(color)
        pen.setWidthF(1.8)
        pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )

        painter.setPen(pen)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        path = QPainterPath()

        width = radius * 0.9
        start_x = -width / 2.0

        points = 28

        for index in range(
            points + 1
        ):
            ratio = index / points

            x = (
                start_x
                + ratio * width
            )

            amplitude = (
                math.sin(
                    self._wave_phase
                    + index * 0.8
                )
                * radius
                * 0.12
                * self._activity_level
            )

            if self._state == "thinking":
                amplitude *= 0.55

            if index == 0:
                path.moveTo(
                    x,
                    amplitude,
                )
            else:
                path.lineTo(
                    x,
                    amplitude,
                )

        painter.drawPath(path)

    # =====================================================
    # STATE TEXT
    # =====================================================

    def _draw_state_text(
        self,
        painter: QPainter,
    ) -> None:
        state_names = {
            "standby": "STANDBY",
            "activated": "ONLINE",
            "listening": "LISTENING",
            "thinking": "PROCESSING",
            "speaking": "SPEAKING",
            "sleeping": "SLEEP MODE",
            "error": "CORE ERROR",
        }

        state_text = state_names[
            self._state
        ]

        text_color = QColor(
            self._current_color
        )

        if self._state == "sleeping":
            text_color = QColor(
                TEXT_MUTED
            )

        text_color.setAlpha(
            220
            if self._state != "sleeping"
            else 100
        )

        painter.setPen(text_color)

        state_font = QFont(
            FONT_FAMILY,
            10,
        )

        state_font.setBold(True)
        state_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing,
            2.0,
        )

        painter.setFont(state_font)

        state_rect = QRectF(
            -120.0,
            CORE_OUTER_RADIUS + 52.0,
            240.0,
            30.0,
        )

        painter.drawText(
            state_rect,
            Qt.AlignmentFlag.AlignCenter,
            state_text,
        )

        subtitle_color = QColor(
            TEXT_MUTED
        )

        subtitle_color.setAlpha(
            150
            if self._state != "sleeping"
            else 65
        )

        painter.setPen(
            subtitle_color
        )

        subtitle_font = QFont(
            FONT_FAMILY,
            7,
        )

        subtitle_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing,
            1.3,
        )

        painter.setFont(
            subtitle_font
        )

        subtitle_rect = QRectF(
            -160.0,
            CORE_OUTER_RADIUS + 75.0,
            320.0,
            24.0,
        )

        painter.drawText(
            subtitle_rect,
            Qt.AlignmentFlag.AlignCenter,
            "REYES ARTIFICIAL INTELLIGENCE CORE",
        )

    # =====================================================
    # CLEANUP
    # =====================================================

    def closeEvent(self, event) -> None:
        self._animation_timer.stop()
        super().closeEvent(event)


# =========================================================
# STANDALONE TEST
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    app.setStyleSheet(
        GLOBAL_STYLESHEET
    )

    window = QWidget()

    window.setWindowTitle(
        "REYES AI Core Test"
    )

    window.resize(
        700,
        700,
    )

    window.setStyleSheet(
        f"""
        QWidget {{
            background-color: {BACKGROUND};
        }}
        """
    )

    core = AICore(
        parent=window
    )

    core.resize(
        CORE_SIZE,
        CORE_SIZE,
    )

    core.move(
        int(
            (
                window.width()
                - CORE_SIZE
            ) / 2
        ),
        int(
            (
                window.height()
                - CORE_SIZE
            ) / 2
        ),
    )

    states = [
        "standby",
        "activated",
        "listening",
        "thinking",
        "speaking",
        "sleeping",
        "error",
    ]

    state_index = 0

    def cycle_state() -> None:
        global state_index

        state = states[
            state_index
        ]

        core.set_state(
            state
        )

        print(
            "AI core state:",
            state,
        )

        state_index = (
            state_index + 1
        ) % len(states)

    state_timer = QTimer()

    state_timer.timeout.connect(
        cycle_state
    )

    state_timer.start(
        3000
    )

    window.show()

    sys.exit(
        app.exec()
    )