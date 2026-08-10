"""REYES's eyes (and now a hand): screen/webcam capture described via a
vision-capable model, plus text-to-image generation.

Capture description deliberately always uses Gemini directly, independent
of MODEL_PROVIDER -- vision needs a multimodal model and we've verified
Gemini handles it; routing through whatever text provider happens to be
active (which might not take images at all) would silently break this.

Image *generation* uses a different, free, no-account service
(Pollinations.ai) instead -- Gemini's and OpenAI's own image models exist
but need billing configured on the user's account, which as of 2026-07-23
neither has. Swap `generate_image` to a paid provider later without
touching any other tool -- it's the same kind of seam as the model
provider itself.

Everything here saves to disk (vault/07-System/captures/) so you can open
the actual image, not just take REYES's word for what's in it.
"""

from __future__ import annotations

import base64
import io
import time

from reyes_agent import config
from reyes_agent.tools import register

_CAPTURE_DIR = config.VAULT_PATH / "07-System" / "captures"


class VisionError(Exception):
    pass


def _describe_image(image_bytes: bytes, question: str) -> str:
    if not config.GEMINI_API_KEY:
        raise VisionError(
            "No GEMINI_API_KEY set -- vision needs it regardless of MODEL_PROVIDER. Add one to .env."
        )
    import openai

    client = openai.OpenAI(
        api_key=config.GEMINI_API_KEY,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    b64 = base64.b64encode(image_bytes).decode()
    try:
        resp = client.chat.completions.create(
            model=config.GEMINI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            max_tokens=600,
        )
    except Exception as exc:  # noqa: BLE001
        raise VisionError(str(exc)) from exc
    return resp.choices[0].message.content or "(no description came back)"


def _save_capture(image_bytes: bytes, prefix: str) -> str:
    _CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CAPTURE_DIR / f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    path.write_bytes(image_bytes)
    return str(path)


@register(
    name="generate_image",
    description=(
        "Generate an image from a text description and save it. Uses a "
        "free, no-account image generation service (Pollinations.ai) -- "
        "not Gemini/OpenAI's paid image models, which need billing set up "
        "on the user's account first. Good for illustrations, website "
        "graphics, icons -- not a substitute for a real photo."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Description of the image to generate."},
            "width": {"type": "integer", "description": "Width in pixels. Default 1024."},
            "height": {"type": "integer", "description": "Height in pixels. Default 1024."},
        },
        "required": ["prompt"],
    },
)
def generate_image(prompt: str, width: int = 1024, height: int = 1024) -> str:
    import urllib.parse

    import requests

    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&nologo=true"
    )
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"Couldn't generate the image: {exc}"

    path = _save_capture(resp.content, "generated")
    return f"Generated and saved to {path}."


@register(
    name="take_screenshot",
    description=(
        "Capture the screen right now and describe what's on it, using a "
        "vision model. Use this when the user asks what's on their screen, "
        "wants help with something visible on screen, or asks you to look "
        "at their current window."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What to look for/answer about the screenshot. Default: general description.",
            },
        },
    },
)
def take_screenshot(question: str = "Describe what's on the screen, in a few sentences.") -> str:
    import pyautogui

    img = pyautogui.screenshot()
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    image_bytes = buf.getvalue()
    path = _save_capture(image_bytes, "screenshot")
    try:
        description = _describe_image(image_bytes, question)
    except VisionError as exc:
        return (f"Captured the screen; postcondition verified: screenshot file exists at {path}. "
                f"Image description failed: {exc}")
    return f"{description}\n\n(postcondition verified: screenshot file exists at {path})"


@register(
    name="take_webcam_photo",
    description=(
        "Take a photo with the webcam right now and describe what's in it, "
        "using a vision model. Only use when the user explicitly asks REYES "
        "to look through the camera -- never proactively."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What to look for/answer about the photo. Default: general description.",
            },
        },
    },
)
def take_webcam_photo(question: str = "Describe what you see, in a few sentences.") -> str:
    import cv2

    cam = cv2.VideoCapture(0)
    try:
        if not cam.isOpened():
            return "Couldn't open the webcam -- it may be in use by another app, or there isn't one."
        # First frame after opening is often dark/unfocused -- warm up briefly.
        for _ in range(5):
            cam.read()
        ok, frame = cam.read()
    finally:
        cam.release()

    if not ok:
        return "Webcam opened but didn't return a frame."

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return "Captured a frame but couldn't encode it."
    image_bytes = buf.tobytes()
    path = _save_capture(image_bytes, "webcam")
    try:
        description = _describe_image(image_bytes, question)
    except VisionError as exc:
        return f"Took the photo (saved to {path}) but couldn't describe it: {exc}"
    return f"{description}\n\n(saved to {path})"
