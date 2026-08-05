from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ollama import Client
from PIL import ImageGrab

from config import (
    OLLAMA_HOST,
    SCREENSHOT_DIR,
    VISION_MODEL,
    VISION_TIMEOUT_SECONDS,
)


DEFAULT_SCREEN_PROMPT = (
    "Describe what is currently visible on this computer screen. "
    "Mention the main application, important text, buttons, warnings, "
    "errors, and anything that appears useful to the user. "
    "Be accurate and concise."
)

READ_SCREEN_PROMPT = (
    "Read the useful visible text on this computer screen. "
    "Preserve error messages, headings, filenames, commands, and buttons. "
    "Do not invent text that is not visible."
)

ERROR_SCREEN_PROMPT = (
    "Inspect this computer screen for an error or warning. "
    "Explain what the error says, the most likely cause, and safe steps "
    "the user can try next. Do not claim certainty when the image is unclear."
)


def _ensure_screenshot_directory() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def capture_screen(filename: str | None = None) -> Path:
    """
    Capture all visible monitors and save the screenshot.

    Returns:
        The absolute path of the saved PNG screenshot.
    """
    _ensure_screenshot_directory()

    if filename:
        safe_name = Path(filename).name

        if not safe_name.lower().endswith(".png"):
            safe_name += ".png"
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"screen_{timestamp}.png"

    screenshot_path = SCREENSHOT_DIR / safe_name

    image = ImageGrab.grab(all_screens=True)
    image.save(screenshot_path, format="PNG")

    return screenshot_path.resolve()


def _extract_response_text(response: Any) -> str:
    """
    Normalize responses returned by different Ollama client versions.
    """
    message = getattr(response, "message", None)

    if message is not None:
        content = getattr(message, "content", None)

        if isinstance(content, str):
            return content.strip()

    if isinstance(response, dict):
        response_message = response.get("message", {})

        if isinstance(response_message, dict):
            content = response_message.get("content")

            if isinstance(content, str):
                return content.strip()

    return str(response).strip()


def analyze_image(
    image_path: str | Path,
    prompt: str = DEFAULT_SCREEN_PROMPT,
) -> str:
    """
    Analyze one image using the configured local Ollama vision model.
    """
    path = Path(image_path).expanduser().resolve()

    if not path.exists():
        return f"I could not find the image: {path}"

    if not path.is_file():
        return f"The image path is not a file: {path}"

    clean_prompt = prompt.strip() or DEFAULT_SCREEN_PROMPT

    try:
        client = Client(
            host=OLLAMA_HOST,
            timeout=VISION_TIMEOUT_SECONDS,
        )

        response = client.chat(
            model=VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": clean_prompt,
                    "images": [str(path)],
                }
            ],
        )

        answer = _extract_response_text(response)

        if not answer:
            return "The vision model returned an empty response."

        return answer

    except Exception as error:
        message = str(error)

        if "not found" in message.lower():
            return (
                f"The vision model '{VISION_MODEL}' is not installed. "
                f"Run: ollama pull {VISION_MODEL}"
            )

        return (
            "I could not analyze the image. "
            f"{type(error).__name__}: {error}"
        )


def analyze_screen(prompt: str = DEFAULT_SCREEN_PROMPT) -> str:
    """
    Capture the current screen and analyze it.
    """
    try:
        screenshot_path = capture_screen()
    except Exception as error:
        return (
            "I could not capture the screen. "
            f"{type(error).__name__}: {error}"
        )

    return analyze_image(
        image_path=screenshot_path,
        prompt=prompt,
    )


def describe_screen() -> str:
    """
    Describe the current screen.
    """
    return analyze_screen(DEFAULT_SCREEN_PROMPT)


def read_screen_text() -> str:
    """
    Read useful visible text from the current screen.
    """
    return analyze_screen(READ_SCREEN_PROMPT)


def analyze_screen_error() -> str:
    """
    Inspect the current screen for an error or warning.
    """
    return analyze_screen(ERROR_SCREEN_PROMPT)


if __name__ == "__main__":
    print(describe_screen())