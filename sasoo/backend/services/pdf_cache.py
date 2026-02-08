"""
Sasoo - PDF Text Cache
File-based caching for extracted PDF text to avoid repeated fitz.open() calls.

Cache files are stored alongside the PDF:
  ~/sasoo-library/papers/{folder_name}/.text_cache.txt
  ~/sasoo-library/papers/{folder_name}/.text_cache.meta.json

Invalidation: SHA-256 hash of the PDF file. If the PDF changes, the cache
is automatically regenerated.
"""

import hashlib
import json
import logging
import time
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

CACHE_FILENAME = ".text_cache.txt"
CACHE_META_FILENAME = ".text_cache.meta.json"


def _pdf_hash(pdf_path: Path) -> str:
    """Return first 16 hex chars of the PDF's SHA-256."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _read_cache(paper_dir: Path, pdf_path: Path) -> str | None:
    """Return cached text if valid, else None."""
    cache_file = paper_dir / CACHE_FILENAME
    meta_file = paper_dir / CACHE_META_FILENAME

    if not cache_file.exists() or not meta_file.exists():
        return None

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if meta.get("pdf_hash") != _pdf_hash(pdf_path):
        return None  # PDF changed → invalidate

    return cache_file.read_text(encoding="utf-8")


def _write_cache(paper_dir: Path, pdf_path: Path, text: str) -> None:
    """Persist extracted text to disk."""
    cache_file = paper_dir / CACHE_FILENAME
    meta_file = paper_dir / CACHE_META_FILENAME

    cache_file.write_text(text, encoding="utf-8")
    meta_file.write_text(
        json.dumps({
            "pdf_hash": _pdf_hash(pdf_path),
            "extracted_at": time.time(),
            "char_count": len(text),
        }),
        encoding="utf-8",
    )


def _extract_full_text(pdf_path: Path) -> str:
    """Extract full text from every page of the PDF."""
    doc = fitz.open(str(pdf_path))
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "\n".join(parts)


def get_pdf_text(paper_dir: Path) -> str:
    """
    Get the full text of the PDF in *paper_dir*.

    1. Look for a valid cache file.
    2. If cache miss, extract via fitz + write cache.
    3. Return text.

    Raises FileNotFoundError if no PDF exists in paper_dir.
    """
    pdf_files = list(paper_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF found in {paper_dir}")

    pdf_path = pdf_files[0]

    # Try cache first
    cached = _read_cache(paper_dir, pdf_path)
    if cached is not None:
        logger.debug("PDF text cache HIT for %s", paper_dir.name)
        return cached

    # Cache miss → extract and save
    logger.info("PDF text cache MISS for %s — extracting...", paper_dir.name)
    text = _extract_full_text(pdf_path)
    _write_cache(paper_dir, pdf_path, text)
    return text


def warm_cache(paper_dir: Path) -> None:
    """
    Pre-populate the cache for a paper directory.
    Safe to call even if cache already exists (no-op if valid).
    """
    pdf_files = list(paper_dir.glob("*.pdf"))
    if not pdf_files:
        return

    pdf_path = pdf_files[0]
    if _read_cache(paper_dir, pdf_path) is None:
        text = _extract_full_text(pdf_path)
        _write_cache(paper_dir, pdf_path, text)
        logger.info("Warmed PDF text cache for %s (%d chars)", paper_dir.name, len(text))
