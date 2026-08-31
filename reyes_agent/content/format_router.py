"""ContentFormatRouter -- decide what a file IS, by content first, name second.

Format is detected from magic bytes when possible (a .txt that is really a PDF,
or an extensionless download, is classified correctly), falling back to the
filename extension, then to a text/binary sniff. It never guesses a handler it
cannot actually run: `handler` names an extractor ZENO already has.

This does not parse anything -- it routes. The UniversalContentEngine takes the
FormatInfo and calls the named handler with the appropriate fallback chain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Coarse categories the rest of the engine and the panels branch on.
DOCUMENT = "document"
SPREADSHEET = "spreadsheet"
PRESENTATION = "presentation"
IMAGE = "image"
TEXT = "text"
CODE = "code"
DATA = "data"
ARCHIVE = "archive"
EMAIL = "email"
EBOOK = "ebook"
UNKNOWN = "unknown"


@dataclass
class FormatInfo:
    fmt: str                 # "pdf", "docx", "png", "csv", ...
    category: str            # one of the constants above
    mime: str = ""
    handler: str = ""        # which engine path parses it
    confidence: float = 0.0  # 0..1 -- how sure we are of the format
    method: str = ""         # "magic" | "extension" | "sniff"
    needs_ocr: bool = False   # a scanned/image doc may need OCR
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"format": self.fmt, "category": self.category, "mime": self.mime,
                "handler": self.handler, "confidence": round(self.confidence, 2),
                "method": self.method, "needs_ocr": self.needs_ocr,
                "detail": self.detail}


# --- magic-byte signatures (prefix -> (fmt, category, mime)) ----------------
_MAGIC: list[tuple[bytes, str, str, str]] = [
    (b"%PDF-", "pdf", DOCUMENT, "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "png", IMAGE, "image/png"),
    (b"\xff\xd8\xff", "jpg", IMAGE, "image/jpeg"),
    (b"GIF87a", "gif", IMAGE, "image/gif"),
    (b"GIF89a", "gif", IMAGE, "image/gif"),
    (b"BM", "bmp", IMAGE, "image/bmp"),
    (b"II*\x00", "tiff", IMAGE, "image/tiff"),
    (b"MM\x00*", "tiff", IMAGE, "image/tiff"),
    (b"RIFF", "webp", IMAGE, "image/webp"),   # refined below (WEBP vs WAV/AVI)
    (b"\x1f\x8b", "gz", ARCHIVE, "application/gzip"),
    (b"Rar!\x1a\x07", "rar", ARCHIVE, "application/vnd.rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z", ARCHIVE, "application/x-7z-compressed"),
    (b"{\\rtf", "rtf", DOCUMENT, "application/rtf"),
    (b"\xd0\xcf\x11\xe0", "ole", DOCUMENT, "application/x-ole-storage"),  # old .doc/.xls/.ppt
]

# ZIP-container formats disambiguated by their internal layout.
_OOXML = {
    "word/": ("docx", DOCUMENT, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "xl/": ("xlsx", SPREADSHEET, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "ppt/": ("pptx", PRESENTATION, "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}

# Extension map (fallback and refinement). handler chosen in `_handler_for`.
_EXT: dict[str, tuple[str, str]] = {
    ".pdf": ("pdf", DOCUMENT), ".doc": ("doc", DOCUMENT), ".docx": ("docx", DOCUMENT),
    ".rtf": ("rtf", DOCUMENT), ".odt": ("odt", DOCUMENT),
    ".xls": ("xls", SPREADSHEET), ".xlsx": ("xlsx", SPREADSHEET),
    ".xlsm": ("xlsx", SPREADSHEET), ".ods": ("ods", SPREADSHEET),
    ".csv": ("csv", DATA), ".tsv": ("tsv", DATA),
    ".ppt": ("ppt", PRESENTATION), ".pptx": ("pptx", PRESENTATION), ".odp": ("odp", PRESENTATION),
    ".txt": ("txt", TEXT), ".log": ("log", TEXT), ".md": ("md", TEXT),
    ".markdown": ("md", TEXT), ".rst": ("rst", TEXT),
    ".html": ("html", TEXT), ".htm": ("html", TEXT), ".xml": ("xml", DATA),
    ".json": ("json", DATA), ".yaml": ("yaml", DATA), ".yml": ("yaml", DATA),
    ".toml": ("toml", DATA), ".ini": ("ini", DATA), ".cfg": ("ini", DATA),
    ".tex": ("latex", DOCUMENT),
    ".jpg": ("jpg", IMAGE), ".jpeg": ("jpg", IMAGE), ".png": ("png", IMAGE),
    ".webp": ("webp", IMAGE), ".bmp": ("bmp", IMAGE), ".gif": ("gif", IMAGE),
    ".tiff": ("tiff", IMAGE), ".tif": ("tiff", IMAGE), ".svg": ("svg", IMAGE),
    ".heic": ("heic", IMAGE), ".heif": ("heic", IMAGE),
    ".eml": ("eml", EMAIL), ".msg": ("msg", EMAIL),
    ".epub": ("epub", EBOOK),
    ".zip": ("zip", ARCHIVE), ".gz": ("gz", ARCHIVE), ".tar": ("tar", ARCHIVE),
    ".py": ("py", CODE), ".js": ("js", CODE), ".ts": ("ts", CODE),
    ".java": ("java", CODE), ".c": ("c", CODE), ".cpp": ("cpp", CODE),
    ".go": ("go", CODE), ".rs": ("rs", CODE), ".rb": ("rb", CODE), ".sh": ("sh", CODE),
}

# Which engine path handles each format. Names are stable; the engine maps them.
_DOC_HANDLER = "document_text"      # -> ocr.extract_document_text (pdf/docx/xls/pptx)
_TEXT_HANDLER = "plain_text"        # deterministic text reader (txt/md/log/code)
_DATA_HANDLER = "structured_data"   # csv/tsv/json/yaml/xml deterministic parser
_IMAGE_HANDLER = "image"            # ocr.extract_image_text + vision
_UNSUPPORTED = "unsupported"


def _handler_for(fmt: str, category: str) -> tuple[str, bool]:
    """(handler, needs_ocr) for a format. Honest: unknown -> unsupported."""
    if category == IMAGE:
        return _IMAGE_HANDLER, True
    if fmt in ("txt", "md", "log", "rst", "html", "latex", "ini", "toml") or category in (TEXT, CODE):
        return _TEXT_HANDLER, False
    if fmt in ("csv", "tsv", "json", "yaml", "xml"):
        return _DATA_HANDLER, False
    if fmt in ("pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "rtf", "ole"):
        return _DOC_HANDLER, fmt in ("pdf", "ole")  # scanned pdf/legacy may need OCR
    return _UNSUPPORTED, False


def _sniff_text(head: bytes) -> bool:
    """Is this head plausibly UTF-8/ASCII text (not binary)?"""
    if not head:
        return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        # allow a little trailing multibyte truncation
        printable = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126 or b >= 160)
        return printable / max(1, len(head)) > 0.85


def _zip_kind(path: Path) -> tuple[str, str, str] | None:
    """Look inside a ZIP container to tell docx/xlsx/pptx/epub/zip apart."""
    try:
        import zipfile
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        joined = "\n".join(names)
        if "mimetype" in names:
            try:
                import zipfile as _z
                with _z.ZipFile(path) as zf:
                    mt = zf.read("mimetype").decode("ascii", "ignore").strip()
                if "epub" in mt:
                    return ("epub", EBOOK, "application/epub+zip")
            except Exception:  # noqa: BLE001
                pass
        for marker, (fmt, cat, mime) in _OOXML.items():
            if any(n.startswith(marker) for n in names) or marker in joined:
                return (fmt, cat, mime)
        return ("zip", ARCHIVE, "application/zip")
    except Exception:  # noqa: BLE001
        return None


class ContentFormatRouter:
    def detect(self, path: str | Path) -> FormatInfo:
        p = Path(os.path.expanduser(str(path)))
        if not p.exists():
            return FormatInfo(UNKNOWN, UNKNOWN, handler=_UNSUPPORTED,
                              method="missing", detail=f"'{p}' does not exist")
        if p.is_dir():
            return FormatInfo("folder", UNKNOWN, handler=_UNSUPPORTED,
                              method="stat", detail="is a directory")
        head = b""
        try:
            with open(p, "rb") as fh:
                head = fh.read(512)
        except OSError as exc:
            return FormatInfo(UNKNOWN, UNKNOWN, handler=_UNSUPPORTED,
                              method="error", detail=f"could not read: {exc}")

        ext = p.suffix.lower()

        # 1) magic bytes -- strongest signal
        for sig, fmt, cat, mime in _MAGIC:
            if head.startswith(sig):
                if fmt == "ole":               # refine legacy Office by extension
                    fmt2, cat2 = _EXT.get(ext, ("doc", DOCUMENT))
                    handler, ocr = _handler_for(fmt2, cat2)
                    return FormatInfo(fmt2, cat2, mime, handler, 0.85, "magic", ocr,
                                      "legacy Office binary")
                if fmt == "webp" and b"WEBP" not in head[:16]:
                    continue                    # RIFF but not WEBP (audio/video)
                handler, ocr = _handler_for(fmt, cat)
                return FormatInfo(fmt, cat, mime, handler, 0.98, "magic", ocr)

        # ZIP container -> docx/xlsx/pptx/epub/zip
        if head.startswith(b"PK\x03\x04"):
            kind = _zip_kind(p)
            if kind:
                fmt, cat, mime = kind
                handler, ocr = _handler_for(fmt, cat)
                return FormatInfo(fmt, cat, mime, handler, 0.95, "magic", ocr)

        # 2) extension
        if ext in _EXT:
            fmt, cat = _EXT[ext]
            handler, ocr = _handler_for(fmt, cat)
            # A text-category extension whose bytes look binary is suspicious.
            if cat in (TEXT, DATA, CODE) and not _sniff_text(head):
                return FormatInfo(fmt, cat, "", handler, 0.55, "extension", ocr,
                                  "extension says text but content looks binary")
            return FormatInfo(fmt, cat, "", handler, 0.8, "extension", ocr)

        # 3) content sniff
        if _sniff_text(head):
            return FormatInfo("txt", TEXT, "text/plain", _TEXT_HANDLER, 0.5,
                              "sniff", False, "no known extension; reads as text")
        return FormatInfo(UNKNOWN, UNKNOWN, "application/octet-stream",
                          _UNSUPPORTED, 0.3, "sniff", False,
                          "binary content with no recognised signature")


_router = ContentFormatRouter()


def detect(path: str | Path) -> FormatInfo:
    return _router.detect(path)
