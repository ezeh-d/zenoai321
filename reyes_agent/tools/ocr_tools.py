"""OCR / document-reading tools.

Complements the existing vision tools rather than replacing them:
`take_screenshot` sends an IMAGE to the model (good for layout, colour and
"what am I looking at"), while `read_screen_text` extracts the actual TEXT
locally (good for exact strings, error messages, long documents, and it
costs no vision tokens).
"""

from __future__ import annotations

from reyes_agent.tools import register


def _format(res, want_lines: bool = False) -> str:
    if res.error:
        return f"Couldn't read that: {res.error}"
    if not res.ok or not res.text.strip():
        return f"No text found in {res.source}."
    header = (f"Read {res.word_count} words from {res.source} "
              f"({res.engine}, confidence {res.confidence:.0%} — {res.confidence_basis})")
    body = "\n".join(res.lines) if (want_lines and res.lines) else res.text
    if res.confidence < 0.5:
        header += ("\nWARNING: low confidence. Treat the text below as uncertain and say so "
                   "rather than acting on an exact string from it.")
    return f"{header}\n\n{body.strip()[:6000]}"


@register(
    name="read_screen_text",
    description=(
        "Read the TEXT currently visible on screen using local OCR. Use for "
        "exact strings: error messages, code, form values, a document the "
        "user is looking at. Cheaper and more precise than take_screenshot "
        "for text; use take_screenshot instead when layout or colour matters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional [left, top, right, bottom] pixel box. Omit for the whole screen.",
            },
        },
    },
)
def read_screen_text(region: list | None = None) -> str:
    from reyes_agent import ocr

    box = None
    if region and len(region) == 4:
        box = (int(region[0]), int(region[1]), int(region[2]), int(region[3]))
    return _format(ocr.extract_screen_text(box))


@register(
    name="read_document",
    description=(
        "Extract the text of a file: images (OCR), or text/markdown/csv/code "
        "read directly. Says plainly when a format needs a library that "
        "isn't installed instead of returning empty text."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full path to the file."},
            "as_lines": {"type": "boolean", "description": "Preserve line structure (useful for tables/forms)."},
        },
        "required": ["path"],
    },
)
def read_document(path: str, as_lines: bool = False) -> str:
    from reyes_agent import ocr

    return _format(ocr.extract_document_text(path), want_lines=bool(as_lines))


@register(
    name="ocr_capabilities",
    description="What ZENO can and cannot read: OCR engines, languages, supported formats, and which formats need a missing library.",
    input_schema={"type": "object", "properties": {}},
    light=True,
)
def ocr_capabilities() -> str:
    from reyes_agent import ocr

    c = ocr.capabilities()
    lines = [
        f"OCR engine(s): {', '.join(c['ocr_engines']) or 'NONE AVAILABLE'}",
        f"OCR languages: {', '.join(c['ocr_languages']) or 'none'}",
        f"Images (OCR): {', '.join(c['image_formats'])}",
        f"Text (direct): {', '.join(c['text_formats'])}",
        "",
        "Cannot read without extra libraries:",
    ]
    lines += [f"  {ext} -> needs {lib}" for ext, lib in c["unsupported_needing_libs"].items()]
    lines.append(f"\nConfidence is {c['confidence']}.")
    return "\n".join(lines)
