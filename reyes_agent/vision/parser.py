"""Screen parsing. Windows UI Automation first, OCR second, OmniParser optional.

WHY UIA IS THE DEFAULT AND NOT A FALLBACK
-----------------------------------------
OmniParser infers controls from pixels with YOLO + Florence-2: ~2GB of
weights, torch, and realistically a GPU. Neither torch nor a GPU is present
on this machine, and CPU inference is seconds per frame -- which the brief
rules out for causing lag.

UI Automation reads the SAME information out of the accessibility tree that
the application already publishes: exact control type, exact label, exact
rectangle, enabled/offscreen state. For native Windows apps that is ground
truth rather than a guess, and it needs no model at all.

THE PERFORMANCE TRAP (measured)
-------------------------------
Naive UIA is unusable. Walking the desktop root's children took **30.75s**,
because every property read is a separate cross-process COM call.

The fix is a cache request: ask for every property you want up front, scoped
to ONE window, and UIA returns the whole subtree in a single hop. Same
machine, same window: **0.22s** -- 140x faster. Every read below therefore
goes through `Cached*` properties; touching a `Current*` property inside the
loop would silently reintroduce the 30-second behaviour.
"""

from __future__ import annotations

import ctypes
import threading
import time

from reyes_agent.vision.elements import OCR, OMNIPARSER, UIA, Element, Scene, classify

# A window with thousands of elements (a big Electron app) would make the
# scan slow and the summary useless. Cap and say so.
MAX_ELEMENTS = 400
SCAN_TIMEOUT_S = 8.0

_lock = threading.Lock()
_automation = None
_uia_module = None


def _uia():
    """Lazily create the COM automation object. Created ONCE per process."""
    global _automation, _uia_module
    with _lock:
        if _automation is not None:
            return _automation, _uia_module
        import comtypes.client as cc

        cc.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as module

        _automation = cc.CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
        _uia_module = module
        return _automation, _uia_module


def foreground_handle() -> int:
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:  # noqa: BLE001
        return 0


def _window_title(handle: int) -> str:
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(handle)
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(handle, buffer, length + 1)
        return buffer.value
    except Exception:  # noqa: BLE001
        return ""


def parse_uia(handle: int = 0, *, max_elements: int = MAX_ELEMENTS) -> Scene:
    """One cached subtree scan of a single window."""
    started = time.time()
    handle = handle or foreground_handle()
    scene = Scene(window=_window_title(handle), window_handle=handle, source=UIA)
    if not handle:
        scene.error = "no foreground window"
        return scene

    try:
        automation, uia = _uia()
        window = automation.ElementFromHandle(handle)

        # ONE cross-process hop for every property, for the whole subtree.
        request = automation.CreateCacheRequest()
        for prop in (uia.UIA_NamePropertyId, uia.UIA_ControlTypePropertyId,
                     uia.UIA_BoundingRectanglePropertyId, uia.UIA_IsEnabledPropertyId,
                     uia.UIA_IsOffscreenPropertyId, uia.UIA_AutomationIdPropertyId):
            request.AddProperty(prop)
        request.TreeScope = uia.TreeScope_Subtree
        condition = automation.CreatePropertyCondition(uia.UIA_IsControlElementPropertyId, True)
        found = window.FindAllBuildCache(uia.TreeScope_Subtree, condition, request)
    except Exception as exc:  # noqa: BLE001 -- a COM failure must not crash ZENO
        scene.error = f"{type(exc).__name__}: {exc}"
        scene.duration_ms = int((time.time() - started) * 1000)
        return scene

    total = found.Length
    scene.truncated = total > max_elements
    for index in range(min(total, max_elements)):
        if time.time() - started > SCAN_TIMEOUT_S:
            scene.truncated = True
            break
        try:
            raw = found.GetElement(index)
            # Cached reads only -- see the module docstring.
            if raw.CachedIsOffscreen:
                continue
            rect = raw.CachedBoundingRectangle
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 0 or height <= 0:
                continue          # zero-size elements cannot be clicked or read
            kind, interactive = classify(raw.CachedControlType)
            scene.elements.append(Element(
                type=kind, label=(raw.CachedName or "")[:160],
                position=(int(rect.left), int(rect.top), width, height),
                interactive=interactive, confidence=1.0, source=UIA,
                enabled=bool(raw.CachedIsEnabled),
                automation_id=(raw.CachedAutomationId or "")[:64]))
        except Exception:  # noqa: BLE001 -- one bad element never fails the scan
            continue

    scene.parsed_at = time.time()
    scene.duration_ms = int((scene.parsed_at - started) * 1000)
    return scene


def parse_ocr(handle: int = 0) -> Scene:
    """Fallback for surfaces with no accessibility tree (canvas, remote desktop).

    Produces text elements only -- OCR cannot tell a button from a label, so
    nothing here is marked interactive and confidence is below UIA's.
    """
    started = time.time()
    handle = handle or foreground_handle()
    scene = Scene(window=_window_title(handle), window_handle=handle, source=OCR)
    try:
        from reyes_agent import ocr as ocr_module
        from reyes_agent.vision import screen_capture

        shot = screen_capture.capture(handle)
        if shot is None:
            scene.error = "screen capture failed"
            return scene
        text = ocr_module.read_image(str(shot)) if hasattr(ocr_module, "read_image") else ""
        for line in [t.strip() for t in str(text).splitlines() if t.strip()][:MAX_ELEMENTS]:
            scene.elements.append(Element(type="text", label=line[:160], interactive=False,
                                          confidence=0.6, source=OCR))
    except Exception as exc:  # noqa: BLE001
        scene.error = f"{type(exc).__name__}: {exc}"
    scene.parsed_at = time.time()
    scene.duration_ms = int((scene.parsed_at - started) * 1000)
    return scene


def parse_omniparser(handle: int = 0) -> Scene:
    """Adapter seam. Deliberately not implemented against absent hardware.

    Returns an honest error rather than a silent empty scene, so enabling the
    flag without the dependencies tells you exactly what is missing instead
    of looking like a screen with nothing on it.
    """
    scene = Scene(window=_window_title(handle or foreground_handle()), source=OMNIPARSER)
    from reyes_agent import integrations

    if not integrations.available("torch"):
        scene.error = ("OmniParser needs torch + transformers and a GPU to be usable; "
                       "neither is installed here. Windows UI Automation is serving this "
                       "role and returns the same schema in ~0.2s.")
        return scene
    scene.error = ("OmniParser weights are not wired up in this build. "
                   "Set ZENO_OMNIPARSER_ENABLED=0 to silence this.")
    return scene


def parse(handle: int = 0, *, prefer: str = "") -> Scene:
    """Parse the screen using the best backend that actually works.

    Order: OmniParser only when explicitly enabled AND installed, then UIA,
    then OCR when UIA produced nothing usable.
    """
    from reyes_agent import integrations

    if (prefer == OMNIPARSER or integrations.OMNIPARSER_ENABLED) and prefer != UIA:
        scene = parse_omniparser(handle)
        if scene.elements:
            return scene
        # fall through to UIA rather than returning an empty screen

    if prefer != OCR:
        scene = parse_uia(handle)
        if scene.elements or scene.error:
            # An error here is still informative; only a genuinely empty,
            # error-free scan justifies paying for OCR.
            if scene.elements or scene.error:
                return scene

    return parse_ocr(handle)
