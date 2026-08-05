# gui/hud_panel.py

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from gui.system_monitor import SystemMonitor, SystemSnapshot
from gui.theme import (
    BACKGROUND,
    BORDER,
    CLOCK_UPDATE_INTERVAL_MS,
    ERROR,
    FONT_FAMILY,
    HUD_PANEL_RADIUS,
    HUD_PANEL_WIDTH,
    MONO_FONT_FAMILY,
    PANEL_BACKGROUND,
    PRIMARY,
    PRIMARY_SOFT,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)


# =========================================================
# SMALL STATUS INDICATOR
# =========================================================

class StatusDot(QWidget):
    """
    Small glowing circular status indicator.
    """

    def __init__(
        self,
        color: str = SUCCESS,
        size: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._color = QColor(color)
        self._dot_size = size

        self.setFixedSize(size + 8, size + 8)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        center_x = self.width() / 2
        center_y = self.height() / 2

        glow = QColor(self._color)
        glow.setAlpha(55)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)

        painter.drawEllipse(
            int(center_x - self._dot_size / 1.1),
            int(center_y - self._dot_size / 1.1),
            int(self._dot_size * 1.8),
            int(self._dot_size * 1.8),
        )

        painter.setBrush(self._color)

        painter.drawEllipse(
            int(center_x - self._dot_size / 2),
            int(center_y - self._dot_size / 2),
            self._dot_size,
            self._dot_size,
        )

        painter.end()


# =========================================================
# SECTION DIVIDER
# =========================================================

class HudDivider(QFrame):
    """
    Thin horizontal divider used between HUD sections.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setFrameShape(
            QFrame.Shape.HLine
        )

        self.setFixedHeight(1)

        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {BORDER};
                border: none;
            }}
            """
        )


# =========================================================
# CUSTOM HUD PROGRESS BAR
# =========================================================

class HudProgressBar(QProgressBar):
    """
    Compact progress bar designed for system information.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(7)

        self._bar_color = PRIMARY
        self._apply_style()

    def set_bar_color(
        self,
        color: str,
    ) -> None:
        self._bar_color = color
        self._apply_style()

    def set_percentage(
        self,
        value: float,
    ) -> None:
        safe_value = max(
            0,
            min(100, int(round(value))),
        )

        self.setValue(safe_value)

        if safe_value >= 90:
            self.set_bar_color(ERROR)
        elif safe_value >= 75:
            self.set_bar_color(WARNING)
        else:
            self.set_bar_color(PRIMARY)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: #031016;
                border: 1px solid {BORDER};
                border-radius: 3px;
                min-height: 7px;
                max-height: 7px;
            }}

            QProgressBar::chunk {{
                background-color: {self._bar_color};
                border-radius: 2px;
            }}
            """
        )


# =========================================================
# HUD VALUE ROW
# =========================================================

class HudValueRow(QWidget):
    """
    Label and value row used throughout the HUD.
    """

    def __init__(
        self,
        title: str,
        value: str = "--",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.title_label = QLabel(title.upper())
        self.value_label = QLabel(value)

        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_MUTED};
                font-family: "{FONT_FAMILY}";
                font-size: 10px;
                font-weight: 600;
            }}
            """
        )

        self.value_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_PRIMARY};
                font-family: "{MONO_FONT_FAMILY}";
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )

        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        layout = QHBoxLayout(self)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(self.value_label)

    def set_value(
        self,
        value: str,
    ) -> None:
        self.value_label.setText(value)

    def set_value_color(
        self,
        color: str,
    ) -> None:
        self.value_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {color};
                font-family: "{MONO_FONT_FAMILY}";
                font-size: 11px;
                font-weight: 600;
            }}
            """
        )


# =========================================================
# SYSTEM METER
# =========================================================

