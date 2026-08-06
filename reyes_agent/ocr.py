"""OCR and document text extraction.

ENGINE CHOICE, AND WHY
----------------------
Uses the OCR engine built into Windows (`Windows.Media.Ocr` via the
`winsdk` package that is already a dependency for notification handling).
Verified available on this machine with en-GB/en-US recognisers.

Tesseract was the obvious first choice and was rejected on evidence:
`pytesseract` is not installed AND it needs a separate native binary that
is also absent, so wiring it would have produced a module that imports
fine and fails at run time. The Windows engine needs neither, and it
returns per-word confidence, which the rest of this file depends on.

CONFIDENCE IS REAL, NOT INVENTED
--------------------------------
Windows OCR does not expose a numeric per-word score, so a fabricated
percentage would be dishonest. Instead the confidence reported here is
derived from observable properties of the result: how much text was
found, how many words survive a dictionary-shape sanity check, and
average word length. It is labelled as a heuristic everywhere it appears,
and `extract_*` always returns the raw text alongside it so a caller can
judge for itself.

DOCUMENTS
---------
Plain text and markdown are read directly. PDF/DOCX/XLSX need libraries
that are NOT installed (`fitz`, `python-docx`, `openpyxl`); those formats
report exactly that rather than returning empty text that looks like a
successful read of an empty document.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".py",
                  ".js", ".html", ".css", ".yml", ".yaml", ".ini", ".xml"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
# Formats we can identify but genuinely cannot read without extra libraries.
_NEEDS_LIB = {
    ".pdf": "PyMuPDF (fitz)",
    ".docx": "python-docx",
    ".doc": "python-docx (and .doc needs conversion to .docx first)",
    ".xlsx": "openpyxl",
    ".xls": "openpyxl",
    ".pptx": "python-pptx",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")


@dataclass
class OcrResult:
    text: str = ""
    ok: bool = False
    source: str = ""
    engine: str = ""
    word_count: int = 0
    confidence: float = 0.0      # 0-1 heuristic; see module docstring
    confidence_basis: str = ""
    error: str = ""
    lines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "source": self.source, "engine": self.engine,
            "text": self.text, "word_count": self.word_count,
            "confidence": round(self.confidence, 2),
            "confidence_basis": self.confidence_basis,
            "error": self.error, "line_count": len(self.lines),
        }


def _score(text: str) -> tuple[float, str]:
    """Heuristic quality score for an OCR result.

    Deliberately simple and explainable: OCR noise looks like short
    fragments of non-word characters, real text looks like words. Returns
    (0-1, human-readable basis).
    """
    stripped = text.strip()
    if not stripped:
        return 0.0, "no text found"
    words = _WORD_RE.findall(stripped)
    if not words:
        return 0.15, "characters found but no recognisable words"
    total_tokens = len(stripped.split())
    word_ratio = len(words) / max(1, total_tokens)
    avg_len = sum(len(w) for w in words) / len(words)
    # Real prose sits around 4-6 chars/word; 1-2 means fragmented noise.
    length_factor = min(1.0, avg_len / 4.0)
    volume_factor = min(1.0, len(words) / 12.0)   # very little text = less certain
    score = 0.55 * word_ratio + 0.30 * length_factor + 0.15 * volume_factor
    basis = (f"{len(words)} word-like tokens of {total_tokens} "
             f"({word_ratio:.0%}), avg length {avg_len:.1f}")
    return max(0.0, min(1.0, score)), basis


async def _ocr_bitmap_async(path: Path) -> tuple[str, list[str]]:
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage import FileAccessMode, StorageFile

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("no OCR recogniser installed for your Windows display languages")
    f = await StorageFile.get_file_from_path_async(str(path))
    stream = await f.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    result = await engine.recognize_async(bitmap)
    lines = [ln.text for ln in result.lines] if result and result.lines else []
    return (result.text if result else ""), lines


def extract_image_text(image_path: str | Path) -> OcrResult:
    """OCR one image file using the Windows engine."""
    path = Path(image_path)
    if not path.is_file():
        return OcrResult(source=str(path), error="no such file")
    try:
        text, lines = asyncio.run(_ocr_bitmap_async(path))
    except Exception as exc:  # noqa: BLE001 -- surfaced to the caller, never swallowed
        return OcrResult(source=str(path), engine="windows-ocr",
                         error=f"{type(exc).__name__}: {exc}")
    conf, basis = _score(text)
    return OcrResult(text=text, ok=bool(text.strip()), source=str(path),
                     engine="windows-ocr", word_count=len(text.split()),
                     confidence=conf, confidence_basis=basis, lines=lines)


def extract_screen_text(region: tuple[int, int, int, int] | None = None) -> OcrResult:
    """Capture the screen (or a region) and OCR it.

    Reuses the existing screenshot path rather than adding a second capture
    mechanism, then deletes the temporary frame -- reading the screen should
    not silently accumulate images of the user's desktop on disk.
    """
    import tempfile

    try:
        import mss
    except ImportError:
        try:
            from PIL import ImageGrab
        except ImportError:
            return OcrResult(engine="windows-ocr", source="screen",
                             error="no screen-capture library available (mss or Pillow)")
        img = ImageGrab.grab(bbox=region)
        tmp = Path(tempfile.gettempdir()) / "zeno_ocr_screen.png"
        img.save(tmp)
    else:
        with mss.mss() as sct:
            mon = sct.monitors[1]
            box = ({"left": region[0], "top": region[1],
                    "width": region[2] - region[0], "height": region[3] - region[1]}
                   if region else mon)
            shot = sct.grab(box)
            tmp = Path(tempfile.gettempdir()) / "zeno_ocr_screen.png"
            import mss.tools

            mss.tools.to_png(shot.rgb, shot.size, output=str(tmp))

    try:
        res = extract_image_text(tmp)
        res.source = "screen" + (f" region {region}" if region else " (full)")
        return res
    finally:
        try:
            tmp.unlink(missing_ok=True)   # don't leave desktop captures lying around
        except OSError:
            pass


def extract_document_text(doc_path: str | Path, max_chars: int = 20000) -> OcrResult:
    """Text from a document. Images route to OCR; text formats are read
    directly; formats needing an absent library say so explicitly."""
    path = Path(doc_path)
    if not path.is_file():
        return OcrResult(source=str(path), error="no such file")
    suffix = path.suffix.lower()

    if suffix in _IMAGE_SUFFIXES:
        return extract_image_text(path)

    if suffix in _TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except OSError as exc:
            return OcrResult(source=str(path), error=str(exc))
        conf, basis = _score(text)
        return OcrResult(text=text, ok=bool(text.strip()), source=str(path),
                         engine="direct-read", word_count=len(text.split()),
                         # A direct file read is exact; the heuristic only
                         # describes OCR uncertainty, so report full confidence.
                         confidence=1.0,
                         confidence_basis="read directly from disk, no OCR involved",
                         lines=text.splitlines()[:400])

    if suffix in _NEEDS_LIB:
        return OcrResult(source=str(path), engine="none",
                         error=(f"{suffix} needs {_NEEDS_LIB[suffix]}, which is not installed. "
                                "No text extracted -- install it, or export the file to PDF "
                                "images/text and I can read that."))

    return OcrResult(source=str(path), engine="none",
                     error=f"unsupported file type '{suffix}'")


def capabilities() -> dict:
    """What this module can genuinely do right now."""
    engines = []
    langs: list[str] = []
    try:
        from winsdk.windows.media.ocr import OcrEngine

        langs = [l.language_tag for l in OcrEngine.available_recognizer_languages]
        if OcrEngine.try_create_from_user_profile_languages() is not None:
            engines.append("windows-ocr")
    except Exception:  # noqa: BLE001
        pass
    missing = sorted({v.split(" ")[0] for v in _NEEDS_LIB.values()})
    return {
        "ocr_engines": engines,
        "ocr_languages": langs,
        "image_formats": sorted(_IMAGE_SUFFIXES),
        "text_formats": sorted(_TEXT_SUFFIXES),
        "unsupported_needing_libs": {k: v for k, v in _NEEDS_LIB.items()},
        "missing_libraries": missing,
        "confidence": "heuristic (word-shape/length/volume), not an engine score",
    }
