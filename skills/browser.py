"""Web automation via Playwright: browse, search a page, fill forms, click.

Lazy-starts a real Chromium browser the first time it's used. Requires:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations


class Browser:
    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._page = None

    def _ensure(self) -> str | None:
        if self._page is not None:
            return None
        try:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=False)
            self._page = self._browser.new_page()
            return None
        except Exception as e:  # noqa: BLE001
            return (
                f"Could not start browser ({e}). "
                "Run: pip install playwright && playwright install chromium"
            )

    def browse(self, url: str) -> str:
        err = self._ensure()
        if err:
            return err
        if not url.startswith("http"):
            url = "https://" + url
        try:
            self._page.goto(url, timeout=30000)
            title = self._page.title()
            text = self._page.inner_text("body")[:1500]
            return f"Opened: {title}\n\n{text}"
        except Exception as e:  # noqa: BLE001
            return f"Error opening {url}: {e}"

    def find_on_page(self, query: str) -> str:
        if self._page is None:
            return "No page open. Use browse first."
        try:
            body = self._page.inner_text("body")
            lines = [ln for ln in body.splitlines() if query.lower() in ln.lower()]
            return "\n".join(lines[:20]) if lines else f"'{query}' not found on page."
        except Exception as e:  # noqa: BLE001
            return f"Error searching page: {e}"

    def type_text(self, selector: str, text: str) -> str:
        if self._page is None:
            return "No page open. Use browse first."
        try:
            self._page.fill(selector, text)
            return f"Typed into {selector}."
        except Exception as e:  # noqa: BLE001
            return f"Error typing into {selector}: {e}"

    def click(self, selector: str) -> str:
        if self._page is None:
            return "No page open. Use browse first."
        try:
            self._page.click(selector, timeout=10000)
            return f"Clicked {selector}. Now on: {self._page.title()}"
        except Exception as e:  # noqa: BLE001
            return f"Error clicking {selector}: {e}"

    def read_page(self) -> str:
        if self._page is None:
            return "No page open. Use browse first."
        try:
            return self._page.inner_text("body")[:4000]
        except Exception as e:  # noqa: BLE001
            return f"Error reading page: {e}"

    def screenshot_page(self, path: str = "data/page.png") -> str:
        if self._page is None:
            return "No page open. Use browse first."
        try:
            self._page.screenshot(path=path, full_page=True)
            return f"Saved page screenshot to {path}."
        except Exception as e:  # noqa: BLE001
            return f"Error screenshotting page: {e}"

    def close_browser(self) -> str:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._page = None
        return "Browser closed."