class SystemMeter(QWidget):
    """
    Named percentage meter used for CPU, RAM, and disk.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.title_label = QLabel(title.upper())
        self.percent_label = QLabel("0%")
        self.detail_label = QLabel("--")
        self.progress_bar = HudProgressBar()

        self.title_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_SECONDARY};
                font-family: "{FONT_FAMILY}";
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            """
        )

        self.percent_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY_SOFT};
                font-family: "{MONO_FONT_FAMILY}";
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )

        self.detail_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_MUTED};
                font-family: "{MONO_FONT_FAMILY}";
                font-size: 9px;
            }}
            """
        )

        self.percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
        )

        self.detail_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
        )

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.percent_label)

        layout = QVBoxLayout(self)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        layout.addLayout(top_layout)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.detail_label)

    def set_data(
        self,
        percentage: float,
        detail: str,
    ) -> None:
        safe_percentage = max(
            0.0,
            min(100.0, percentage),
        )

        self.percent_label.setText(
            f"{safe_percentage:.0f}%"
        )

        self.detail_label.setText(detail)

        self.progress_bar.set_percentage(
            safe_percentage
        )

        if safe_percentage >= 90:
            color = ERROR
        elif safe_percentage >= 75:
            color = WARNING
        else:
            color = PRIMARY_SOFT

        self.percent_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {color};
                font-family: "{MONO_FONT_FAMILY}";
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )


# =========================================================
# HUD SECTION TITLE
# =========================================================

class HudSectionTitle(QWidget):
    """
    Section heading with a status dot.
    """

    def __init__(
        self,
        title: str,
        dot_color: str = PRIMARY,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.dot = StatusDot(
            color=dot_color,
            size=7,
        )

        self.label = QLabel(
            title.upper()
        )

        self.label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY_SOFT};
                font-family: "{FONT_FAMILY}";
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            """
        )

        layout = QHBoxLayout(self)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        layout.addStretch(1)


# =========================================================
# MAIN HUD PANEL
# =========================================================

