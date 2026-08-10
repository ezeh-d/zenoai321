"""Lazy structured document loader with local OCR fallback."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any


class DocumentLoader:
    def __init__(self, *, chunk_chars: int = 4000, overlap: int = 300) -> None:
        self.chunk_chars = max(500, min(12000, int(chunk_chars)))
        self.overlap = max(0, min(self.chunk_chars // 3, int(overlap)))

    def load(self, value: str | Path) -> dict[str, Any]:
        path = Path(value).expanduser().resolve(strict=False)
        if not path.is_file():
            return {"ok": False, "path": str(path), "error": "file does not exist"}
        enabled = os.environ.get("ZENO_DOCLING_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
        installed = importlib.util.find_spec("docling") is not None
        if enabled and installed:
            try:
                from docling.document_converter import DocumentConverter
                converted = DocumentConverter().convert(str(path))
                text = converted.document.export_to_markdown()
                engine = "docling"
            except Exception as exc:
                text, engine = "", f"docling failed: {type(exc).__name__}: {exc}"
        else:
            text, engine = "", "existing local OCR/document parser"
        if not text:
            from reyes_agent import ocr
            result = ocr.extract_document_text(path, max_chars=200_000)
            if result.error:
                return {"ok": False, "path": str(path), "engine": engine, "error": result.error}
            text = result.text
            engine = result.engine
        chunks = self._chunks(text)
        return {"ok": bool(text.strip()), "path": str(path), "engine": engine,
                "characters": len(text), "chunks": chunks,
                "metadata": {"name": path.name, "suffix": path.suffix.casefold(), "size": path.stat().st_size}}

    def _chunks(self, text: str) -> list[dict[str, Any]]:
        text = str(text or "")
        if not text:
            return []
        chunks, start, index = [], 0, 0
        while start < len(text):
            end = min(len(text), start + self.chunk_chars)
            if end < len(text):
                boundary = max(text.rfind("\n\n", start, end), text.rfind("\n", start, end), text.rfind(" ", start, end))
                if boundary > start + self.chunk_chars // 2:
                    end = boundary
            chunks.append({"index": index, "start": start, "end": end, "text": text[start:end]})
            index += 1
            if end >= len(text):
                break
            start = max(start + 1, end - self.overlap)
        return chunks

    @staticmethod
    def status() -> dict[str, Any]:
        installed = importlib.util.find_spec("docling") is not None
        enabled = os.environ.get("ZENO_DOCLING_ENABLED", "").casefold() in {"1", "true", "yes", "on"}
        return {"state": "STANDBY" if enabled and installed else ("DEGRADED" if enabled else "DISABLED"),
                "enabled": enabled, "docling_installed": installed, "fallback": "reyes_agent.ocr", "loaded": False}
