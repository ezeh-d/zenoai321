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
            return f"Opened {page.url} -- '{page.title()}'."
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
                element = page.query_selector(selector)
                if element is None:
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
            if text.strip():
                page.get_by_text(text.strip(), exact=False).first.click(timeout=timeout)
            elif selector.strip():
                page.click(selector, timeout=timeout)
            else:
                return "Give either text or selector."
            page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return f"Clicked '{text or selector}'. Now at {page.url}"
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
                page.get_by_label(label.strip(), exact=False).first.fill(value, timeout=timeout)
                return f"Filled '{label}'."
            if selector.strip():
                page.fill(selector, value, timeout=timeout)
                return f"Filled '{selector}'."
            return "Give either selector or label."
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
            direction_normalized = direction.strip().lower()
            if direction_normalized == "bottom":
                page.keyboard.press("End")
            elif direction_normalized == "top":
                page.keyboard.press("Home")
            else:
                page.mouse.wheel(0, int(amount or 800) * (1 if direction_normalized == "down" else -1))
            page.wait_for_timeout(700)
            return f"Scrolled {direction_normalized}."
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
            page.screenshot(path=str(out_dir / name), full_page=bool(full_page), timeout=bc.action_timeout_ms(30_000))
            return f"Saved screenshot {name} (of {page.url})."
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_screenshot", action, timeout=35.0)


@register(name="browser_vision_click", description="Find a reference image on the current page and click it.",
          input_schema={"type": "object", "properties": {"template_path": {"type": "string"}, "threshold": {"type": "number"}}, "required": ["template_path"]})
def browser_vision_click(template_path: str, threshold: float = 0.75) -> str:
    def action() -> str:
        try:
            point = bc.find_on_screenshot(template_path, float(threshold or 0.75))
            if point is None:
                return "Vision match failed -- nothing on the page matched that image above the threshold."
            page = bc.get_page()
            page.mouse.click(*point)
            page.wait_for_load_state("domcontentloaded", timeout=bc.action_timeout_ms(15_000))
            return f"Vision-clicked at {point}. Now at {page.url}"
        except Exception as exc:  # noqa: BLE001
            return _err(exc)
    return _run("browser_vision_click", action, timeout=25.0)


@register(name="browser_close", description="Close ZENO's browser while retaining its saved profile.",
          input_schema={"type": "object", "properties": {}})
def browser_close() -> str:
    if not bc.is_open():
        return "The browser wasn't open."
    _run("browser_close", bc.close_browser, timeout=10.0)
    return "Browser closed. Saved logins are kept for next time."
