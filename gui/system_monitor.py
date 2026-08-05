# gui/system_monitor.py

from __future__ import annotations

import os
import platform
import socket
import time
from dataclasses import dataclass

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from gui.theme import SYSTEM_UPDATE_INTERVAL_MS


# =========================================================
# SYSTEM DATA MODEL
# =========================================================

@dataclass
class SystemSnapshot:
    """
    Current device information collected by SystemMonitor.
    """

    cpu_percent: float
    cpu_frequency_mhz: float

    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float

    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float

    battery_percent: float | None
    battery_plugged: bool | None
    battery_seconds_left: int | None

    network_sent_mb: float
    network_received_mb: float
    upload_speed_kbps: float
    download_speed_kbps: float

    process_count: int
    boot_time: float
    uptime_seconds: int

    hostname: str
    operating_system: str
    processor: str
    python_version: str


# =========================================================
# SYSTEM MONITOR
# =========================================================

class SystemMonitor(QObject):
    """
    Collects live Windows system information.

    Signals:
        snapshot_updated(SystemSnapshot)
        monitor_error(str)

    Usage:

        self.monitor = SystemMonitor()
        self.monitor.snapshot_updated.connect(
            self.update_system_panel
        )
        self.monitor.start()
    """

    snapshot_updated = Signal(object)
    monitor_error = Signal(str)

    def __init__(
        self,
        update_interval_ms: int = SYSTEM_UPDATE_INTERVAL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self.update_interval_ms = max(
            250,
            int(update_interval_ms),
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(
            self.collect_snapshot
        )

        self.running = False

        self._previous_network = psutil.net_io_counters()
        self._previous_network_time = time.monotonic()

        # Initialize CPU measurement.
        psutil.cpu_percent(interval=None)

    # =====================================================
    # START AND STOP
    # =====================================================

    def start(self) -> None:
        """
        Start collecting system information.
        """

        if self.running:
            return

        self.running = True

        self._previous_network = psutil.net_io_counters()
        self._previous_network_time = time.monotonic()

        self.collect_snapshot()
        self.timer.start(self.update_interval_ms)

    def stop(self) -> None:
        """
        Stop collecting system information.
        """

        if not self.running:
            return

        self.running = False
        self.timer.stop()

    def set_update_interval(
        self,
        interval_ms: int,
    ) -> None:
        """
        Change the monitor update interval.
        """

        self.update_interval_ms = max(
            250,
            int(interval_ms),
        )

        if self.running:
            self.timer.start(
                self.update_interval_ms
            )

    # =====================================================
    # DATA COLLECTION
    # =====================================================

    def collect_snapshot(self) -> None:
        """
        Collect and publish a complete system snapshot.
        """

        try:
            cpu_percent = psutil.cpu_percent(
                interval=None
            )

            cpu_frequency = psutil.cpu_freq()

            if cpu_frequency is None:
                cpu_frequency_mhz = 0.0
            else:
                cpu_frequency_mhz = float(
                    cpu_frequency.current
                )

            memory = psutil.virtual_memory()

            memory_used_gb = self._bytes_to_gb(
                memory.used
            )
            memory_total_gb = self._bytes_to_gb(
                memory.total
            )

            disk = self._get_disk_usage()

            battery = self._get_battery_information()

            network = self._get_network_information()

            boot_time = float(
                psutil.boot_time()
            )

            uptime_seconds = max(
                0,
                int(time.time() - boot_time),
            )

            snapshot = SystemSnapshot(
                cpu_percent=float(cpu_percent),
                cpu_frequency_mhz=cpu_frequency_mhz,

                memory_percent=float(memory.percent),
                memory_used_gb=memory_used_gb,
                memory_total_gb=memory_total_gb,

                disk_percent=float(disk.percent),
                disk_used_gb=self._bytes_to_gb(
                    disk.used
                ),
                disk_total_gb=self._bytes_to_gb(
                    disk.total
                ),

                battery_percent=battery["percent"],
                battery_plugged=battery["plugged"],
                battery_seconds_left=battery[
                    "seconds_left"
                ],

                network_sent_mb=network["sent_mb"],
                network_received_mb=network[
                    "received_mb"
                ],
                upload_speed_kbps=network[
                    "upload_kbps"
                ],
                download_speed_kbps=network[
                    "download_kbps"
                ],

                process_count=len(
                    psutil.pids()
                ),
                boot_time=boot_time,
                uptime_seconds=uptime_seconds,

                hostname=socket.gethostname(),
                operating_system=self._get_os_name(),
                processor=self._get_processor_name(),
                python_version=platform.python_version(),
            )

            self.snapshot_updated.emit(snapshot)

        except Exception as error:
            self.monitor_error.emit(
                f"System monitor error: {error}"
            )

    # =====================================================
    # DISK
    # =====================================================

    @staticmethod
    def _get_disk_usage():
        """
        Return usage for the primary system drive.
        """

        if os.name == "nt":
            drive = os.environ.get(
                "SystemDrive",
                "C:",
            )

            path = f"{drive}\\"
        else:
            path = "/"

        return psutil.disk_usage(path)

    # =====================================================
    # BATTERY
    # =====================================================

    @staticmethod
    def _get_battery_information() -> dict:
        """
        Return battery information when available.
        """

        battery = psutil.sensors_battery()

        if battery is None:
            return {
                "percent": None,
                "plugged": None,
                "seconds_left": None,
            }

        seconds_left: int | None

        if battery.secsleft in {
            psutil.POWER_TIME_UNKNOWN,
            psutil.POWER_TIME_UNLIMITED,
        }:
            seconds_left = None
        else:
            seconds_left = max(
                0,
                int(battery.secsleft),
            )

        return {
            "percent": float(battery.percent),
            "plugged": bool(
                battery.power_plugged
            ),
            "seconds_left": seconds_left,
        }

    # =====================================================
    # NETWORK
    # =====================================================

    def _get_network_information(
        self,
    ) -> dict:
        """
        Calculate total network usage and current speeds.
        """

        current_network = psutil.net_io_counters()
        current_time = time.monotonic()

        elapsed = max(
            0.001,
            current_time - self._previous_network_time,
        )

        sent_difference = max(
            0,
            current_network.bytes_sent
            - self._previous_network.bytes_sent,
        )

        received_difference = max(
            0,
            current_network.bytes_recv
            - self._previous_network.bytes_recv,
        )

        upload_speed_kbps = (
            sent_difference / 1024.0 / elapsed
        )

        download_speed_kbps = (
            received_difference / 1024.0 / elapsed
        )

        self._previous_network = current_network
        self._previous_network_time = current_time

        return {
            "sent_mb": self._bytes_to_mb(
                current_network.bytes_sent
            ),
            "received_mb": self._bytes_to_mb(
                current_network.bytes_recv
            ),
            "upload_kbps": upload_speed_kbps,
            "download_kbps": download_speed_kbps,
        }

    # =====================================================
    # DEVICE INFORMATION
    # =====================================================

    @staticmethod
    def _get_os_name() -> str:
        """
        Return a readable operating-system name.
        """

        system = platform.system()
        release = platform.release()
        version = platform.version()

        if system == "Windows":
            return f"Windows {release}"

        if release:
            return f"{system} {release}"

        return version or system or "Unknown"

    @staticmethod
    def _get_processor_name() -> str:
        """
        Return the processor name when available.
        """

        processor = platform.processor().strip()

        if processor:
            return processor

        machine = platform.machine().strip()

        if machine:
            return machine

        return "Unknown Processor"

    # =====================================================
    # FORMAT HELPERS
    # =====================================================

    @staticmethod
    def _bytes_to_gb(value: int | float) -> float:
        return float(value) / (
            1024.0 ** 3
        )

    @staticmethod
    def _bytes_to_mb(value: int | float) -> float:
        return float(value) / (
            1024.0 ** 2
        )

    @staticmethod
    def format_percentage(
        value: float,
    ) -> str:
        """
        Format percentage values for the HUD.
        """

        return f"{value:.0f}%"

    @staticmethod
    def format_gigabytes(
        value: float,
    ) -> str:
        """
        Format storage values for the HUD.
        """

        return f"{value:.1f} GB"

    @staticmethod
    def format_frequency(
        frequency_mhz: float,
    ) -> str:
        """
        Format CPU frequency as MHz or GHz.
        """

        if frequency_mhz <= 0:
            return "N/A"

        if frequency_mhz >= 1000:
            return (
                f"{frequency_mhz / 1000:.2f} GHz"
            )

        return f"{frequency_mhz:.0f} MHz"

    @staticmethod
    def format_network_speed(
        speed_kbps: float,
    ) -> str:
        """
        Format network speed.
        """

        if speed_kbps >= 1024:
            return (
                f"{speed_kbps / 1024:.2f} MB/s"
            )

        return f"{speed_kbps:.1f} KB/s"

    @staticmethod
    def format_uptime(
        uptime_seconds: int,
    ) -> str:
        """
        Convert uptime seconds into readable text.
        """

        days, remaining = divmod(
            uptime_seconds,
            86400,
        )

        hours, remaining = divmod(
            remaining,
            3600,
        )

        minutes, seconds = divmod(
            remaining,
            60,
        )

        if days > 0:
            return (
                f"{days}d {hours:02d}h "
                f"{minutes:02d}m"
            )

        if hours > 0:
            return (
                f"{hours:02d}h "
                f"{minutes:02d}m"
            )

        return (
            f"{minutes:02d}m "
            f"{seconds:02d}s"
        )

    @staticmethod
    def format_battery(
        percent: float | None,
        plugged: bool | None,
    ) -> str:
        """
        Format battery status.
        """

        if percent is None:
            return "DESKTOP POWER"

        status = (
            "CHARGING"
            if plugged
            else "BATTERY"
        )

        return (
            f"{percent:.0f}% {status}"
        )


# =========================================================
# STANDALONE TEST
# =========================================================

if __name__ == "__main__":
    import sys

    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)

    monitor = SystemMonitor(
        update_interval_ms=1000
    )

    def print_snapshot(
        snapshot: SystemSnapshot,
    ) -> None:
        print(
            "\n"
            "====================================\n"
            "REYES SYSTEM MONITOR\n"
            "===================================="
        )

        print(
            f"CPU: {snapshot.cpu_percent:.0f}% "
            f"({monitor.format_frequency(snapshot.cpu_frequency_mhz)})"
        )

        print(
            f"RAM: {snapshot.memory_percent:.0f}% "
            f"({snapshot.memory_used_gb:.1f} / "
            f"{snapshot.memory_total_gb:.1f} GB)"
        )

        print(
            f"DISK: {snapshot.disk_percent:.0f}% "
            f"({snapshot.disk_used_gb:.1f} / "
            f"{snapshot.disk_total_gb:.1f} GB)"
        )

        print(
            "BATTERY:",
            monitor.format_battery(
                snapshot.battery_percent,
                snapshot.battery_plugged,
            ),
        )

        print(
            "NETWORK:",
            f"↓ {monitor.format_network_speed(snapshot.download_speed_kbps)}",
            f"↑ {monitor.format_network_speed(snapshot.upload_speed_kbps)}",
        )

        print(
            f"PROCESSES: {snapshot.process_count}"
        )

        print(
            "UPTIME:",
            monitor.format_uptime(
                snapshot.uptime_seconds
            ),
        )

        print(
            f"HOSTNAME: {snapshot.hostname}"
        )

        print(
            f"OS: {snapshot.operating_system}"
        )

    monitor.snapshot_updated.connect(
        print_snapshot
    )

    monitor.monitor_error.connect(
        print
    )

    monitor.start()

    sys.exit(app.exec())