class HudPanel(QFrame):
    """
    Futuristic REYES system information panel.

    Displays:

        current time
        current date
        AI status
        CPU usage
        RAM usage
        disk usage
        network speed
        battery information
        process count
        system uptime
        hostname
        operating system
    """

    monitor_error = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        auto_start_monitor: bool = True,
    ) -> None:
        super().__init__(parent)

        self.setObjectName("HudPanel")

        self.setMinimumWidth(HUD_PANEL_WIDTH)
        self.setMaximumWidth(HUD_PANEL_WIDTH + 50)

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )

        self._current_state = "standby"

        self.monitor = SystemMonitor(
            parent=self
        )

        self.monitor.snapshot_updated.connect(
            self.update_snapshot
        )

        self.monitor.monitor_error.connect(
            self._handle_monitor_error
        )

        self.clock_timer = QTimer(self)

        self.clock_timer.timeout.connect(
            self.update_clock
        )

        self.clock_timer.start(
            CLOCK_UPDATE_INTERVAL_MS
        )

        self._build_interface()
        self._apply_panel_style()
        self._apply_shadow()
        self.update_clock()

        if auto_start_monitor:
            self.start_monitoring()

    # =====================================================
    # INTERFACE CREATION
    # =====================================================

    def _build_interface(self) -> None:
        self.main_layout = QVBoxLayout(self)

        self.main_layout.setContentsMargins(
            18,
            18,
            18,
            18,
        )

        self.main_layout.setSpacing(14)

        self._build_header_section()
        self.main_layout.addWidget(HudDivider())

        self._build_ai_status_section()
        self.main_layout.addWidget(HudDivider())

        self._build_performance_section()
        self.main_layout.addWidget(HudDivider())

        self._build_network_section()
        self.main_layout.addWidget(HudDivider())

        self._build_power_section()
        self.main_layout.addWidget(HudDivider())

        self._build_system_section()

        self.main_layout.addItem(
            QSpacerItem(
                20,
                20,
                QSizePolicy.Policy.Minimum,
                QSizePolicy.Policy.Expanding,
            )
        )

        self._build_footer_section()

    def _build_header_section(self) -> None:
        self.time_label = QLabel("00:00:00")
        self.date_label = QLabel("INITIALIZING")

        self.time_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.date_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.time_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_PRIMARY};
                font-family: "{MONO_FONT_FAMILY}";
                font-size: 25px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            """
        )

        self.date_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_SECONDARY};
                font-family: "{FONT_FAMILY}";
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1px;
            }}
            """
        )

        header_layout = QVBoxLayout()

        header_layout.setContentsMargins(
            0,
            2,
            0,
            2,
        )

        header_layout.setSpacing(4)

        header_layout.addWidget(
            self.time_label
        )

        header_layout.addWidget(
            self.date_label
        )

        self.main_layout.addLayout(
            header_layout
        )

    def _build_ai_status_section(self) -> None:
        section_title = HudSectionTitle(
            "REYES CORE",
            dot_color=SUCCESS,
        )

        self.ai_status_dot = section_title.dot

        self.ai_state_label = QLabel(
            "STANDBY"
        )

        self.ai_substatus_label = QLabel(
            "Awaiting voice activation"
        )

        self.ai_state_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {PRIMARY};
                font-family: "{FONT_FAMILY}";
                font-size: 17px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            """
        )

        self.ai_substatus_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_MUTED};
                font-family: "{FONT_FAMILY}";
                font-size: 10px;
            }}
            """
        )

        self.ai_substatus_label.setWordWrap(True)

        status_layout = QVBoxLayout()

        status_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        status_layout.setSpacing(6)

        status_layout.addWidget(
            section_title
        )

        status_layout.addWidget(
            self.ai_state_label
        )

        status_layout.addWidget(
            self.ai_substatus_label
        )

        self.main_layout.addLayout(
            status_layout
        )

    def _build_performance_section(self) -> None:
        title = HudSectionTitle(
            "System Performance",
            dot_color=PRIMARY,
        )

        self.cpu_meter = SystemMeter(
            "CPU"
        )

        self.memory_meter = SystemMeter(
            "Memory"
        )

        self.disk_meter = SystemMeter(
            "System Disk"
        )

        layout = QVBoxLayout()

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.setSpacing(12)

        layout.addWidget(title)
        layout.addWidget(self.cpu_meter)
        layout.addWidget(self.memory_meter)
        layout.addWidget(self.disk_meter)

        self.main_layout.addLayout(layout)

    def _build_network_section(self) -> None:
        title = HudSectionTitle(
            "Network Link",
            dot_color=SUCCESS,
        )

        self.network_dot = title.dot

        self.download_row = HudValueRow(
            "Download",
            "0.0 KB/s",
        )

        self.upload_row = HudValueRow(
            "Upload",
            "0.0 KB/s",
        )

        self.received_row = HudValueRow(
            "Received",
            "0.0 MB",
        )

        self.sent_row = HudValueRow(
            "Sent",
            "0.0 MB",
        )

        layout = QVBoxLayout()

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.setSpacing(7)

        layout.addWidget(title)
        layout.addWidget(self.download_row)
        layout.addWidget(self.upload_row)
        layout.addWidget(self.received_row)
        layout.addWidget(self.sent_row)

        self.main_layout.addLayout(layout)

    def _build_power_section(self) -> None:
        title = HudSectionTitle(
            "Power System",
            dot_color=SUCCESS,
        )

        self.power_dot = title.dot

        self.battery_row = HudValueRow(
            "Battery",
            "SCANNING",
        )

        self.power_mode_row = HudValueRow(
            "Power",
            "--",
        )

        layout = QVBoxLayout()

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.setSpacing(7)

        layout.addWidget(title)
        layout.addWidget(self.battery_row)
        layout.addWidget(self.power_mode_row)

        self.main_layout.addLayout(layout)

    def _build_system_section(self) -> None:
        title = HudSectionTitle(
            "System Identity",
            dot_color=PRIMARY,
        )

        self.hostname_row = HudValueRow(
            "Node",
            "--",
        )

        self.os_row = HudValueRow(
            "Platform",
            "--",
        )

        self.process_row = HudValueRow(
            "Processes",
            "--",
        )

        self.uptime_row = HudValueRow(
            "Uptime",
            "--",
        )

        layout = QVBoxLayout()

        layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        layout.setSpacing(7)

        layout.addWidget(title)
        layout.addWidget(self.hostname_row)
        layout.addWidget(self.os_row)
        layout.addWidget(self.process_row)
        layout.addWidget(self.uptime_row)

        self.main_layout.addLayout(layout)

    def _build_footer_section(self) -> None:
        footer_layout = QHBoxLayout()

        footer_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        footer_layout.setSpacing(7)

        self.footer_dot = StatusDot(
            color=SUCCESS,
            size=6,
        )

        self.footer_label = QLabel(
            "ALL SYSTEMS OPERATIONAL"
        )

        self.footer_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {TEXT_MUTED};
                font-family: "{MONO_FONT_FAMILY}";
                font-size: 9px;
                font-weight: 600;
                letter-spacing: 1px;
            }}
            """
        )

        footer_layout.addWidget(
            self.footer_dot
        )

        footer_layout.addWidget(
            self.footer_label
        )

        footer_layout.addStretch(1)

        self.main_layout.addLayout(
            footer_layout
        )

    # =====================================================
    # PANEL APPEARANCE
    # =====================================================

    def _apply_panel_style(self) -> None:
        self.setStyleSheet(
            f"""
            QFrame#HudPanel {{
                background-color: {PANEL_BACKGROUND};
                border: 1px solid {BORDER};
                border-radius: {HUD_PANEL_RADIUS}px;
            }}
            """
        )

    def _apply_shadow(self) -> None:
        shadow = QGraphicsDropShadowEffect(
            self
        )

        shadow.setBlurRadius(30)
        shadow.setOffset(0, 7)

        shadow_color = QColor(PRIMARY)
        shadow_color.setAlpha(32)

        shadow.setColor(shadow_color)

        self.setGraphicsEffect(shadow)

    # =====================================================
    # MONITOR CONTROL
    # =====================================================

    def start_monitoring(self) -> None:
        self.monitor.start()

    def stop_monitoring(self) -> None:
        self.monitor.stop()

    # =====================================================
    # CLOCK
    # =====================================================

    def update_clock(self) -> None:
        now = datetime.now()

        self.time_label.setText(
            now.strftime("%H:%M:%S")
        )

        self.date_label.setText(
            now.strftime(
                "%A  •  %d %B %Y"
            ).upper()
        )

    # =====================================================
    # SYSTEM SNAPSHOT UPDATE
    # =====================================================

    def update_snapshot(
        self,
        snapshot: SystemSnapshot,
    ) -> None:
        self.cpu_meter.set_data(
            snapshot.cpu_percent,
            SystemMonitor.format_frequency(
                snapshot.cpu_frequency_mhz
            ),
        )

        self.memory_meter.set_data(
            snapshot.memory_percent,
            (
                f"{snapshot.memory_used_gb:.1f} / "
                f"{snapshot.memory_total_gb:.1f} GB"
            ),
        )

        self.disk_meter.set_data(
            snapshot.disk_percent,
            (
                f"{snapshot.disk_used_gb:.1f} / "
                f"{snapshot.disk_total_gb:.1f} GB"
            ),
        )

        self.download_row.set_value(
            SystemMonitor.format_network_speed(
                snapshot.download_speed_kbps
            )
        )

        self.upload_row.set_value(
            SystemMonitor.format_network_speed(
                snapshot.upload_speed_kbps
            )
        )

        self.received_row.set_value(
            f"{snapshot.network_received_mb:.1f} MB"
        )

        self.sent_row.set_value(
            f"{snapshot.network_sent_mb:.1f} MB"
        )

        self._update_network_status(
            snapshot
        )

        self._update_battery_status(
            snapshot
        )

        self.hostname_row.set_value(
            snapshot.hostname
        )

        self.os_row.set_value(
            snapshot.operating_system
        )

        self.process_row.set_value(
            str(snapshot.process_count)
        )

        self.uptime_row.set_value(
            SystemMonitor.format_uptime(
                snapshot.uptime_seconds
            )
        )

        self._update_footer_status(
            snapshot
        )

    def _update_network_status(
        self,
        snapshot: SystemSnapshot,
    ) -> None:
        total_speed = (
            snapshot.download_speed_kbps
            + snapshot.upload_speed_kbps
        )

        if total_speed > 0.1:
            self.network_dot.set_color(
                SUCCESS
            )
        else:
            self.network_dot.set_color(
                TEXT_MUTED
            )

    def _update_battery_status(
        self,
        snapshot: SystemSnapshot,
    ) -> None:
        percent = snapshot.battery_percent
        plugged = snapshot.battery_plugged

        if percent is None:
            self.battery_row.set_value(
                "DESKTOP"
            )

            self.power_mode_row.set_value(
                "AC POWER"
            )

            self.power_dot.set_color(
                SUCCESS
            )

            self.battery_row.set_value_color(
                PRIMARY_SOFT
            )

            return

        battery_text = f"{percent:.0f}%"

        if plugged:
            mode_text = "CHARGING"
        else:
            mode_text = "BATTERY"

        self.battery_row.set_value(
            battery_text
        )

        self.power_mode_row.set_value(
            mode_text
        )

        if plugged:
            color = SUCCESS
        elif percent <= 15:
            color = ERROR
        elif percent <= 30:
            color = WARNING
        else:
            color = PRIMARY_SOFT

        self.power_dot.set_color(color)
        self.battery_row.set_value_color(
            color
        )

    def _update_footer_status(
        self,
        snapshot: SystemSnapshot,
    ) -> None:
        critical = (
            snapshot.cpu_percent >= 95
            or snapshot.memory_percent >= 95
            or snapshot.disk_percent >= 97
        )

        warning = (
            snapshot.cpu_percent >= 80
            or snapshot.memory_percent >= 80
            or snapshot.disk_percent >= 85
        )

        if critical:
            self.footer_dot.set_color(
                ERROR
            )

            self.footer_label.setText(
                "SYSTEM LOAD CRITICAL"
            )

            self.footer_label.setStyleSheet(
                f"""
                QLabel {{
                    background: transparent;
                    color: {ERROR};
                    font-family: "{MONO_FONT_FAMILY}";
                    font-size: 9px;
                    font-weight: 700;
                    letter-spacing: 1px;
                }}
                """
            )

        elif warning:
            self.footer_dot.set_color(
                WARNING
            )

            self.footer_label.setText(
                "HIGH SYSTEM LOAD"
            )

            self.footer_label.setStyleSheet(
                f"""
                QLabel {{
                    background: transparent;
                    color: {WARNING};
                    font-family: "{MONO_FONT_FAMILY}";
                    font-size: 9px;
                    font-weight: 700;
                    letter-spacing: 1px;
                }}
                """
            )

        else:
            self.footer_dot.set_color(
                SUCCESS
            )

            self.footer_label.setText(
                "ALL SYSTEMS OPERATIONAL"
            )

            self.footer_label.setStyleSheet(
                f"""
                QLabel {{
                    background: transparent;
                    color: {TEXT_MUTED};
                    font-family: "{MONO_FONT_FAMILY}";
                    font-size: 9px;
                    font-weight: 600;
                    letter-spacing: 1px;
                }}
                """
            )

    # =====================================================
    # AI STATE CONTROL
    # =====================================================

    def set_ai_state(
        self,
        state: str,
        message: str | None = None,
    ) -> None:
        normalized = state.strip().lower()

        state_map = {
            "standby": {
                "title": "STANDBY",
                "message": "Awaiting voice activation",
                "color": PRIMARY,
            },
            "activated": {
                "title": "ACTIVATED",
                "message": "REYES core online",
                "color": PRIMARY_SOFT,
            },
            "listening": {
                "title": "LISTENING",
                "message": "Voice input active",
                "color": SUCCESS,
            },
            "thinking": {
                "title": "PROCESSING",
                "message": "Analyzing request",
                "color": "#A855F7",
            },
            "speaking": {
                "title": "SPEAKING",
                "message": "Voice output active",
                "color": "#F97316",
            },
            "sleeping": {
                "title": "SLEEP MODE",
                "message": "Low-power monitoring enabled",
                "color": "#64748B",
            },
            "error": {
                "title": "CORE ERROR",
                "message": "REYES requires attention",
                "color": ERROR,
            },
        }

        settings = state_map.get(
            normalized,
            state_map["standby"],
        )

        self._current_state = normalized

        title = settings["title"]
        subtitle = (
            message
            if message is not None
            else settings["message"]
        )

        color = settings["color"]

        self.ai_state_label.setText(title)
        self.ai_substatus_label.setText(
            subtitle
        )

        self.ai_status_dot.set_color(color)

        self.ai_state_label.setStyleSheet(
            f"""
            QLabel {{
                background: transparent;
                color: {color};
                font-family: "{FONT_FAMILY}";
                font-size: 17px;
                font-weight: 700;
                letter-spacing: 2px;
            }}
            """
        )

    def standby(
        self,
        message: str | None = None,
    ) -> None:
        self.set_ai_state(
            "standby",
            message,
        )

    def activated(
        self,
        message: str | None = None,
    ) -> None:
        self.set_ai_state(
            "activated",
            message,
        )

    def listening(
        self,
        message: str | None = None,
    ) -> None:
        self.set_ai_state(
            "listening",
            message,
        )

    def thinking(
        self,
        message: str | None = None,
    ) -> None:
        self.set_ai_state(
            "thinking",
            message,
        )

    def speaking(
        self,
        message: str | None = None,
    ) -> None:
        self.set_ai_state(
            "speaking",
            message,
        )

    def sleeping(
        self,
        message: str | None = None,
    ) -> None:
        self.set_ai_state(
            "sleeping",
            message,
        )

    def error(
        self,
        message: str | None = None,
    ) -> None:
        self.set_ai_state(
            "error",
            message,
        )

    # =====================================================
    # ERROR HANDLING
    # =====================================================

    def _handle_monitor_error(
        self,
        message: str,
    ) -> None:
        self.footer_dot.set_color(ERROR)

        self.footer_label.setText(
            "MONITOR CONNECTION ERROR"
        )

        self.monitor_error.emit(message)

    # =====================================================
    # CLEANUP
    # =====================================================

    def closeEvent(self, event) -> None:
        self.stop_monitoring()
        self.clock_timer.stop()

        super().closeEvent(event)


# =========================================================
# STANDALONE TEST WINDOW
# =========================================================

if __name__ == "__main__":
    import sys

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QWidget,
    )

    from gui.theme import GLOBAL_STYLESHEET

    app = QApplication(sys.argv)
    app.setStyleSheet(
        GLOBAL_STYLESHEET
    )

    window = QWidget()

    window.setWindowTitle(
        "REYES HUD Panel Test"
    )

    window.resize(
        420,
        850,
    )

    window.setStyleSheet(
        f"""
        QWidget {{
            background-color: {BACKGROUND};
        }}
        """
    )

    layout = QHBoxLayout(window)

    layout.setContentsMargins(
        40,
        30,
        40,
        30,
    )

    panel = HudPanel()

    layout.addWidget(
        panel,
        alignment=Qt.AlignmentFlag.AlignCenter,
    )

    window.show()

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

        state = states[state_index]

        panel.set_ai_state(state)

        print(
            "HUD state:",
            state,
        )

        state_index = (
            state_index + 1
        ) % len(states)

    state_timer = QTimer()
    state_timer.timeout.connect(
        cycle_state
    )
    state_timer.start(3000)

    sys.exit(app.exec())