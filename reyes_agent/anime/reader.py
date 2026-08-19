"""Read and understand a manga or manhwa PAGE.

WHY THE VISION MODEL, NOT OCR
-----------------------------
A comic page is art and text at once. Plain OCR pulls letters out of speech
bubbles and loses the panel order, the who-is-speaking, and everything the
drawing carries. ZENO's vision model reads the page the way a person does --
following the panels, attributing dialogue, and understanding what happens --
and it handles Japanese, Korean and English text natively, so raw manga and
Korean manhwa work without a CJK OCR pack.

READING ORDER MATTERS
---------------------
Manga reads right-to-left, top-to-bottom. Manhwa is a vertical scroll read
top-to-bottom. Western comics read left-to-right. Telling the model which one
it is looking at is the difference between the real sequence and scrambled
dialogue, so the format is part of the prompt.

WHAT THIS DOES NOT DO
---------------------
It does not fetch chapters. It reads a page the owner already has -- a file,
a screenshot, a photo. Downloading copyrighted chapters from piracy sites is
not built and will not be.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Reading order and layout guidance per format. The model is told exactly how
# to traverse the page.
_FORMAT_GUIDE: dict[str, str] = {
    "manga": ("This is a Japanese MANGA page. Read panels RIGHT-TO-LEFT, "
              "top-to-bottom. Speech bubbles within a panel also go "
              "right-to-left."),
    "manhwa": ("This is a Korean MANHWA / webtoon panel. Read TOP-TO-BOTTOM "
               "as a vertical scroll. Text may be Korean."),
    "manhua": ("This is a Chinese MANHUA page. Read TOP-TO-BOTTOM; panels may "
               "go left-to-right. Text may be Chinese."),
    "comic": ("This is a Western comic page. Read panels LEFT-TO-RIGHT, "
              "top-to-bottom."),
    "auto": ("This is a comic page. First work out whether it is Japanese "
             "manga (right-to-left), Korean manhwa (vertical scroll) or a "
             "Western comic (left-to-right), then read it in that order."),
}

FORMATS = tuple(_FORMAT_GUIDE)


@dataclass
class PageReading:
    ok: bool
    text: str
    fmt: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "format": self.fmt, "reading": self.text,
                "detail": self.detail}


def _prompt(fmt: str, focus: str) -> str:
    guide = _FORMAT_GUIDE.get(fmt, _FORMAT_GUIDE["auto"])
    ask = focus.strip() or (
        "Then give me: (1) the dialogue and narration in order, each line "
        "attributed to who says it where you can tell; (2) a two or three "
        "sentence summary of what happens on this page. If any text is not in "
        "English, translate it and note the original language.")
    return (f"{guide}\n\n{ask}\n\n"
            "If the image is not a comic page, say so plainly instead of "
            "inventing dialogue.")


def read_page(image_bytes: bytes, *, fmt: str = "auto", focus: str = "") -> PageReading:
    """Read one page image. `fmt` is manga/manhwa/manhua/comic/auto."""
    fmt = (fmt or "auto").strip().lower()
    if fmt not in _FORMAT_GUIDE:
        fmt = "auto"
    if not image_bytes:
        return PageReading(False, "", fmt, "no image was given")

    try:
        from reyes_agent.tools.vision import _describe_image
    except Exception as exc:  # noqa: BLE001
        return PageReading(False, "", fmt, f"vision unavailable: {exc}")

    try:
        text = _describe_image(image_bytes, _prompt(fmt, focus))
    except Exception as exc:  # noqa: BLE001
        # The most common cause is no GEMINI_API_KEY. Say it plainly.
        return PageReading(False, "", fmt, str(exc))
    return PageReading(True, text.strip(), fmt)
