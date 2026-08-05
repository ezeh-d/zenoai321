# gui/theme.py
#
# REYES design system — cohesive deep-cyan HUD ("JARVIS" aesthetic).
# All GUI colors/typography/core geometry flow from here, so editing this
# file restyles the entire interface at once.

from __future__ import annotations


# =========================================================
# APPLICATION
# =========================================================

APP_TITLE = "REYES AI"

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 850

MIN_WINDOW_WIDTH = 1100
MIN_WINDOW_HEIGHT = 700


# =========================================================
# COLORS — deep-cyan HUD
# =========================================================

BACKGROUND = "#04080E"
BACKGROUND_ALT = "#071019"

PANEL_BACKGROUND = "#08151F"
PANEL_BACKGROUND_ALT = "#0A1C28"

CARD_BACKGROUND = "#0B1E2A"
CARD_BACKGROUND_HOVER = "#0F2A38"

BORDER = "#123B49"
BORDER_BRIGHT = "#22D3EE"

PRIMARY = "#22D3EE"
PRIMARY_DARK = "#0B7285"
PRIMARY_SOFT = "#7FEFFF"

SECONDARY = "#38BDF8"
SECONDARY_SOFT = "#7DD3FC"

SUCCESS = "#2DD4BF"
WARNING = "#FBBF24"
ERROR = "#F87171"

TEXT_PRIMARY = "#E6FBFF"
TEXT_SECONDARY = "#8FBECB"
TEXT_MUTED = "#4E7B88"

# Extra HUD tokens (available to panels/widgets)
GRID_COLOR = "#0E3A44"
GLOW_CYAN = "#22D3EE"
ACCENT_DIM = "#0E4A57"


# =========================================================
# REYES STATES — harmonized cool family
# =========================================================

STATE_COLORS = {
    "standby": "#22B8D4",
    "activated": "#22D3EE",
    "listening": "#2DD4BF",
    "thinking": "#38BDF8",
    "speaking": "#67E8F9",
    "sleeping": "#3E5A66",
    "error": "#F87171",
}


# =========================================================
# FONTS
# =========================================================

FONT_FAMILY = "Segoe UI"
MONO_FONT_FAMILY = "Consolas"

TITLE_FONT_SIZE = 30
HEADER_FONT_SIZE = 20
TEXT_FONT_SIZE = 14
SMALL_TEXT_FONT_SIZE = 11
HUD_FONT_SIZE = 12
STATUS_FONT_SIZE = 24


# =========================================================
# AI CORE — richer glow
# =========================================================

CORE_SIZE = 440
CORE_INNER_RADIUS = 52
CORE_MIDDLE_RADIUS = 92
CORE_OUTER_RADIUS = 148

CORE_GLOW_LAYERS = 10
CORE_PARTICLE_COUNT = 40

CORE_ROTATION_SPEED_SLOW = 0.35
CORE_ROTATION_SPEED_MEDIUM = 0.8
CORE_ROTATION_SPEED_FAST = 1.5

CORE_PULSE_SPEED = 0.03


# =========================================================
# HUD
# =========================================================

HUD_PANEL_WIDTH = 280
HUD_PANEL_RADIUS = 16

HUD_BORDER_WIDTH = 1
HUD_MARGIN = 24
HUD_SPACING = 14


# =========================================================
# TIMERS
# =========================================================

ANIMATION_INTERVAL_MS = 16
SYSTEM_UPDATE_INTERVAL_MS = 1000
CLOCK_UPDATE_INTERVAL_MS = 1000


# =========================================================
# EFFECTS
# =========================================================

GLOW_BLUR_RADIUS = 48
GLOW_STRENGTH = 0.9

PANEL_SHADOW_BLUR = 28
PANEL_SHADOW_OFFSET_X = 0
PANEL_SHADOW_OFFSET_Y = 6


# =========================================================
# PYSIDE6 STYLESHEET  (QSS-valid properties only)
# =========================================================

GLOBAL_STYLESHEET = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT_PRIMARY};
    font-family: "{FONT_FAMILY}";
}}

QMainWindow {{
    background-color: {BACKGROUND};
}}

QFrame#HudPanel {{
    background-color: {PANEL_BACKGROUND};
    border: 1px solid {BORDER};
    border-radius: {HUD_PANEL_RADIUS}px;
}}

QFrame#TranscriptPanel {{
    background-color: {PANEL_BACKGROUND_ALT};
    border: 1px solid {BORDER};
    border-radius: {HUD_PANEL_RADIUS}px;
}}

QLabel {{
    background: transparent;
    color: {TEXT_PRIMARY};
}}

QLabel#BrandLabel {{
    color: {PRIMARY};
    font-size: {TITLE_FONT_SIZE}px;
    font-weight: 700;
}}

QLabel#StatusLabel {{
    color: {PRIMARY};
    font-size: {STATUS_FONT_SIZE}px;
    font-weight: 700;
}}

QLabel#SubStatusLabel {{
    color: {TEXT_SECONDARY};
    font-size: {TEXT_FONT_SIZE}px;
}}

QLabel#HudTitle {{
    color: {PRIMARY_SOFT};
    font-size: {HUD_FONT_SIZE}px;
    font-weight: 700;
}}

QLabel#HudValue {{
    color: {TEXT_PRIMARY};
    font-family: "{MONO_FONT_FAMILY}";
    font-size: {TEXT_FONT_SIZE}px;
}}

QLabel#HudMuted {{
    color: {TEXT_MUTED};
    font-size: {SMALL_TEXT_FONT_SIZE}px;
}}

QPushButton {{
    background-color: {CARD_BACKGROUND};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: {TEXT_FONT_SIZE}px;
}}

QPushButton:hover {{
    background-color: {CARD_BACKGROUND_HOVER};
    border-color: {PRIMARY};
}}

QPushButton:pressed {{
    background-color: {PRIMARY_DARK};
}}

QPushButton#DangerButton {{
    color: #FCA5A5;
    border-color: #7F1D1D;
}}

QPushButton#DangerButton:hover {{
    background-color: #3F1218;
    border-color: {ERROR};
}}

QProgressBar {{
    background-color: {BACKGROUND_ALT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {PRIMARY};
    border-radius: 4px;
}}

QScrollBar:vertical {{
    background: {BACKGROUND_ALT};
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background: {BORDER};
    min-height: 24px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: {PRIMARY_DARK};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QToolTip {{
    background-color: {PANEL_BACKGROUND_ALT};
    color: {TEXT_PRIMARY};
    border: 1px solid {PRIMARY};
    padding: 6px;
}}
"""


# =========================================================
# HELPERS
# =========================================================

def get_state_color(state: str) -> str:
    return STATE_COLORS.get(
        state.strip().lower(),
        PRIMARY,
    )


def rgba(
    hex_color: str,
    alpha: int,
) -> tuple[int, int, int, int]:

    cleaned = hex_color.lstrip("#")

    if len(cleaned) != 6:
        raise ValueError(
            f"Invalid hex color: {hex_color}"
        )

    red = int(cleaned[0:2], 16)
    green = int(cleaned[2:4], 16)
    blue = int(cleaned[4:6], 16)

    alpha = max(0, min(255, alpha))

    return red, green, blue, alpha
