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

from reyes_agent.vision import coverage as coverage_check
from reyes_agent.vision.elements import (CONTROL_TYPES, INTERACTIVE, OCR, OMNIPARSER,
                                         READABLE, UIA, Element, Scene, classify)

# A window with thousands of elements (a big Electron app) would make the
# scan slow and the summary useless. Cap and say so.
MAX_ELEMENTS = 400
SCAN_TIMEOUT_S = 8.0

# Control types worth returning at all: things that can be acted on, plus
# things worth reading. Asking UIA for only these is what makes a big
# Electron window affordable -- see `_condition`.
_WANTED_TYPES = tuple(sorted(cid for cid, name in CONTROL_TYPES.items()
                             if name in (INTERACTIVE | READABLE)))

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


def _cached_value(raw, uia) -> str:
    """What a control contains, from the cache -- no extra cross-process hop.

    A control's Name is its label; a text box called "Search" is called
    "Search" whether it is empty or holds a sentence. Reading the Value
    pattern is what lets ZENO answer "what does that field say?" -- verified
    against Notepad, which returns the typed text here and nothing in Name.

    Controls with no Value pattern return empty, which is why this is read
    for every element rather than only for edits.
    """
    try:
        value = raw.GetCachedPropertyValue(uia.UIA_ValueValuePropertyId)
    except Exception:  # noqa: BLE001
        return ""
    if value is None or isinstance(value, bool) or not isinstance(value, str):
        return ""
    return value[:400]


def _condition(automation, uia):
    """What to ask UIA for -- and the difference between 3s and 38s.

    MEASURED on this machine, same windows, same cache request:

        query                       ChatGPT            Claude
        every control element       37.59s / 4300      12.14s / 1031
        + only wanted types          9.11s / 4068       2.55s /  933
        + only onscreen              2.82s /  378       1.32s /  132

    A long chat transcript publishes thousands of scrolled-out text nodes.
    The loop below discarded every one of them anyway -- offscreen elements
    cannot be clicked or read -- so it was paying 35 seconds to enumerate
    things it would throw away. Pushing both filters into the query is not
    an approximation; it returns the same elements, 13x sooner.

    Falls back to the broad condition if this UIA build lacks the composite
    condition APIs, because a slow scan beats no scan.
    """
    try:
        types = automation.CreateOrConditionFromArray(
            [automation.CreatePropertyCondition(uia.UIA_ControlTypePropertyId, cid)
             for cid in _WANTED_TYPES])
        onscreen = automation.CreatePropertyCondition(uia.UIA_IsOffscreenPropertyId, False)
        return automation.CreateAndCondition(types, onscreen)
    except Exception:  # noqa: BLE001
        return automation.CreatePropertyCondition(uia.UIA_IsControlElementPropertyId, True)


def parse_uia(handle: int = 0, *, max_elements: int = MAX_ELEMENTS) -> Scene:
    """One cached subtree scan of a single window."""
    started = time.time()
    handle = handle or foreground_handle()
    scene = Scene(window=_window_title(handle), window_handle=handle, source=UIA)
    if not handle:
        scene.error = "no foreground window"
        return scene

    # Ask the cheap question first. A minimized or shell-suspended window
    # renders nothing, and scanning one still costs a full cross-process
    # subtree walk (measured at 1.6s on a backgrounded app) to be told what
    # two flag reads answer instantly.
    early = coverage_check.assess(handle, 0, 0)
    if early.state in (coverage_check.MINIMIZED, coverage_check.SUSPENDED):
        scene.coverage = early
        scene.duration_ms = int((time.time() - started) * 1000)
        return scene

    try:
        automation, uia = _uia()
        window = automation.ElementFromHandle(handle)

        # ONE cross-process hop for every property, for the whole subtree.
        request = automation.CreateCacheRequest()
        for prop in (uia.UIA_NamePropertyId, uia.UIA_ControlTypePropertyId,
                     uia.UIA_BoundingRectanglePropertyId, uia.UIA_IsEnabledPropertyId,
                     uia.UIA_IsOffscreenPropertyId, uia.UIA_AutomationIdPropertyId,
                     uia.UIA_ValueValuePropertyId):
            request.AddProperty(prop)
        request.TreeScope = uia.TreeScope_Subtree
        found = window.FindAllBuildCache(uia.TreeScope_Subtree,
                                         _condition(automation, uia), request)
    except Exception as exc:  # noqa: BLE001 -- a COM failure must not crash ZENO
        scene.error = f"{type(exc).__name__}: {exc}"
        scene.duration_ms = int((time.time() - started) * 1000)
        return scene

    # How much of the budget the enumeration itself consumed. On a heavy
    # window this can be most of it, and the loop below must not then break
    # on its first iteration and report an empty window.
    enumerate_s = time.time() - started
    total = found.Length
    scene.truncated = total > max_elements
    for index in range(min(total, max_elements)):
        if time.time() - started > SCAN_TIMEOUT_S and scene.elements:
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
                automation_id=(raw.CachedAutomationId or "")[:64],
                value=_cached_value(raw, uia)))
        except Exception:  # noqa: BLE001 -- one bad element never fails the scan
            continue

    scene.parsed_at = time.time()
    scene.duration_ms = int((scene.parsed_at - started) * 1000)
    # A thin result is not the same as an empty window -- find out which.
    # `enumerate_s` matters: a window that took the whole budget just to
    # enumerate is SLOW, not opaque, and saying "it draws its own interface"
    # about an app that published 4300 elements would be plainly wrong.
    scene.coverage = coverage_check.assess(handle, len(scene.elements),
                                           len(scene.interactive),
                                           enumerate_s=enumerate_s,
                                           reported_total=total)
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
        if scene.error:
            return scene          # an error is still informative
        if scene.elements and scene.reliable:
            return scene

        # Thin result. OCR is only worth paying for when the window IS drawing
        # something we failed to read. A minimized or suspended window has
        # nothing on screen to read either, so OCR would burn a capture and a
        # model call to confirm the same emptiness -- return the diagnosis and
        # its remedy instead.
        if scene.coverage is not None and not scene.coverage.worth_ocr:
            return scene

        text_scene = parse_ocr(handle)
        if text_scene.elements:
            text_scene.coverage = scene.coverage      # keep WHY we fell back
            return text_scene
        return scene

    return parse_ocr(handle)
