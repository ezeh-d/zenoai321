"""Agent-facing browser tools, executed only by the Playwright owner worker."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from reyes_agent import browser_controller as bc
from reyes_agent.browser_runtime import get_browser_runtime
from reyes_agent.tools import register


T = TypeVar("T")


def _run(name: str, action: Callable[[], T], *, timeout: float = 50.0) -> T:
    # Browser infrastructure is explicitly Stage 3: constructing its worker
    # is cheap, but Chromium remains completely untouched until this first
    # actual browser request.
    try:
        from reyes_agent.kernel import get_kernel

        get_kernel().start_lazy("browser-runtime")
    except KeyError:
        # CLI/front-door use before the web kernel is booted keeps the
        # existing lazy behaviour instead of creating a second controller.
        pass
    return get_browser_runtime().run(name, action, timeout=timeout)


def _err(exc: Exception) -> str:
    # This runs inside the browser owner worker when a Playwright call fails.
    bc.invalidate_if_unhealthy(exc)
    return f"Browser error: {type(exc).__name__}: {exc}"


@register(name="browser_open", description="Open a URL in ZENO's persistent automated Chromium browser.",
          input_schema={"type": "object", "properties": {"url": {"type": "string", "description": "Full URL including https://."}}, "required": ["url"]})
def browser_open(url: str) -> str:
    def action() -> str:
        try:
            page = bc.get_page()
            page.goto(url, timeout=bc.action_timeout_ms(45_000), wait_until="domcontentloaded")
            return (f"Opened {page.url}; postcondition verified: the browser reports "
                    f"title '{page.title()}'.")
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_open", action)


@register(name="browser_read", description="Read visible text from ZENO's current browser page.",
          input_schema={"type": "object", "properties": {"selector": {"type": "string"}, "max_chars": {"type": "integer"}}})
def browser_read(selector: str = "", max_chars: int = 4000) -> str:
    def action() -> str:
        try:
            page = bc.get_page()
            if selector.strip():
                element = page.locator(selector).first
                if element.count() == 0:
                    return f"No element matches '{selector}'."
                text = element.inner_text(timeout=bc.action_timeout_ms(15_000))
            else:
                text = page.inner_text("body", timeout=bc.action_timeout_ms(15_000))
            cap = max(200, min(20_000, int(max_chars or 4000)))
            text = " ".join(text.split())
            return text[:cap] if text else "The page has no readable text."
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_read", action, timeout=20.0)


@register(name="browser_click", description="Click visible text or a CSS selector on the current browser page.",
          input_schema={"type": "object", "properties": {"text": {"type": "string"}, "selector": {"type": "string"}}})
def browser_click(text: str = "", selector: str = "") -> str:
    def action() -> str:
        try:
            page = bc.get_page()
            timeout = bc.action_timeout_ms(15_000)
            before_url, before_title = page.url, page.title()
            try:
                before_text = page.inner_text("body", timeout=timeout)[:20_000]
            except Exception:  # noqa: BLE001
                before_text = ""
            if text.strip():
                page.get_by_text(text.strip(), exact=False).first.click(timeout=timeout)
            elif selector.strip():
                page.click(selector, timeout=timeout)
            else:
                return "Give either text or selector."
            page.wait_for_load_state("domcontentloaded", timeout=timeout)
            page.wait_for_timeout(250)
            try:
                after_text = page.inner_text("body", timeout=timeout)[:20_000]
            except Exception:  # noqa: BLE001
                after_text = before_text
            if page.url != before_url or page.title() != before_title or after_text != before_text:
                return (f"Clicked '{text or selector}'; postcondition verified: "
                        f"the page state changed and is now at {page.url}.")
            return (f"Click was sent to '{text or selector}', but no URL, title, or visible-text "
                    "change was observed; the effect is unverified.")
        except Exception as exc:  # noqa: BLE001
            return _err(exc) + " -- try browser_vision_click if there is no stable text or selector."
    return _run("browser_click", action, timeout=20.0)


@register(name="browser_fill", description="Fill a labelled or CSS-selected browser form field (never credentials).",
          input_schema={"type": "object", "properties": {"selector": {"type": "string"}, "value": {"type": "string"}, "label": {"type": "string"}}, "required": ["value"]})
def browser_fill(value: str, selector: str = "", label: str = "") -> str:
    def action() -> str:
        try:
            page = bc.get_page()
            timeout = bc.action_timeout_ms(15_000)
            if label.strip():
                field = page.get_by_label(label.strip(), exact=False).first
                field.fill(value, timeout=timeout)
                observed = field.input_value(timeout=timeout)
                target = label
            elif selector.strip():
                field = page.locator(selector).first
                field.fill(value, timeout=timeout)
                observed = field.input_value(timeout=timeout)
                target = selector
            else:
                return "Give either selector or label."
            if observed != value:
                return f"Failed to verify field '{target}': the read-back value did not match."
            return f"Filled '{target}'; postcondition verified by field value read-back."
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_fill", action, timeout=20.0)


@register(name="browser_extract", description="Extract visible text or one attribute from all matches of a CSS selector.",
          input_schema={"type": "object", "properties": {"selector": {"type": "string"}, "attribute": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["selector"]})
def browser_extract(selector: str, attribute: str = "", limit: int = 30) -> str:
    def action() -> str:
        try:
            page = bc.get_page()
            elements = page.query_selector_all(selector)
            if not elements:
                return f"Nothing matches '{selector}'."
            rows: list[str] = []
            for element in elements[:max(1, min(200, int(limit or 30)))]:
                value = element.get_attribute(attribute) if attribute.strip() else element.inner_text()
                value = " ".join((value or "").split())
                if value:
                    rows.append(value)
            return f"{len(rows)} result(s):\n" + "\n".join(f"- {row}" for row in rows) if rows else "Matched elements were empty."
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_extract", action, timeout=25.0)


@register(name="browser_scroll", description="Scroll the current browser page.",
          input_schema={"type": "object", "properties": {"direction": {"type": "string", "enum": ["down", "up", "bottom", "top"]}, "amount": {"type": "integer"}}, "required": ["direction"]})
def browser_scroll(direction: str, amount: int = 800) -> str:
    def action() -> str:
        try:
            page = bc.get_page()
            before = float(page.evaluate("() => window.scrollY"))
            maximum = float(page.evaluate(
                "() => Math.max(0, document.documentElement.scrollHeight - window.innerHeight)"
            ))
            direction_normalized = direction.strip().lower()
            if direction_normalized not in {"down", "up", "bottom", "top"}:
                return "Scroll direction must be down, up, bottom, or top."
            if direction_normalized == "bottom":
                page.keyboard.press("End")
            elif direction_normalized == "top":
                page.keyboard.press("Home")
            else:
                page.mouse.wheel(0, int(amount or 800) * (1 if direction_normalized == "down" else -1))
            page.wait_for_timeout(700)
            after = float(page.evaluate("() => window.scrollY"))
            reached_edge = (
                direction_normalized == "top" and after <= 1
            ) or (
                direction_normalized == "bottom" and after >= max(0.0, maximum - 1)
            )
            if after == before and not reached_edge:
                return f"Scroll input was sent {direction_normalized}, but position did not change."
            evidence = "requested edge reached" if reached_edge else "position changed"
            return (f"Scrolled {direction_normalized}; postcondition verified ({evidence}) by "
                    f"scroll position {before:.0f} -> {after:.0f} of {maximum:.0f}.")
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_scroll", action, timeout=10.0)


@register(name="browser_screenshot", description="Save a screenshot of the current browser page.",
          input_schema={"type": "object", "properties": {"full_page": {"type": "boolean"}}})
def browser_screenshot(full_page: bool = False) -> str:
    def action() -> str:
        try:
            from datetime import datetime
            from reyes_agent import config
            page = bc.get_page()
            out_dir = config.VAULT_PATH / "07-System" / "captures"
            out_dir.mkdir(parents=True, exist_ok=True)
            name = f"browser-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
            output = out_dir / name
            page.screenshot(path=str(output), full_page=bool(full_page), timeout=bc.action_timeout_ms(30_000))
            if not output.is_file() or output.stat().st_size < 100:
                return f"Failed to verify browser screenshot {name}."
            return (f"Saved screenshot {name} (of {page.url}); postcondition verified on disk "
                    f"({output.stat().st_size} bytes).")
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_screenshot", action, timeout=35.0)


@register(name="browser_tabs",
          description=("List the real tabs currently open in ZENO's OWN automated browser (title, URL, which one is "
                       "active) -- use this to answer 'is the X tab still open' or 'what tabs are open' honestly from "
                       "live state rather than assuming. This does NOT see the owner's separately-launched personal "
                       "Chrome/Edge -- only the persistent browser ZENO itself drives. Empty list if no session is "
                       "running (never a remembered/stale answer)."),
          input_schema={"type": "object", "properties": {}})
def browser_tabs() -> str:
    import json

    def action() -> str:
        tabs = bc.list_pages()
        return json.dumps({"open": bool(tabs), "count": len(tabs), "tabs": tabs}, default=str)
    return _run("browser_tabs", action, timeout=15.0)


class _TabAmbiguous(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def resolve_tab_reference(tabs: list[dict], reference: str) -> dict:
    """Pure resolution logic, kept separate from the threaded browser-runtime
    call so it is directly unit-testable without Playwright. Never guesses:
    raises _TabAmbiguous (a plain, honest message) rather than picking a tab
    on a no-match or multi-match reference."""
    if not tabs:
        raise _TabAmbiguous("No browser session is running -- there is nothing to close.")
    text = str(reference or "").strip()
    if text.isdigit():
        index = int(text)
        match = next((t for t in tabs if t["index"] == index), None)
        if match is None:
            raise _TabAmbiguous(f"No tab at index {index} ({len(tabs)} open).")
        return match
    if text.casefold() in {"current", "active", "this one", "this tab", ""}:
        return next((t for t in tabs if t["active"]), tabs[-1])
    needle = text.casefold()
    candidates = [t for t in tabs if needle in t["title"].casefold() or needle in t["url"].casefold()]
    if not candidates:
        raise _TabAmbiguous(f"No open tab matches '{reference}'. Open tabs: " +
                            ", ".join(t["title"] or t["url"] for t in tabs))
    if len(candidates) > 1:
        raise _TabAmbiguous(f"'{reference}' matches more than one open tab: " +
                            ", ".join(t["title"] or t["url"] for t in candidates) + ". Which one?")
    return candidates[0]


@register(name="browser_close_tab",
          description=("Close one tab in ZENO's browser by its index from browser_tabs, or by a case-insensitive "
                       "substring of its title/URL. Use 'current'/'active'/'this one' for the active tab. Refuses "
                       "(rather than guessing) if the reference matches more than one tab or none."),
          input_schema={"type": "object", "properties": {
              "reference": {"type": "string", "description": "A tab index (e.g. '1'), 'current', or a title/URL substring."},
          }, "required": ["reference"]})
def browser_close_tab(reference: str) -> str:
    def action() -> str:
        try:
            match = resolve_tab_reference(bc.list_pages(), reference)
        except _TabAmbiguous as exc:
            return exc.message
        ok, detail = bc.close_page(match["index"])
        if not ok:
            return f"Could not close {match['title'] or match['url']!r}: {detail}"
        return f"Closed {match['title'] or match['url']!r}; postcondition verified: {detail}."
    return _run("browser_close_tab", action, timeout=15.0)


@register(name="browser_vision_click", description="Find a reference image on the current page and click it.",
          input_schema={"type": "object", "properties": {"template_path": {"type": "string"}, "threshold": {"type": "number"}}, "required": ["template_path"]})
def browser_vision_click(template_path: str, threshold: float = 0.75) -> str:
    def action() -> str:
        try:
            point = bc.find_on_screenshot(template_path, float(threshold or 0.75))
            if point is None:
                return "Vision match failed -- nothing on the page matched that image above the threshold."
            page = bc.get_page()
            before_url, before_title = page.url, page.title()
            try:
                before_text = page.inner_text("body", timeout=bc.action_timeout_ms(15_000))[:20_000]
            except Exception:  # noqa: BLE001
                before_text = ""
            page.mouse.click(*point)
            page.wait_for_load_state("domcontentloaded", timeout=bc.action_timeout_ms(15_000))
            page.wait_for_timeout(250)
            try:
                after_text = page.inner_text("body", timeout=bc.action_timeout_ms(15_000))[:20_000]
            except Exception:  # noqa: BLE001
                after_text = before_text
            if page.url != before_url or page.title() != before_title or after_text != before_text:
                return (f"Vision-clicked at {point}; postcondition verified by a "
                        f"visible page-state change at {page.url}.")
            return (f"Vision click was sent at {point}, but no URL, title, or visible-text "
                    "change was observed; the effect is unverified.")
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_vision_click", action, timeout=25.0)


@register(name="browser_close", description="Close ZENO's browser while retaining its saved profile.",
          input_schema={"type": "object", "properties": {}})
def browser_close() -> str:
    if not bc.is_open():
        return "The browser wasn't open."
    try:
        _run("browser_close", bc.close_browser, timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    if bc.is_open():
        return "Browser close was requested, but the persistent context still reports open."
    return "Browser closed; postcondition verified. Saved logins are kept for next time."
