"""
SSE Stage 1 — Document Parser

Extracts raw text from uploaded source documents (.pdf, .txt, .md, .docx).
Scanned PDFs (zero extractable text) are flagged for Night School OCR ingestion.
"""
from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

_SUPPORTED_MIMES = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

_EXT_TO_FORMAT = {".pdf": "pdf", ".txt": "txt", ".md": "md", ".docx": "docx"}


def _guess_format(mime_type: str, filename: str) -> str | None:
    fmt = _SUPPORTED_MIMES.get(mime_type)
    if fmt:
        return fmt
    for ext, f in _EXT_TO_FORMAT.items():
        if filename.lower().endswith(ext):
            return f
    return None


async def parse(file_bytes: bytes, mime_type: str, filename: str) -> dict[str, Any]:
    fmt = _guess_format(mime_type, filename)
    if fmt is None:
        return {"error": "unsupported_format", "message": f"Unsupported format: {mime_type}", "filename": filename}

    if fmt == "pdf":
        return _parse_pdf(file_bytes, filename)
    if fmt == "docx":
        return _parse_docx(file_bytes, filename)
    return _parse_text(file_bytes, filename, fmt)


def _parse_pdf(file_bytes: bytes, filename: str) -> dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    page_count = len(reader.pages)
    check_pages = min(page_count, 3)
    probe_text = "".join((reader.pages[i].extract_text() or "") for i in range(check_pages))

    if len(probe_text.strip()) == 0:
        return {
            "error": "scanned_pdf_no_ocr",
            "message": "Document requires OCR preprocessing. Route to Night School ingestion.",
            "filename": filename,
            "page_count": page_count,
        }

    all_text = probe_text + "".join((reader.pages[i].extract_text() or "") for i in range(check_pages, page_count))
    return _success(all_text, "pdf", filename, page_count)


def _parse_docx(file_bytes: bytes, filename: str) -> dict[str, Any]:
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    text = "\n".join(p.text for p in doc.paragraphs)
    return _success(text, "docx", filename, page_count=None)


def _parse_text(file_bytes: bytes, filename: str, fmt: str) -> dict[str, Any]:
    text = file_bytes.decode("utf-8", errors="replace")
    return _success(text, fmt, filename, page_count=None)


def _success(raw_text: str, source_format: str, filename: str, page_count: int | None) -> dict[str, Any]:
    words = raw_text.split()
    return {
        "raw_text": raw_text,
        "word_count": len(words),
        "source_format": source_format,
        "filename": filename,
        "page_count": page_count,
    }
