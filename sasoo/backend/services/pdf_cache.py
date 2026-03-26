"""
Sasoo - PDF Text Cache
File-based caching for extracted PDF text to avoid repeated fitz.open() calls.

Cache files are stored alongside the PDF:
  ~/sasoo-library/papers/{folder_name}/.text_cache.txt
  ~/sasoo-library/papers/{folder_name}/.text_cache.meta.json

Invalidation: PDF mtime_ns + size. If the PDF changes, the cache is
automatically regenerated without re-reading the whole file on cache hits.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_FILENAME = ".text_cache.txt"
CACHE_META_FILENAME = ".text_cache.meta.json"


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

    from services.odl_parser import get_pdf_signature

    pdf_signature = get_pdf_signature(pdf_path)
    if (
        meta.get("pdf_mtime_ns") != pdf_signature["pdf_mtime_ns"]
        or meta.get("pdf_size") != pdf_signature["pdf_size"]
    ):
        return None  # PDF changed → invalidate

    return cache_file.read_text(encoding="utf-8")


def _write_cache(paper_dir: Path, pdf_path: Path, text: str) -> None:
    """Persist extracted text to disk."""
    cache_file = paper_dir / CACHE_FILENAME
    meta_file = paper_dir / CACHE_META_FILENAME
    from services.odl_parser import get_pdf_signature

    pdf_signature = get_pdf_signature(pdf_path)

    cache_file.write_text(text, encoding="utf-8")
    meta_file.write_text(
        json.dumps({
            "pdf_mtime_ns": pdf_signature["pdf_mtime_ns"],
            "pdf_size": pdf_signature["pdf_size"],
            "extracted_at": time.time(),
            "char_count": len(text),
        }),
        encoding="utf-8",
    )


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

    from services.odl_parser import ensure_text_artifacts

    logger.info("PDF text cache MISS for %s — preparing text artifacts...", paper_dir.name)
    manifest = ensure_text_artifacts(paper_dir)
    text = manifest.get("full_text", "")
    if not text:
        raise RuntimeError(f"OpenDataLoader did not produce text for {paper_dir}")
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
        from services.odl_parser import ensure_text_artifacts

        manifest = ensure_text_artifacts(paper_dir)
        logger.info(
            "Warmed text cache for %s (%d chars)",
            paper_dir.name,
            len(manifest.get("full_text", "")),
        )
