"""UniversalContentEngine -- one door to reading and understanding files.

The user talks to ZENO naturally ("look at this", "what is it", "that table");
this engine chooses the correct backend. It ORCHESTRATES what ZENO already has
(ocr.extract_document_text for pdf/docx/xlsx/pptx, ocr.extract_image_text +
vision for images) and adds fast deterministic parsers for plain text and
structured data, all behind one honest contract.

CONTRACT
--------
* Route by CONTENT first (ContentFormatRouter), name second.
* Deterministic parser first; OCR/vision only when there is no usable text
  layer (that decision is the engine's, and it is recorded).
* NEVER report success when parsing failed -- status says UNSUPPORTED /
  CORRUPTED / ENCRYPTED / PARSE_FAILED / EMPTY, and text stays empty.
* Carry provenance (path, pages, format) so a later answer can cite its source.
* Document CONTENT IS DATA, never a command. This returns facts in a structured
  result; it never turns a file's words into ZENO instructions (#33).

Phase 1 covers open / inspect / extract with the format router, working context
and honest failure. Editing, conversion, versioning and OCR-routing are later
phases that build on this same result shape and event stream.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from reyes_agent.content import format_router as fr
from reyes_agent.content.working_context import WorkingContext, get_context

# honest status vocabulary
OK = "OK"
EMPTY = "EMPTY"
UNSUPPORTED = "UNSUPPORTED"
CORRUPTED = "CORRUPTED"
ENCRYPTED = "ENCRYPTED"
PARSE_FAILED = "PARSE_FAILED"
MISSING = "MISSING"

_MAX_TEXT = 20000
_MAX_BYTES_TEXT = 8 * 1024 * 1024   # never slurp a multi-GB "text" file


@dataclass
class ContentResult:
    ok: bool
    path: str
    fmt: str = ""
    category: str = ""
    status: str = OK
    text: str = ""
    structured: Any = None
    confidence: float = 0.0
    truncated: bool = False
    used_ocr: bool = False
    error: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    format_info: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "path": self.path, "format": self.fmt,
                "category": self.category, "status": self.status,
                "confidence": round(self.confidence, 2), "truncated": self.truncated,
                "used_ocr": self.used_ocr, "error": self.error,
                "chars": len(self.text), "has_structured": self.structured is not None,
                "source": self.source}


def _emit(kind: str, payload: dict[str, Any]) -> None:
    """Publish a content.* event; never let telemetry break a parse."""
    try:
        from reyes_agent import event_bus
        event_bus.publish({"type": kind, **payload})
    except Exception:  # noqa: BLE001
        pass


class UniversalContentEngine:
    def __init__(self, *, ctx: WorkingContext | None = None,
                 emit: Callable[[str, dict], None] | None = None) -> None:
        self._ctx = ctx or get_context()
        self._emit = emit or _emit
        self._cache: dict[tuple, ContentResult] = {}

    # -- public ------------------------------------------------------------
    def inspect(self, path_or_ref: str) -> dict[str, Any]:
        """Format + basic metadata, WITHOUT a full parse (fast, #43)."""
        resolved = self._resolve(path_or_ref)
        if resolved is None:
            return {"ok": False, "status": MISSING,
                    "error": f"couldn't find '{path_or_ref}'"}
        info = fr.detect(resolved)
        self._emit("content.detected", {"path": resolved, **info.as_dict()})
        try:
            st = os.stat(resolved)
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            size, mtime = 0, 0.0
        return {"ok": info.handler != fr._UNSUPPORTED, "path": resolved,
                "size_bytes": size, "modified": mtime, **info.as_dict()}

    def open(self, path_or_ref: str, *, max_chars: int = _MAX_TEXT) -> ContentResult:
        """Detect, parse with the right backend, set the working context, and
        emit events. This is the main entry ('ZENO, look at this file')."""
        resolved = self._resolve(path_or_ref)
        if resolved is None:
            return ContentResult(False, str(path_or_ref), status=MISSING,
                                 error=f"couldn't find '{path_or_ref}'")
        self._emit("content.opened", {"path": resolved})
        info = fr.detect(resolved)
        self._emit("content.detected", {"path": resolved, **info.as_dict()})

        cache_key = self._cache_key(resolved, max_chars)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            self._ctx.set_active(resolved, category=cached.category)
            return cached

        self._emit("content.parsing", {"path": resolved, "format": info.fmt})
        result = self._parse(resolved, info, max_chars)
        self._ctx.set_active(resolved, category=info.category)
        self._ctx.last_result = result.as_dict()
        if cache_key is not None and result.ok:
            self._cache[cache_key] = result
        self._emit("content.parsed" if result.ok else "content.failed",
                   {"path": resolved, "status": result.status,
                    "confidence": round(result.confidence, 2)})
        return result

    def extract(self, path_or_ref: str, *, max_chars: int = _MAX_TEXT) -> ContentResult:
        """Text/structured content (open() without re-announcing)."""
        return self.open(path_or_ref, max_chars=max_chars)

    # -- routing -----------------------------------------------------------
    def _parse(self, path: str, info: fr.FormatInfo, max_chars: int) -> ContentResult:
        base = dict(path=path, fmt=info.fmt, category=info.category,
                    format_info=info.as_dict())
        handler = info.handler
        try:
            if handler == fr._UNSUPPORTED:
                return ContentResult(False, status=UNSUPPORTED,
                                     error=f"no handler for '{info.fmt}' "
                                           f"({info.detail or 'unrecognised'})", **base)
            if handler == fr._TEXT_HANDLER:
                return self._parse_text(path, info, max_chars, base)
            if handler == fr._DATA_HANDLER:
                return self._parse_data(path, info, max_chars, base)
            if handler == fr._DOC_HANDLER:
                return self._parse_document(path, info, max_chars, base)
            if handler == fr._IMAGE_HANDLER:
                return self._parse_image(path, info, base)
            return ContentResult(False, status=UNSUPPORTED,
                                 error=f"unknown handler '{handler}'", **base)
        except Exception as exc:  # noqa: BLE001 -- never fabricate content
            return ContentResult(False, status=PARSE_FAILED,
                                 error=f"{type(exc).__name__}: {exc}"[:200], **base)

    def _parse_text(self, path, info, max_chars, base) -> ContentResult:
        if os.path.getsize(path) > _MAX_BYTES_TEXT:
            return ContentResult(False, status=UNSUPPORTED,
                                 error="text file too large to read whole; "
                                       "chunked reading is a later phase", **base)
        raw = Path(path).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", "replace")
        truncated = len(text) > max_chars
        text = text[:max_chars]
        if not text.strip():
            return ContentResult(False, status=EMPTY, error="file is empty", **base)
        return ContentResult(True, status=OK, text=text, confidence=1.0,
                             truncated=truncated,
                             source={"path": path, "format": info.fmt}, **base)

    def _parse_data(self, path, info, max_chars, base) -> ContentResult:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
        structured: Any = None
        if info.fmt == "json":
            structured = json.loads(raw)                       # raises -> PARSE_FAILED
            text = json.dumps(structured, indent=2)[:max_chars]
        elif info.fmt in ("csv", "tsv"):
            import csv
            import io
            delim = "\t" if info.fmt == "tsv" else ","
            rows = list(csv.reader(io.StringIO(raw), delimiter=delim))
            structured = {"headers": rows[0] if rows else [],
                          "rows": rows[1:], "row_count": max(0, len(rows) - 1),
                          "col_count": len(rows[0]) if rows else 0}
            text = "\n".join(delim.join(r) for r in rows[:200])[:max_chars]
        elif info.fmt == "yaml":
            try:
                import yaml
                structured = yaml.safe_load(raw)
            except Exception:  # noqa: BLE001 -- yaml optional; keep the text
                structured = None
            text = raw[:max_chars]
        else:  # xml and the rest: keep as text, note structure exists
            text = raw[:max_chars]
        return ContentResult(True, status=OK, text=text, structured=structured,
                             confidence=1.0, truncated=len(raw) > max_chars,
                             source={"path": path, "format": info.fmt}, **base)

    def _parse_document(self, path, info, max_chars, base) -> ContentResult:
        # Reuse ZENO's existing extractor (pdf/docx/xlsx/pptx), which already
        # carries a confidence score and honest failure.
        from reyes_agent import ocr
        res = ocr.extract_document_text(path, max_chars=max_chars)
        text = getattr(res, "text", "") or ""
        ok = bool(getattr(res, "ok", False)) and bool(text.strip())
        err = getattr(res, "error", "") or ""
        low = err.lower()
        status = OK if ok else (
            ENCRYPTED if ("password" in low or "encrypt" in low) else
            CORRUPTED if "corrupt" in low else
            EMPTY if not text.strip() else PARSE_FAILED)
        needs_ocr = (not ok) and info.needs_ocr
        return ContentResult(
            ok, status=status, text=text,
            confidence=float(getattr(res, "confidence", 0.0) or 0.0),
            truncated=len(text) >= max_chars, used_ocr=False,
            error="" if ok else (err or "no extractable text; may need OCR"
                                 if needs_ocr else err),
            source={"path": path, "format": info.fmt,
                    "engine": getattr(res, "engine", "")},
            meta={"needs_ocr": needs_ocr, "word_count": getattr(res, "word_count", 0)},
            **base)

    def _parse_image(self, path, info, base) -> ContentResult:
        # Images: OCR the text layer now; deep visual understanding (scene,
        # objects, charts) is a later phase that reuses reyes_agent.vision.
        from reyes_agent import ocr
        res = ocr.extract_image_text(path)
        text = getattr(res, "text", "") or ""
        ok = bool(getattr(res, "ok", False))
        vision_available = self._vision_available()
        return ContentResult(
            ok or vision_available, status=OK if (ok or vision_available) else EMPTY,
            text=text, confidence=float(getattr(res, "confidence", 0.0) or 0.0),
            used_ocr=True,
            error="" if (ok or vision_available) else "no readable text in the image",
            source={"path": path, "format": info.fmt},
            meta={"ocr_found_text": ok, "vision_available": vision_available,
                  "note": "OCR reads words; semantic understanding is separate "
                          "and verifiable (#12)."},
            **base)

    # -- helpers -----------------------------------------------------------
    def _resolve(self, path_or_ref: str) -> str | None:
        raw = str(path_or_ref or "").strip().strip('"').strip("'")
        if raw and Path(os.path.expanduser(raw)).exists():
            return str(Path(os.path.expanduser(raw)))
        ref = self._ctx.resolve(path_or_ref)
        return ref.path if ref.ok and ref.path else None

    @staticmethod
    def _vision_available() -> bool:
        try:
            from reyes_agent.vision.models import router as vrouter
            return bool(getattr(vrouter, "available", lambda: False)())
        except Exception:  # noqa: BLE001
            return False

    def _cache_key(self, path: str, max_chars: int) -> tuple | None:
        try:
            st = os.stat(path)
            return (path, int(st.st_mtime), int(st.st_size), int(max_chars))
        except OSError:
            return None


_engine = UniversalContentEngine()


def get_engine() -> UniversalContentEngine:
    return _engine
