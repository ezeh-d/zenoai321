from __future__ import annotations

from enum import Enum


class DeviceType(str, Enum):
    WINDOWS_PC = "WINDOWS_PC"
    ANDROID = "ANDROID"
    WEB_COMPANION = "WEB_COMPANION"
    REMOTE_MACHINE = "REMOTE_MACHINE"


class Capability(str, Enum):
    OBSERVE_SCREEN = "OBSERVE_SCREEN"
    ACCESSIBILITY = "ACCESSIBILITY"
    GUI_INPUT = "GUI_INPUT"
    NATIVE_APP_CONTROL = "NATIVE_APP_CONTROL"
    FILESYSTEM = "FILESYSTEM"
    SHELL = "SHELL"
    BROWSER = "BROWSER"
