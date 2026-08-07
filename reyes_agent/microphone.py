"""Microphone diagnosis: tell the user WHICH thing is wrong, precisely.

WHY THIS EXISTS
---------------
The panel previously mapped every capture failure onto one of two
sentences -- "permission is blocked in Windows or this ZENO profile" or
"unavailable: <raw error>". Those cover at least six genuinely different
faults with different fixes, and the first one names two unrelated causes
in a single sentence, so the user cannot tell which applies.

This module distinguishes them using evidence:
  * Windows privacy policy      -> read from the registry (READ ONLY)
  * no capture device present   -> device enumeration
  * device present but disabled -> device state
  * device busy                 -> the browser's NotReadableError
  * permission denied           -> the browser's NotAllowedError
  * STT/transport failure       -> provider configuration check

NOTHING HERE CHANGES A WINDOWS SETTING. Privacy keys are read to explain
what to switch on; flipping them is the user's decision in the Settings
app, and silently editing privacy policy would be exactly the wrong
behaviour for a microphone permission problem. The module returns the
precise place to go instead.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Where Windows records microphone consent. Read-only use.
_CONSENT_ROOT = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"

# Stable states for the browser/API diagnostic boundary.  User-facing wording
# can change without making a support report ambiguous.
MIC_PERMISSION_DENIED = "MIC_PERMISSION_DENIED"
MIC_PERMISSION_NOT_REQUESTED = "MIC_PERMISSION_NOT_REQUESTED"
WEBVIEW2_PERMISSION_DENIED = "WEBVIEW2_PERMISSION_DENIED"
WINDOWS_PERMISSION_DENIED = "WINDOWS_PERMISSION_DENIED"
NO_MICROPHONE_FOUND = "NO_MICROPHONE_FOUND"
MICROPHONE_DISABLED = "MICROPHONE_DISABLED"
MICROPHONE_BUSY = "MICROPHONE_BUSY"
DEVICE_INITIALIZATION_FAILED = "DEVICE_INITIALIZATION_FAILED"
AUDIO_CAPTURE_FAILED = "AUDIO_CAPTURE_FAILED"
STT_FAILED = "STT_FAILED"
WAKE_WORD_FAILED = "WAKE_WORD_FAILED"
BACKEND_CONNECTION_FAILED = "BACKEND_CONNECTION_FAILED"
MICROPHONE_READY = "MICROPHONE_READY"

_KNOWN_STATUSES = {
    MIC_PERMISSION_DENIED, MIC_PERMISSION_NOT_REQUESTED, WEBVIEW2_PERMISSION_DENIED,
    WINDOWS_PERMISSION_DENIED, NO_MICROPHONE_FOUND, MICROPHONE_DISABLED,
    MICROPHONE_BUSY, DEVICE_INITIALIZATION_FAILED, AUDIO_CAPTURE_FAILED, STT_FAILED,
    WAKE_WORD_FAILED, BACKEND_CONNECTION_FAILED, MICROPHONE_READY,
}
_runtime_lock = threading.Lock()
_runtime: dict[str, Any] = {
    "status": "", "detail": "", "source": "", "updated_at": 0.0,
    "audio_received": False, "device_id": "",
}

# Browser DOMException name -> (cause id, what it actually means, what to do)
_BROWSER_ERRORS: dict[str, tuple[str, str, str]] = {
    "NotAllowedError": (
        "permission_denied",
        "The microphone prompt was denied, or Windows/WebView2 policy is blocking it.",
        "Windows Settings > Privacy & security > Microphone: turn on 'Microphone access' "
        "and 'Let desktop apps access your microphone'. Then reopen ZENO.",
    ),
    "NotFoundError": (
        "no_device",
        "No capture device was offered to the app at all.",
        "Plug in or enable a microphone, then reopen ZENO.",
    ),
    "NotReadableError": (
        "device_busy_or_driver",
        "The device exists and is permitted, but could not be opened -- normally another "
        "app holds it exclusively, or the audio driver failed.",
        "Close other apps using the mic (Teams, Zoom, Discord, Slack huddle, OBS), or "
        "restart Windows Audio, then try again.",
    ),
    "OverconstrainedError": (
        "constraints_unsupported",
        "The device cannot satisfy the requested audio processing constraints.",
        "ZENO retries without the optional constraints; if that fails, pick a different "
        "input device in Windows sound settings.",
    ),
    "SecurityError": (
        "insecure_context",
        "The page is not in a secure context, so capture is refused.",
        "Open ZENO from the desktop app or http://127.0.0.1:8765 (loopback counts as secure).",
    ),
    "AbortError": (
        "hardware_abort",
        "The OS aborted the capture request, usually a transient driver fault.",
        "Try again; if it repeats, restart the Windows Audio service.",
    ),
    "AudioCaptureError": (
        AUDIO_CAPTURE_FAILED,
        "The microphone stream stopped unexpectedly after it had opened.",
        "ZENO will retry safely. If it keeps happening, reconnect or reselect the microphone.",
    ),
}


@dataclass
class MicReport:
    ok: bool = False
    cause: str = ""              # stable id for the UI
    summary: str = ""            # one line for the user
    fix: str = ""                # exactly what to do
    details: dict[str, Any] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "status": self.cause, "cause": self.cause, "summary": self.summary,
                "fix": self.fix, "details": self.details, "checks": self.checks}


def report_runtime(status: str, *, detail: str = "", source: str = "", audio_received: bool = False,
                   device_id: str = "") -> dict[str, Any]:
    """Record observed browser capture evidence without retaining audio."""
    if status not in _KNOWN_STATUSES:
        raise ValueError(f"unknown microphone status: {status}")
    snapshot = {
        "status": status, "detail": str(detail)[:300], "source": str(source)[:40],
        "updated_at": time.time(), "audio_received": bool(audio_received),
        "device_id": str(device_id)[:256],
    }
    with _runtime_lock:
        _runtime.update(snapshot)
        return dict(_runtime)


def runtime_status() -> dict[str, Any]:
    with _runtime_lock:
        return dict(_runtime)


def _read_windows_consent() -> dict[str, Any]:
    """Read (never write) the Windows microphone consent policy."""
    out: dict[str, Any] = {"readable": False}
    if sys.platform != "win32":
        return out
    try:
        import winreg
    except ImportError:
        return out

    for hive, label in ((winreg.HKEY_CURRENT_USER, "user"),
                        (winreg.HKEY_LOCAL_MACHINE, "machine")):
        try:
            with winreg.OpenKey(hive, _CONSENT_ROOT) as key:
                value, _ = winreg.QueryValueEx(key, "Value")
                out[f"{label}_global"] = value      # "Allow" / "Deny"
                out["readable"] = True
        except OSError:
            continue

    # Desktop apps (which is what WebView2 is) sit under NonPackaged.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CONSENT_ROOT + r"\NonPackaged") as key:
            value, _ = winreg.QueryValueEx(key, "Value")
            out["desktop_apps"] = value
            out["readable"] = True
    except OSError:
        pass
    return out


def _enumerate_devices() -> dict[str, Any]:
    """Real input devices, via sounddevice if present (already a dependency
    of the voice CLI paths)."""
    info: dict[str, Any] = {"available": False, "inputs": [], "default": None}
    try:
        import sounddevice as sd
    except Exception:  # noqa: BLE001
        return info
    try:
        devices = sd.query_devices()
        inputs = [d["name"] for d in devices if d.get("max_input_channels", 0) > 0]
        info["available"] = True
        info["inputs"] = inputs[:8]
        info["input_count"] = len(inputs)
        try:
            default = sd.query_devices(kind="input")
            info["default"] = default.get("name")
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _stt_configured() -> dict[str, Any]:
    from reyes_agent import config

    return {
        "deepgram_key": bool(config.DEEPGRAM_API_KEY),
        "model": config.DEEPGRAM_MODEL,
    }


def diagnose(browser_error: str = "", permission_state: str = "", selected_device: str = "") -> MicReport:
    """Full diagnosis. `browser_error` is the DOMException name the panel
    saw, when there was one -- it is the strongest single signal."""
    rep = MicReport()
    permission_state = str(permission_state or "").strip().lower()
    consent = _read_windows_consent()
    devices = _enumerate_devices()
    stt = _stt_configured()
    rep.details = {"windows_consent": consent, "devices": devices, "stt": stt}

    # 1. Windows policy -- decisive when it says Deny, whatever else is true.
    denied_globally = consent.get("user_global") == "Deny" or consent.get("machine_global") == "Deny"
    denied_desktop = consent.get("desktop_apps") == "Deny"
    if denied_globally or denied_desktop:
        which = "Microphone access" if denied_globally else "Let desktop apps access your microphone"
        rep.cause = WINDOWS_PERMISSION_DENIED
        rep.summary = f"Windows is blocking microphone access — '{which}' is set to Deny."
        rep.fix = ("Open Windows Settings > Privacy & security > Microphone and turn on "
                   f"'{which}'. ZENO cannot change this for you, and shouldn't — it's a "
                   "system privacy control. Reopen ZENO afterwards.")
        rep.checks.append("windows consent: DENY")
        return rep
    if consent.get("readable"):
        rep.checks.append("windows consent: allowed")
    else:
        rep.checks.append("windows consent: not readable (assuming allowed)")

    # 2. No device at all.
    if devices.get("available") and devices.get("input_count", 0) == 0:
        rep.cause = NO_MICROPHONE_FOUND
        rep.summary = "No microphone is connected or enabled on this machine."
        rep.fix = ("Plug in a microphone, or enable the built-in one in Windows Settings > "
                   "System > Sound > Input. Then reopen ZENO.")
        rep.checks.append("devices: none found")
        return rep
    if devices.get("input_count"):
        rep.checks.append(f"devices: {devices['input_count']} input(s), default "
                          f"'{devices.get('default') or 'unknown'}'")

    # 3. An unasked browser grant is neither a device failure nor a denial.
    if permission_state == "prompt" and not browser_error:
        rep.cause = MIC_PERMISSION_NOT_REQUESTED
        rep.summary = "Microphone access has not been approved for ZENO yet."
        rep.fix = "Select Enable microphone once, then choose Allow in the ZENO microphone prompt."
        rep.checks.append("browser permission: prompt")
        return rep

    # 4. Whatever the browser actually reported.
    if browser_error:
        cause, meaning, fix = _BROWSER_ERRORS.get(
            browser_error,
            (DEVICE_INITIALIZATION_FAILED, f"The browser reported {browser_error}.",
             "Use Enable microphone to retry. If it persists, check Windows sound settings."))
        rep.cause = cause
        rep.summary = meaning
        rep.fix = fix
        rep.checks.append(f"browser: {browser_error}")
        # A NotAllowedError only proves that this one capture attempt was
        # refused. WebView2 can use it for a gesture, policy, or capture
        # failure too; an explicit Permissions-API `denied` state is needed
        # before we claim that the saved profile refused the microphone.
        if cause == "permission_denied" and consent.get("readable") and not denied_globally:
            if permission_state == "denied":
                rep.cause = WEBVIEW2_PERMISSION_DENIED
                rep.summary = "WebView2 currently reports microphone permission as denied for ZENO."
                rep.fix = ("Select Enable microphone once and choose Allow if WebView2 presents its one-time prompt. "
                           "ZENO keeps the same profile and fixed local origin, so an allowed grant persists. "
                           "Do not delete the profile.")
                rep.checks.append("browser permission: denied")
            elif permission_state == "granted":
                rep.cause = DEVICE_INITIALIZATION_FAILED
                rep.summary = "WebView2 reports the microphone grant, but this capture attempt was still refused."
                rep.fix = ("Use Test microphone once. If it repeats, refresh the selected device or check whether another "
                           "app is holding the microphone; this is not evidence that the saved WebView2 permission was revoked.")
                rep.checks.append("browser permission: granted (conflicts with capture error)")
            else:
                rep.cause = MIC_PERMISSION_DENIED
                rep.summary = "WebView2 refused this microphone request; its saved permission state could not be confirmed."
                rep.fix = ("Select Enable microphone once to retry from an explicit ZENO action. If WebView2 then reports "
                           "permission denied, ZENO will show that exact state. Do not delete the profile.")
        elif cause == "permission_denied":
            rep.cause = MIC_PERMISSION_DENIED
        elif cause == "no_device" and selected_device:
            rep.cause = MICROPHONE_DISABLED
            rep.summary = "The selected microphone is disconnected or disabled."
            rep.fix = "Refresh devices, choose an available microphone, then select Enable microphone."
        elif cause == "no_device":
            rep.cause = NO_MICROPHONE_FOUND
        elif cause == "device_busy_or_driver":
            rep.cause = MICROPHONE_BUSY
        elif cause in {"constraints_unsupported", "hardware_abort", "insecure_context"}:
            rep.cause = DEVICE_INITIALIZATION_FAILED
        return rep

    # 5. Preserve an observed browser failure rather than overwriting it with
    # a generic system-level "looks fine" report.
    runtime = runtime_status()
    if runtime["status"] and runtime["status"] != MICROPHONE_READY:
        rep.cause = runtime["status"]
        rep.summary = runtime["detail"] or runtime["status"].replace("_", " ").title()
        rep.fix = "Select Enable microphone to run a safe retry."
        rep.checks.append(f"runtime: {runtime['status']}")
        return rep

    # 6. Nothing wrong that we can see.
    if not stt["deepgram_key"]:
        rep.cause = STT_FAILED
        rep.summary = ("Microphone access looks fine, but speech-to-text has no Deepgram "
                       "key, so audio cannot be transcribed.")
        rep.fix = "Add DEEPGRAM_API_KEY to .env and restart ZENO."
        rep.checks.append("stt: no key")
        return rep

    rep.ok = True
    rep.cause = MICROPHONE_READY
    rep.summary = ("Microphone access and speech-to-text look correctly configured."
                   if runtime["audio_received"] else
                   "Microphone device and permissions look ready; select Test microphone to confirm live audio.")
    rep.fix = ""
    rep.checks.append("stt: configured")
    return rep
