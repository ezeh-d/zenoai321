# gui old/theme.py

from __future__ import annotations


# =========================================================
# WINDOW
# =========================================================

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 850
MIN_WINDOW_WIDTH = 1100
MIN_WINDOW_HEIGHT = 700

APP_TITLE = "REYES AI"


# =========================================================
# COLORS
# =========================================================

BACKGROUND = "#02070B"
BACKGROUND_ALT = "#050D13"
PANEL_BACKGROUND = "#07131C"
PANEL_BACKGROUND_ALT = "#091A25"

CARD_BACKGROUND = "#0A1822"
CARD_BACKGROUND_HOVER = "#0D2430"

BORDER = "#123746"
BORDER_BRIGHT = "#00C8E8"

PRIMARY = "#00E5FF"
PRIMARY_DARK = "#007D91"
PRIMARY_SOFT = "#6CEEFF"

SECONDARY = "#7C3AED"
SECONDARY_SOFT = "#A78BFA"

SUCCESS = "#22C55E"
WARNING = "#F59E0B"
ERROR = "#EF4444"

TEXT_PRIMARY = "#E8FCFF"
TEXT_SECONDARY = "#8CB4BF"
TEXT_MUTED = "#4D707A"

TRANSPARENT = "transparent"


# =========================================================
# STATE COLORS
# =========================================================

STATE_COLORS = {
    "standby": "#00B8D4",
    "activated": "#00E5FF",
    "listening": "#22C55E",
    "thinking": "#A855F7",
    "speaking": "#F97316",
    "sleeping": "#64748B",
    "error": "#EF4444",
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
# CORE SETTINGS
# =========================================================

CORE_SIZE = 440

CORE_INNER_RADIUS = 54
CORE_MIDDLE_RADIUS = 92
CORE_OUTER_RADIUS = 145

CORE_GLOW_LAYERS = 8
CORE_PARTICLE_COUNT = 32

CORE_ROTATION_SPEED_SLOW = 0.35
CORE_ROTATION_SPEED_MEDIUM = 0.8
CORE_ROTATION_SPEED_FAST = 1.5

CORE_PULSE_SPEED = 0.035


# =========================================================
# HUD SETTINGS
# =========================================================

HUD_PANEL_WIDTH = 280
HUD_PANEL_RADIUS = 16

HUD_BORDER_WIDTH = 1
HUD_MARGIN = 24
HUD_SPACING = 14

ANIMATION_INTERVAL_MS = 16
SYSTEM_UPDATE_INTERVAL_MS = 1000
CLOCK_UPDATE_INTERVAL_MS = 1000


# =========================================================
# SHADOWS AND EFFECTS
# =========================================================

GLOW_BLUR_RADIUS = 40
GLOW_STRENGTH = 0.85

PANEL_SHADOW_BLUR = 24
PANEL_SHADOW_OFFSET_X = 0
PANEL_SHADOW_OFFSET_Y = 6


# =========================================================
# PYQT / PYSIDE6 STYLESHEET
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

QLabel {{
    background: transparent;
    color: {TEXT_PRIMARY};
}}

QLabel#BrandLabel {{
    color: {PRIMARY};
    font-size: {TITLE_FONT_SIZE}px;
    font-weight: 700;
    letter-spacing: 5px;
}}

QLabel#StatusLabel {{
    color: {PRIMARY};
    font-size: {STATUS_FONT_SIZE}px;
    font-weight: 700;
    letter-spacing: 3px;
}}

QLabel#SubStatusLabel {{
    color: {TEXT_SECONDARY};
    font-size: {TEXT_FONT_SIZE}px;
}}

QLabel#HudTitle {{
    color: {PRIMARY_SOFT};
    font-size: {HUD_FONT_SIZE}px;
    font-weight: 700;
    letter-spacing: 2px;
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
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {PRIMARY};
    border-radius: 4px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {PRIMARY_DARK};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {PRIMARY};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
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
    """
    Return the correct color for a REYES state.
    """

    return STATE_COLORS.get(
        state.lower().strip(),
        PRIMARY,
    )


def rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    """
    Convert a hex color into an RGBA tuple.

    Example:
        rgba("#00E5FF", 180)
    """

    cleaned = hex_color.lstrip("#")

    if len(cleaned) != 6:
        raise ValueError(
            f"Invalid hex color: {hex_color}"
        )

    red = int(cleaned[0:2], 16)
    green = int(cleaned[2:4], 16)
    blue = int(cleaned[4:6], 16)

    return red, green, blue, alpha