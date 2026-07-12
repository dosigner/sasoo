"""
OpenDataLoader-based PDF parsing, caching, and figure synchronization.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import threading
from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from models.database import DB_PATH, fetch_all, get_db, get_library_root
from services.document_audit import find_suspect_pages
from services.document_manifest import build_document_manifest
from services.figure_candidates import build_figure_candidates
from services.figure_resolver import resolve_figure_candidates
from services.table_candidates import build_table_candidates
from services.table_resolver import resolve_table_candidates

from services.concurrency import run_pipeline_blocking

logger = logging.getLogger(__name__)

RESOLVER_PARSER_VERSION = "odl-v3"
RESOLVER_PIPELINE_VERSION = "resolver_v1"
DEFAULT_EXTRACTION_PIPELINE_VERSION = RESOLVER_PIPELINE_VERSION
RESOLVER_VERSION = "resolver-v1"
PYMUPDF_TEXT_ENGINE = "pymupdf-text"
TEXT_CACHE_FILENAME = ".text_cache.txt"
TEXT_CACHE_META_FILENAME = ".text_cache.meta.json"
MANIFEST_FILENAME = ".odl_manifest.json"
SUPPORTED_MODES = {"java"}
RAW_IMAGE_DIRNAME = ".odl_raw_images"
DOI_PATTERN = re.compile(r"10\.\d{4,}/[^\s]+")
YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
TITLE_NOISE_PATTERNS = [
    re.compile(r"^\s*---\s*Page\s+\d+\s*---\s*$", re.IGNORECASE),
    re.compile(r"^\s*page\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"\barxiv:\s*\S+", re.IGNORECASE),
    re.compile(r"^\s*https?://\S+\s*$", re.IGNORECASE),
    re.compile(r"^\s*\S+@\S+\s*$"),
    re.compile(r"^\s*.+\.pdf\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:[A-Za-z-]+\.){1,}[A-Za-z-]+\s*$"),
    re.compile(r"^\s*(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,.-]+\d{4}\s*$", re.IGNORECASE),
]
JOURNAL_PATTERNS = [
    r"(?:Published in|Journal of|Proceedings of)\s+(.+?)[\.\n]",
    r"(?:Nature|Science|ACS|IEEE|Optics|Applied|Physical Review)\s*\w*",
]
_artifact_tasks: dict[int, asyncio.Task[dict[str, Any]]] = {}
_artifact_task_errors: dict[int, tuple[int, str]] = {}
_artifact_tasks_lock = asyncio.Lock()


class OdlParserError(RuntimeError):
    """Base class for OpenDataLoader parsing errors."""


class OdlRuntimeError(OdlParserError):
    """Raised when the runtime is not ready for OpenDataLoader."""


def _normalize_title_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _is_noise_title_candidate(value: str | None) -> bool:
    candidate = _normalize_title_text(value)
    if not candidate:
        return True
    if len(candidate) < 8:
        return True
    if not any(char.isalpha() for char in candidate):
        return True
    return any(pattern.search(candidate) for pattern in TITLE_NOISE_PATTERNS)


def resolve_paper_title(raw_title: str | None, full_text: str, fallback: str) -> str:
    normalized_raw = _normalize_title_text(raw_title)
    if not _is_noise_title_candidate(normalized_raw):
        return normalized_raw[:200]

    for raw_line in full_text.splitlines():
        line = _normalize_title_text(raw_line)
        if _is_noise_title_candidate(line):
            continue
        return line[:200]

    fallback_title = _normalize_title_text(fallback).replace("_", " ")
    if fallback_title.lower().endswith(".pdf"):
        fallback_title = fallback_title[:-4].strip()
    return (fallback_title or "Untitled Paper")[:200]


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _runtime_candidates() -> list[Path]:
    backend_root = _backend_root()
    exe_dir = Path(sys.executable).resolve().parent
    candidates: list[Path] = []
    for value in (os.environ.get("SASOO_JAVA_HOME"), os.environ.get("JAVA_HOME")):
        if value:
            candidates.append(Path(value))
    candidates.extend(
        [
        backend_root / "java-runtime",
        backend_root / "jre",
        exe_dir / "java-runtime",
        exe_dir / "jre",
        exe_dir.parent / "java-runtime",
        exe_dir.parent / "jre",
        ]
    )
    return candidates


def _java_executable_for_home(java_home: Path) -> Path:
    name = "java.exe" if sys.platform == "win32" else "java"
    direct = java_home / "bin" / name
    if direct.exists():
        return direct
    mac_bundle = java_home / "Contents" / "Home" / "bin" / name
    if mac_bundle.exists():
        return mac_bundle
    return direct


def _ensure_java_tool_options() -> None:
    headless_flag = "-Djava.awt.headless=true"
    current = os.environ.get("JAVA_TOOL_OPTIONS", "").strip()
    if "java.awt.headless" in current:
        return
    os.environ["JAVA_TOOL_OPTIONS"] = f"{current} {headless_flag}".strip() if current else headless_flag


def ensure_java_runtime() -> str:
    """
    Ensure Java is available for OpenDataLoader.
    Returns the java executable path.
    """
    _ensure_java_tool_options()
    for candidate in _runtime_candidates():
        if candidate.exists():
            java_exe = _java_executable_for_home(candidate)
            if java_exe.exists():
                java_home = candidate
                if java_exe.parent.parent.name == "Home" and java_exe.parent.parent.parent.name == "Contents":
                    java_home = java_exe.parent.parent
                os.environ["JAVA_HOME"] = str(java_home)
                current_path = os.environ.get("PATH", "")
                java_bin = str(java_exe.parent)
                if java_bin not in current_path.split(os.pathsep):
                    os.environ["PATH"] = f"{java_bin}{os.pathsep}{current_path}" if current_path else java_bin
                return str(java_exe)

    java_on_path = shutil.which("java")
    if java_on_path:
        return java_on_path

    raise OdlRuntimeError(
        "Java runtime was not found. Install Java 11+ or bundle a runtime under "
        "`backend/java-runtime`."
    )


def get_configured_parser_mode() -> str:
    """Read the parser mode from settings, defaulting to Java mode."""
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'pdf_parser_mode' LIMIT 1"
            ).fetchone()
    except Exception:
        row = None

    mode = (row[0] if row and row[0] else "java").strip().lower() if row else "java"
    return mode if mode in SUPPORTED_MODES else "java"


def get_extraction_pipeline_version() -> str:
    """Extraction pipeline version.

    Only resolver_v1 is supported; any other stored value (e.g. a legacy row
    left over from an older database) heals to it unconditionally.
    """
    return DEFAULT_EXTRACTION_PIPELINE_VERSION


def _pdf_hash(pdf_path: Path) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with open(pdf_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:16]


def get_pdf_signature(pdf_path: Path) -> dict[str, int]:
    stat = pdf_path.stat()
    return {
        "pdf_mtime_ns": stat.st_mtime_ns,
        "pdf_size": stat.st_size,
    }


def _paper_pdf(paper_dir: Path) -> Path:
    pdf_files = sorted(paper_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF found in {paper_dir}")
    return pdf_files[0]


def _load_manifest(paper_dir: Path) -> dict[str, Any] | None:
    manifest_path = paper_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_pipeline_request(
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
) -> tuple[str, str, str, str]:
    requested_mode = (mode or get_configured_parser_mode()).strip().lower()
    if requested_mode not in SUPPORTED_MODES:
        requested_mode = "java"
    # Only resolver_v1 is supported; any requested/stored value heals to it.
    pipeline_version = get_extraction_pipeline_version()
    return requested_mode, pipeline_version, RESOLVER_PARSER_VERSION, RESOLVER_VERSION


def _artifact_path_exists(paper_dir: Path, rel_or_abs: str | None) -> bool:
    if not rel_or_abs:
        return False
    path = Path(rel_or_abs)
    if not path.is_absolute():
        path = paper_dir / path
    return path.exists()


def _cache_files_are_current(paper_dir: Path, pdf_signature: dict[str, int]) -> bool:
    cache_meta_path = paper_dir / TEXT_CACHE_META_FILENAME
    cache_path = paper_dir / TEXT_CACHE_FILENAME
    if not cache_path.exists() or not cache_meta_path.exists():
        return False
    try:
        cache_meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    return (
        cache_meta.get("pdf_mtime_ns") == pdf_signature["pdf_mtime_ns"]
        and cache_meta.get("pdf_size") == pdf_signature["pdf_size"]
    )


def _text_contract_files_are_current(paper_dir: Path, manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return False

    markdown_file = manifest.get("markdown_file")
    json_file = manifest.get("json_file")
    if markdown_file and not _artifact_path_exists(paper_dir, str(markdown_file)):
        return False
    if json_file and not _artifact_path_exists(paper_dir, str(json_file)):
        return False
    return True


def _text_manifest_matches_pdf(manifest: dict[str, Any] | None, pdf_signature: dict[str, int]) -> bool:
    if not manifest:
        return False
    if (
        manifest.get("pdf_mtime_ns") != pdf_signature["pdf_mtime_ns"]
        or manifest.get("pdf_size") != pdf_signature["pdf_size"]
    ):
        return False
    return bool(str(manifest.get("full_text", "")).strip())


def _text_manifest_is_current(
    manifest: dict[str, Any] | None,
    pdf_signature: dict[str, int],
    requested_mode: str,
    extraction_pipeline_version: str,
    parser_version: str,
    resolver_version: str,
) -> bool:
    if not _text_manifest_matches_pdf(manifest, pdf_signature):
        return False
    if not manifest:
        return False
    if manifest.get("requested_mode") != requested_mode:
        return False
    if manifest.get("extraction_pipeline_version", DEFAULT_EXTRACTION_PIPELINE_VERSION) != extraction_pipeline_version:
        return False
    if manifest.get("parser_version") != parser_version:
        return False
    if manifest.get("resolver_version", "legacy") != resolver_version:
        return False
    return True


def _visual_manifest_is_current(
    manifest: dict[str, Any] | None,
    pdf_signature: dict[str, int],
    requested_mode: str,
    extraction_pipeline_version: str,
    parser_version: str,
    resolver_version: str,
) -> bool:
    if not manifest:
        return False
    if manifest.get("parser_version") != parser_version:
        return False
    if (
        manifest.get("pdf_mtime_ns") != pdf_signature["pdf_mtime_ns"]
        or manifest.get("pdf_size") != pdf_signature["pdf_size"]
    ):
        return False
    if manifest.get("requested_mode") != requested_mode:
        return False
    if manifest.get("extraction_pipeline_version", DEFAULT_EXTRACTION_PIPELINE_VERSION) != extraction_pipeline_version:
        return False
    if manifest.get("resolver_version", "legacy") != resolver_version:
        return False
    return bool(manifest.get("visual_artifacts_ready", True))


def _visual_files_are_current(paper_dir: Path, manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return False

    for figure in manifest.get("figures", []):
        if not _artifact_path_exists(paper_dir, figure.get("file_path")):
            return False

    for table in manifest.get("tables", []):
        csv_path = table.get("csv_path")
        html_path = table.get("html_path")
        if csv_path and not _artifact_path_exists(paper_dir, csv_path):
            return False
        if html_path and not _artifact_path_exists(paper_dir, html_path):
            return False

    for page in manifest.get("pages", []):
        raster_path = page.get("raster_path")
        if raster_path and not _artifact_path_exists(paper_dir, raster_path):
            return False

    return True


def _manifest_is_current(
    paper_dir: Path,
    manifest: dict[str, Any] | None,
    pdf_signature: dict[str, int],
    requested_mode: str,
    extraction_pipeline_version: str,
    parser_version: str,
    resolver_version: str,
) -> bool:
    return (
        _text_manifest_matches_pdf(manifest, pdf_signature)
        and _cache_files_are_current(paper_dir, pdf_signature)
        and _text_contract_files_are_current(paper_dir, manifest)
        and _visual_manifest_is_current(
            manifest,
            pdf_signature,
            requested_mode,
            extraction_pipeline_version,
            parser_version,
            resolver_version,
        )
        and _visual_files_are_current(paper_dir, manifest)
    )


def paper_text_is_current(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
) -> bool:
    paper_dir = Path(paper_dir)
    pdf_path = _paper_pdf(paper_dir)
    requested_mode, pipeline_version, parser_version, resolver_version = _resolve_pipeline_request(
        mode,
        extraction_pipeline_version,
    )
    manifest = _load_manifest(paper_dir)
    pdf_signature = get_pdf_signature(pdf_path)
    return (
        _text_manifest_is_current(
            manifest,
            pdf_signature,
            requested_mode,
            pipeline_version,
            parser_version,
            resolver_version,
        )
        and _cache_files_are_current(paper_dir, pdf_signature)
        and _text_contract_files_are_current(paper_dir, manifest)
    )


def paper_visuals_are_current(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
) -> bool:
    paper_dir = Path(paper_dir)
    pdf_path = _paper_pdf(paper_dir)
    requested_mode, pipeline_version, parser_version, resolver_version = _resolve_pipeline_request(
        mode,
        extraction_pipeline_version,
    )
    manifest = _load_manifest(paper_dir)
    pdf_signature = get_pdf_signature(pdf_path)
    return (
        _visual_manifest_is_current(
            manifest,
            pdf_signature,
            requested_mode,
            pipeline_version,
            parser_version,
            resolver_version,
        )
        and _visual_files_are_current(paper_dir, manifest)
    )


def paper_artifacts_are_current(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
) -> bool:
    return paper_text_is_current(
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
    ) and paper_visuals_are_current(
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
    )


def _import_odl_module():
    try:
        return importlib.import_module("opendataloader_pdf")
    except ImportError as exc:
        raise OdlRuntimeError(
            "OpenDataLoader PDF is not installed. Install `opendataloader-pdf`."
        ) from exc


def _locate_output_file(output_dir: Path, pdf_stem: str, suffix: str) -> Path:
    direct = output_dir / f"{pdf_stem}{suffix}"
    if direct.exists():
        return direct

    matches = sorted(output_dir.rglob(f"*{suffix}"))
    if matches:
        for match in matches:
            if match.stem == pdf_stem:
                return match
        return matches[0]

    raise OdlParserError(f"OpenDataLoader did not produce a {suffix} file.")


def _maybe_text(text: Any) -> str:
    return text.strip() if isinstance(text, str) else ""


def _maybe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_metadata(root: dict[str, Any], full_text: str, pdf_path: Path) -> dict[str, Any]:
    title = resolve_paper_title(_maybe_text(root.get("title")), full_text, pdf_path.stem)
    author = _maybe_text(root.get("author")) or None
    creation_date = _maybe_text(root.get("creation_date")) or _maybe_text(root.get("creation date"))

    year = None
    if creation_date:
        creation_match = YEAR_PATTERN.search(creation_date)
        if creation_match:
            year = int(creation_match.group(1))
    if year is None:
        matches = [int(match) for match in YEAR_PATTERN.findall(full_text[:3000])]
        valid = [item for item in matches if 1900 <= item <= 2100]
        if valid:
            year = max(valid)

    doi_match = DOI_PATTERN.search(full_text)
    doi = doi_match.group(0).rstrip(".,;)") if doi_match else None

    journal = None
    for pattern in JOURNAL_PATTERNS:
        match = re.search(pattern, full_text[:2000], re.IGNORECASE)
        if match:
            journal = match.group(0).strip()[:100]
            break

    return {
        "title": title[:200],
        "authors": author,
        "year": year,
        "journal": journal,
        "doi": doi,
        "page_count": _maybe_int(root.get("num_pages")) or _maybe_int(root.get("number of pages")) or 0,
    }


def _manifest_to_text_root(manifest: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(manifest.get("metadata", {}))
    kids: list[dict[str, Any]] = []
    for page in manifest.get("pages", []):
        page_number = _maybe_int(page.get("page_number")) or 1
        for block in page.get("text_blocks", []):
            text = _maybe_text(block.get("text"))
            if not text:
                continue
            node: dict[str, Any] = {
                "type": block.get("type") or "paragraph",
                "page number": page_number,
                "content": text,
            }
            if block.get("bbox") is not None:
                node["bounding box"] = block.get("bbox")
            kids.append(node)
    return {
        "title": metadata.get("title"),
        "author": metadata.get("authors"),
        "number of pages": metadata.get("page_count") or len(manifest.get("pages", [])),
        "kids": kids,
    }


def _ensure_text_contract_files(
    paper_dir: Path,
    manifest: dict[str, Any],
    *,
    overwrite: bool = False,
) -> None:
    pdf_file = manifest.get("pdf_file") or _paper_pdf(paper_dir).name
    pdf_stem = Path(str(pdf_file)).stem
    markdown_name = str(manifest.get("markdown_file") or f"{pdf_stem}.md")
    json_name = str(manifest.get("json_file") or f"{pdf_stem}.json")
    manifest["markdown_file"] = markdown_name
    manifest["json_file"] = json_name

    markdown_path = paper_dir / markdown_name
    json_path = paper_dir / json_name

    if overwrite or not markdown_path.exists():
        markdown_path.write_text(str(manifest.get("full_text", "")), encoding="utf-8")
    if overwrite or not json_path.exists():
        json_path.write_text(
            json.dumps(_manifest_to_text_root(manifest), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _build_pymupdf_text_manifest(
    pdf_path: Path,
    *,
    requested_mode: str,
    extraction_pipeline_version: str,
    parser_version: str,
    resolver_version: str,
) -> dict[str, Any]:
    doc = fitz.open(str(pdf_path))
    try:
        kids: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        full_text_parts: list[str] = []

        for page_number, page in enumerate(doc, start=1):
            text_blocks: list[dict[str, Any]] = []
            page_lines: list[str] = []
            for block_index, block in enumerate(page.get_text("blocks")):
                x0, y0, x1, y1, text = block[:5]
                clean_text = _maybe_text(text)
                if not clean_text:
                    continue
                bbox = [float(x0), float(page.rect.height - y1), float(x1), float(page.rect.height - y0)]
                text_blocks.append(
                    {
                        "id": f"txt:p{page_number}:n{block_index}",
                        "page_number": page_number,
                        "bbox": bbox,
                        "text": clean_text,
                        "type": "paragraph",
                        "source_id": None,
                        "order": block_index,
                    }
                )
                kids.append(
                    {
                        "type": "paragraph",
                        "page number": page_number,
                        "bounding box": bbox,
                        "content": clean_text,
                    }
                )
                page_lines.append(clean_text)

            pages.append(
                {
                    "page_number": page_number,
                    "page_size": {
                        "width": float(page.rect.width),
                        "height": float(page.rect.height),
                    },
                    "raster_path": None,
                    "source_parsers": [PYMUPDF_TEXT_ENGINE],
                    "text_blocks": text_blocks,
                    "image_blocks": [],
                    "caption_blocks": [],
                    "odl_table_nodes": [],
                }
            )

            page_text = "\n\n".join(page_lines).strip()
            if page_text:
                full_text_parts.append(f"--- Page {page_number} ---\n\n{page_text}")

        full_text = "\n\n".join(full_text_parts).strip()
        root = {
            "title": doc.metadata.get("title"),
            "author": doc.metadata.get("author"),
            "number of pages": len(doc),
            "kids": kids,
        }
    finally:
        doc.close()

    metadata = _extract_metadata(root, full_text, pdf_path)
    pdf_hash = _pdf_hash(pdf_path)
    pdf_signature = get_pdf_signature(pdf_path)
    return {
        "parser_version": parser_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_mode": requested_mode,
        "extraction_pipeline_version": extraction_pipeline_version,
        "resolver_version": resolver_version,
        "engine": PYMUPDF_TEXT_ENGINE,
        "pdf_hash": pdf_hash,
        "pdf_mtime_ns": pdf_signature["pdf_mtime_ns"],
        "pdf_size": pdf_signature["pdf_size"],
        "pdf_file": pdf_path.name,
        "markdown_file": f"{pdf_path.stem}.md",
        "json_file": f"{pdf_path.stem}.json",
        "metadata": metadata,
        "full_text": full_text,
        "pages": pages,
        "captions": [],
        "figure_candidates": [],
        "table_candidates": [],
        "figures": [],
        "tables": [],
        "visual_artifacts_ready": False,
        "audit": {
            "triggered": False,
            "reason": "pymupdf_text_fallback",
            "suspect_pages": [],
        },
    }


def _write_cache_files(paper_dir: Path, manifest: dict[str, Any]) -> None:
    full_text = manifest.get("full_text", "")
    pdf_hash = manifest.get("pdf_hash", "")
    engine = manifest.get("engine", "odl-java")
    pdf_mtime_ns = manifest.get("pdf_mtime_ns")
    pdf_size = manifest.get("pdf_size")
    parser_version = manifest.get("parser_version", "odl-v2")
    requested_mode = manifest.get("requested_mode", "java")
    extraction_pipeline_version = manifest.get("extraction_pipeline_version", DEFAULT_EXTRACTION_PIPELINE_VERSION)
    resolver_version = manifest.get("resolver_version", "legacy")
    (paper_dir / TEXT_CACHE_FILENAME).write_text(full_text, encoding="utf-8")
    (paper_dir / TEXT_CACHE_META_FILENAME).write_text(
        json.dumps(
            {
                "pdf_hash": pdf_hash,
                "pdf_mtime_ns": pdf_mtime_ns,
                "pdf_size": pdf_size,
                "extracted_at": time.time(),
                "char_count": len(full_text),
                "parser_version": parser_version,
                "requested_mode": requested_mode,
                "extraction_pipeline_version": extraction_pipeline_version,
                "resolver_version": resolver_version,
                "engine": engine,
            }
        ),
        encoding="utf-8",
    )


def _write_manifest(paper_dir: Path, manifest: dict[str, Any]) -> None:
    (paper_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_convert(pdf_path: Path, output_dir: Path, figures_dir: Path, mode: str) -> tuple[dict[str, Any], str, str]:
    ensure_java_runtime()
    odl = _import_odl_module()

    params: dict[str, Any] = {
        "input_path": [str(pdf_path)],
        "output_dir": str(output_dir),
        "format": "json,markdown",
        "quiet": True,
        "use_struct_tree": True,
        "image_output": "external",
        "image_dir": str(figures_dir),
    }

    actual_engine = "odl-java"

    try:
        odl.convert(**params)
    except Exception as exc:
        raise OdlParserError(_convert_error_message(exc)) from exc

    json_path = _locate_output_file(output_dir, pdf_path.stem, ".json")
    md_path = _locate_output_file(output_dir, pdf_path.stem, ".md")
    root = json.loads(json_path.read_text(encoding="utf-8"))
    markdown_text = md_path.read_text(encoding="utf-8")
    return root, markdown_text, actual_engine


def _convert_error_message(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        details: list[str] = [f"OpenDataLoader convert failed with exit code {exc.returncode}."]
        output = exc.stderr or exc.stdout or exc.output
        if output:
            last_line = output.strip().splitlines()[-1][:400]
            details.append(last_line)
        return " ".join(details)
    return f"OpenDataLoader convert failed: {exc}"


def _run_coroutine_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - surfaced to caller
            error["value"] = exc

    thread = threading.Thread(target=_runner, name="resolver-v1-sync-runner")
    thread.start()
    thread.join()
    if error:
        raise error["value"]
    return result.get("value")


def _merge_page_scoped_items(
    existing: list[dict[str, Any]],
    replacement: list[dict[str, Any]],
    page_numbers: set[int],
) -> list[dict[str, Any]]:
    kept = [
        item
        for item in existing
        if item.get("page_number") not in page_numbers
    ]
    return kept + replacement


async def _build_resolver_v1_manifest(
    *,
    paper_dir: Path,
    pdf_path: Path,
    root: dict[str, Any],
    markdown_text: str,
    actual_engine: str,
    requested_mode: str,
) -> dict[str, Any]:
    manifest = build_document_manifest(
        pdf_path=pdf_path,
        paper_dir=paper_dir,
        root=root,
        markdown_text=markdown_text,
        actual_engine=actual_engine,
        requested_mode=requested_mode,
        extraction_pipeline_version=RESOLVER_PIPELINE_VERSION,
        parser_version=RESOLVER_PARSER_VERSION,
        resolver_version=RESOLVER_VERSION,
    )

    manifest["figure_candidates"] = build_figure_candidates(manifest, pdf_path=pdf_path)
    figure_result = await resolve_figure_candidates(
        manifest,
        paper_dir=paper_dir,
        pdf_path=pdf_path,
        resolver_version=RESOLVER_VERSION,
    )
    manifest["figures"] = figure_result["figures"]

    low_figure_pages = set(figure_result.get("low_confidence_pages", []))
    if low_figure_pages:
        regenerated = build_figure_candidates(
            manifest,
            pdf_path=pdf_path,
            page_numbers=low_figure_pages,
            aggressive=True,
        )
        manifest["figure_candidates"] = _merge_page_scoped_items(
            manifest.get("figure_candidates", []),
            regenerated,
            low_figure_pages,
        )
        retried = await resolve_figure_candidates(
            manifest,
            paper_dir=paper_dir,
            pdf_path=pdf_path,
            resolver_version=RESOLVER_VERSION,
            page_numbers=low_figure_pages,
        )
        manifest["figures"] = _merge_page_scoped_items(
            manifest.get("figures", []),
            retried["figures"],
            low_figure_pages,
        )

    manifest["table_candidates"] = build_table_candidates(
        manifest,
        pdf_path=pdf_path,
        paper_dir=paper_dir,
    )
    table_result = await resolve_table_candidates(
        manifest,
        paper_dir=paper_dir,
        resolver_version=RESOLVER_VERSION,
    )
    manifest["tables"] = table_result["tables"]

    low_table_pages = set(table_result.get("low_confidence_pages", []))
    if low_table_pages:
        regenerated = build_table_candidates(
            manifest,
            pdf_path=pdf_path,
            paper_dir=paper_dir,
            page_numbers=low_table_pages,
            aggressive=True,
        )
        manifest["table_candidates"] = _merge_page_scoped_items(
            manifest.get("table_candidates", []),
            regenerated,
            low_table_pages,
        )
        retried = await resolve_table_candidates(
            manifest,
            paper_dir=paper_dir,
            resolver_version=RESOLVER_VERSION,
            page_numbers=low_table_pages,
        )
        manifest["tables"] = _merge_page_scoped_items(
            manifest.get("tables", []),
            retried["tables"],
            low_table_pages,
        )

    audit = find_suspect_pages(
        full_text=manifest.get("full_text", ""),
        pages=manifest.get("pages", []),
        figures=manifest.get("figures", []),
        tables=manifest.get("tables", []),
        figure_candidates=manifest.get("figure_candidates", []),
        table_candidates=manifest.get("table_candidates", []),
    )
    manifest["audit"] = audit
    suspect_pages = set(audit.get("suspect_pages", []))
    if suspect_pages:
        regenerated_figures = build_figure_candidates(
            manifest,
            pdf_path=pdf_path,
            page_numbers=suspect_pages,
            aggressive=True,
        )
        manifest["figure_candidates"] = _merge_page_scoped_items(
            manifest.get("figure_candidates", []),
            regenerated_figures,
            suspect_pages,
        )
        retried_figures = await resolve_figure_candidates(
            manifest,
            paper_dir=paper_dir,
            pdf_path=pdf_path,
            resolver_version=RESOLVER_VERSION,
            page_numbers=suspect_pages,
        )
        manifest["figures"] = _merge_page_scoped_items(
            manifest.get("figures", []),
            retried_figures["figures"],
            suspect_pages,
        )

        regenerated_tables = build_table_candidates(
            manifest,
            pdf_path=pdf_path,
            paper_dir=paper_dir,
            page_numbers=suspect_pages,
            aggressive=True,
        )
        manifest["table_candidates"] = _merge_page_scoped_items(
            manifest.get("table_candidates", []),
            regenerated_tables,
            suspect_pages,
        )
        retried_tables = await resolve_table_candidates(
            manifest,
            paper_dir=paper_dir,
            resolver_version=RESOLVER_VERSION,
            page_numbers=suspect_pages,
        )
        manifest["tables"] = _merge_page_scoped_items(
            manifest.get("tables", []),
            retried_tables["tables"],
            suspect_pages,
        )

    manifest["visual_artifacts_ready"] = True
    return manifest


def _build_text_manifest_from_odl(
    *,
    pdf_path: Path,
    paper_dir: Path,
    root: dict[str, Any],
    markdown_text: str,
    actual_engine: str,
    requested_mode: str,
    pipeline_version: str,
    parser_version: str,
    resolver_version: str,
) -> dict[str, Any]:
    manifest = build_document_manifest(
        pdf_path=pdf_path,
        paper_dir=paper_dir,
        root=root,
        markdown_text=markdown_text,
        actual_engine=actual_engine,
        requested_mode=requested_mode,
        extraction_pipeline_version=pipeline_version,
        parser_version=parser_version,
        resolver_version=resolver_version,
        generate_page_rasters=False,
    )
    manifest["visual_artifacts_ready"] = False
    return manifest


def ensure_text_artifacts(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure text-oriented cache and manifest files exist and are current.
    Visual artifacts are intentionally best-effort and may remain stale.
    """
    paper_dir = Path(paper_dir)
    pdf_path = _paper_pdf(paper_dir)
    requested_mode, pipeline_version, parser_version, resolver_version = _resolve_pipeline_request(
        mode,
        extraction_pipeline_version,
    )

    pdf_signature = get_pdf_signature(pdf_path)
    manifest = _load_manifest(paper_dir)
    if not force and paper_text_is_current(paper_dir):
        return manifest  # type: ignore[return-value]

    if not force and _text_manifest_is_current(
        manifest,
        pdf_signature,
        requested_mode,
        pipeline_version,
        parser_version,
        resolver_version,
    ):
        _ensure_text_contract_files(paper_dir, manifest)
        _write_cache_files(paper_dir, manifest)
        if not (paper_dir / MANIFEST_FILENAME).exists():
            _write_manifest(paper_dir, manifest)
        return manifest

    output_dir = paper_dir
    raw_image_dir = paper_dir / RAW_IMAGE_DIRNAME
    shutil.rmtree(raw_image_dir, ignore_errors=True)
    raw_image_dir.mkdir(parents=True, exist_ok=True)
    for output_file in (output_dir / f"{pdf_path.stem}.json", output_dir / f"{pdf_path.stem}.md"):
        if output_file.exists():
            output_file.unlink()

    try:
        root, markdown_text, actual_engine = _run_convert(pdf_path, output_dir, raw_image_dir, requested_mode)
        manifest = _build_text_manifest_from_odl(
            pdf_path=pdf_path,
            paper_dir=paper_dir,
            root=root,
            markdown_text=markdown_text,
            actual_engine=actual_engine,
            requested_mode=requested_mode,
            pipeline_version=pipeline_version,
            parser_version=parser_version,
            resolver_version=resolver_version,
        )
        if not str(manifest.get("full_text", "")).strip():
            raise OdlParserError("OpenDataLoader did not produce usable text.")
        _ensure_text_contract_files(paper_dir, manifest)
    except (OdlParserError, OdlRuntimeError) as exc:
        logger.warning("Falling back to PyMuPDF text ingestion for %s: %s", paper_dir.name, exc)
        manifest = _build_pymupdf_text_manifest(
            pdf_path,
            requested_mode=requested_mode,
            extraction_pipeline_version=pipeline_version,
            parser_version=parser_version,
            resolver_version=resolver_version,
        )
        _ensure_text_contract_files(paper_dir, manifest, overwrite=True)

    _write_cache_files(paper_dir, manifest)
    _write_manifest(paper_dir, manifest)
    return manifest


def ensure_visual_artifacts(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure full visual artifacts (figures, tables, rasters) exist and are current.
    """
    paper_dir = Path(paper_dir)
    pdf_path = _paper_pdf(paper_dir)
    requested_mode, pipeline_version, parser_version, resolver_version = _resolve_pipeline_request(
        mode,
        extraction_pipeline_version,
    )

    manifest = _load_manifest(paper_dir)
    pdf_signature = get_pdf_signature(pdf_path)
    if not force and _manifest_is_current(
        paper_dir,
        manifest,
        pdf_signature,
        requested_mode,
        pipeline_version,
        parser_version,
        resolver_version,
    ):
        return manifest  # type: ignore[return-value]

    ensure_text_artifacts(
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
        force=False,
    )

    output_dir = paper_dir
    raw_image_dir = paper_dir / RAW_IMAGE_DIRNAME
    shutil.rmtree(raw_image_dir, ignore_errors=True)
    raw_image_dir.mkdir(parents=True, exist_ok=True)
    for output_file in (output_dir / f"{pdf_path.stem}.json", output_dir / f"{pdf_path.stem}.md"):
        if output_file.exists():
            output_file.unlink()

    root, markdown_text, actual_engine = _run_convert(pdf_path, output_dir, raw_image_dir, requested_mode)
    manifest = _run_coroutine_sync(
        _build_resolver_v1_manifest(
            paper_dir=paper_dir,
            pdf_path=pdf_path,
            root=root,
            markdown_text=markdown_text,
            actual_engine=actual_engine,
            requested_mode=requested_mode,
        )
    )
    _ensure_text_contract_files(paper_dir, manifest)
    _write_cache_files(paper_dir, manifest)
    _write_manifest(paper_dir, manifest)
    return manifest


def ensure_parsed_artifacts(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Compatibility wrapper that ensures both text and visual artifacts.
    """
    ensure_text_artifacts(
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
        force=force,
    )
    return ensure_visual_artifacts(
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
        force=force,
    )


async def ensure_text_artifacts_async(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    return await run_pipeline_blocking(
        ensure_text_artifacts,
        paper_dir,
        mode,
        extraction_pipeline_version,
        force,
    )


async def ensure_visual_artifacts_async(
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    return await run_pipeline_blocking(
        ensure_visual_artifacts,
        paper_dir,
        mode,
        extraction_pipeline_version,
        force,
    )


def _absolute_figure_path(paper_dir: Path, rel_or_abs: str | None) -> str | None:
    if not rel_or_abs:
        return None
    path = Path(rel_or_abs)
    if path.is_absolute():
        return str(path)
    return str((paper_dir / path).resolve())


def _figure_extraction_status(figure: dict[str, Any]) -> str:
    status = figure.get("extraction_status")
    if status:
        return str(status)
    confidence = figure.get("confidence")
    try:
        return "resolved" if confidence is None or float(confidence) >= 0.85 else "uncertain"
    except (TypeError, ValueError):
        return "resolved"


def _bbox_signature(bbox: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    try:
        return tuple(round(float(value), 2) for value in bbox)
    except (TypeError, ValueError):
        return None


def _row_bbox_signature(bbox_json: Any) -> tuple[float, float, float, float] | None:
    if not bbox_json:
        return None
    try:
        return _bbox_signature(json.loads(str(bbox_json)))
    except (TypeError, json.JSONDecodeError):
        return None


def _visual_match_key(page_number: Any, bbox: Any) -> tuple[int | None, tuple[float, float, float, float] | None]:
    return _maybe_int(page_number), _bbox_signature(bbox)


def _existing_row_match_key(row: dict[str, Any]) -> tuple[int | None, tuple[float, float, float, float] | None]:
    return _maybe_int(row.get("page_number")), _row_bbox_signature(row.get("bbox_json"))


def _claim_existing_row(
    *,
    existing_by_num: dict[str, dict[str, Any]],
    existing_by_key: dict[tuple[int | None, tuple[float, float, float, float] | None], list[dict[str, Any]]],
    matched_ids: set[int],
    item_num: str | None,
    page_number: Any,
    bbox: Any,
) -> dict[str, Any] | None:
    if item_num:
        exact = existing_by_num.get(item_num)
        if exact and exact["id"] not in matched_ids:
            return exact

    key = _visual_match_key(page_number, bbox)
    if key[1] is None:
        return None

    for candidate in existing_by_key.get(key, []):
        if candidate["id"] not in matched_ids:
            return candidate
    return None


async def sync_figures_for_paper(
    paper_id: int,
    paper_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Upsert figures from the manifest into the DB while preserving AI-generated fields.
    """
    paper_dir = Path(paper_dir)
    manifest = manifest or _load_manifest(paper_dir)
    if not manifest:
        return []

    existing_rows = await fetch_all(
        """
        SELECT id, figure_num, page_number, bbox_json, ai_analysis, detailed_explanation
        FROM figures
        WHERE paper_id = ?
        """,
        (paper_id,),
    )
    existing_by_num = {row["figure_num"]: row for row in existing_rows if row.get("figure_num")}
    existing_by_key: dict[tuple[int | None, tuple[float, float, float, float] | None], list[dict[str, Any]]] = {}
    for row in existing_rows:
        existing_by_key.setdefault(_existing_row_match_key(row), []).append(row)

    figures = manifest.get("figures", [])
    db = await get_db()
    matched_ids: set[int] = set()

    for figure in figures:
        figure_num = figure.get("figure_num")
        if not figure_num:
            continue
        bbox_json = json.dumps(figure.get("bbox")) if figure.get("bbox") is not None else None
        payload = (
            figure_num,
            figure.get("caption"),
            _absolute_figure_path(paper_dir, figure.get("file_path")),
            figure.get("quality"),
            figure.get("page_number"),
            bbox_json,
            figure.get("extraction_engine"),
            figure.get("confidence"),
            figure.get("classifier_label"),
            figure.get("classifier_model"),
            1 if figure.get("is_composite") else 0,
            figure.get("resolver_version"),
            _figure_extraction_status(figure),
        )
        existing = _claim_existing_row(
            existing_by_num=existing_by_num,
            existing_by_key=existing_by_key,
            matched_ids=matched_ids,
            item_num=figure_num,
            page_number=figure.get("page_number"),
            bbox=figure.get("bbox"),
        )
        if existing:
            matched_ids.add(existing["id"])
            await db.execute(
                """
                UPDATE figures
                SET figure_num = ?, caption = ?, file_path = ?, quality = ?,
                    page_number = ?, bbox_json = ?, extraction_engine = ?,
                    confidence = ?, classifier_label = ?, classifier_model = ?,
                    is_composite = ?, resolver_version = ?, extraction_status = ?
                WHERE id = ?
                """,
                payload + (existing["id"],),
            )
        else:
            await db.execute(
                """
                INSERT INTO figures (
                    paper_id, figure_num, caption, file_path, quality,
                    page_number, bbox_json, extraction_engine, confidence,
                    classifier_label, classifier_model, is_composite,
                    resolver_version, extraction_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (paper_id,) + payload,
            )

    current_rows = await fetch_all(
        "SELECT id, figure_num FROM figures WHERE paper_id = ?",
        (paper_id,),
    )
    ids_by_num = {row["figure_num"]: row["id"] for row in current_rows if row.get("figure_num")}
    for figure in figures:
        figure_num = figure.get("figure_num")
        parent_num = figure.get("parent_figure_num")
        if not figure_num or figure_num not in ids_by_num:
            continue
        parent_id = ids_by_num.get(parent_num) if parent_num else None
        await db.execute(
            "UPDATE figures SET parent_figure_id = ? WHERE id = ?",
            (parent_id, ids_by_num[figure_num]),
        )

    stale_ids = [row["id"] for row in existing_rows if row["id"] not in matched_ids]
    if stale_ids:
        placeholders = ", ".join("?" for _ in stale_ids)
        await db.execute(
            f"DELETE FROM figures WHERE id IN ({placeholders})",
            tuple(stale_ids),
        )

    await db.commit()
    return figures


async def sync_tables_for_paper(
    paper_id: int,
    paper_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    paper_dir = Path(paper_dir)
    manifest = manifest or _load_manifest(paper_dir)
    if not manifest:
        return []

    existing_rows = await fetch_all(
        "SELECT id, table_num, page_number, bbox_json FROM tables WHERE paper_id = ?",
        (paper_id,),
    )
    existing_by_num = {row["table_num"]: row for row in existing_rows if row.get("table_num")}
    existing_by_key: dict[tuple[int | None, tuple[float, float, float, float] | None], list[dict[str, Any]]] = {}
    for row in existing_rows:
        existing_by_key.setdefault(_existing_row_match_key(row), []).append(row)
    tables = manifest.get("tables", [])
    db = await get_db()
    matched_ids: set[int] = set()

    for table in tables:
        table_num = table.get("table_num")
        if not table_num:
            continue
        bbox_json = json.dumps(table.get("bbox")) if table.get("bbox") is not None else None
        payload = (
            table_num,
            table.get("caption"),
            table.get("page_number"),
            bbox_json,
            _absolute_figure_path(paper_dir, table.get("csv_path")),
            _absolute_figure_path(paper_dir, table.get("html_path")),
            table.get("markdown_text"),
            table.get("confidence"),
            table.get("parse_method"),
            table.get("classifier_model"),
            table.get("resolver_version"),
            table.get("extraction_status") or ("resolved" if (table.get("confidence") or 0) >= 0.85 else "uncertain"),
            1 if table.get("repair_attempted") else 0,
            table.get("repair_reason"),
            table.get("repair_confidence"),
            1 if table.get("review_required") else 0,
        )
        existing = _claim_existing_row(
            existing_by_num=existing_by_num,
            existing_by_key=existing_by_key,
            matched_ids=matched_ids,
            item_num=table_num,
            page_number=table.get("page_number"),
            bbox=table.get("bbox"),
        )
        if existing:
            matched_ids.add(existing["id"])
            await db.execute(
                """
                UPDATE tables
                SET table_num = ?, caption = ?, page_number = ?, bbox_json = ?,
                    csv_path = ?, html_path = ?, markdown_text = ?, confidence = ?,
                    parse_method = ?, classifier_model = ?, resolver_version = ?,
                    extraction_status = ?, repair_attempted = ?, repair_reason = ?,
                    repair_confidence = ?, review_required = ?
                WHERE id = ?
                """,
                payload + (existing["id"],),
            )
        else:
            await db.execute(
                """
                INSERT INTO tables (
                    paper_id, table_num, caption, page_number, bbox_json,
                    csv_path, html_path, markdown_text, confidence,
                    parse_method, classifier_model, resolver_version, extraction_status,
                    repair_attempted, repair_reason, repair_confidence, review_required
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (paper_id,) + payload,
            )

    stale_ids = [row["id"] for row in existing_rows if row["id"] not in matched_ids]
    if stale_ids:
        placeholders = ", ".join("?" for _ in stale_ids)
        await db.execute(
            f"DELETE FROM tables WHERE id IN ({placeholders})",
            tuple(stale_ids),
        )

    await db.commit()
    return tables


async def _refresh_paper_artifacts(
    paper_id: int,
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    manifest = await ensure_visual_artifacts_async(
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
        force=force,
    )
    await sync_figures_for_paper(paper_id, paper_dir, manifest=manifest)
    await sync_tables_for_paper(paper_id, paper_dir, manifest=manifest)
    return manifest


def _cleanup_artifact_task(paper_id: int, task: asyncio.Task[dict[str, Any]]) -> None:
    current = _artifact_tasks.get(paper_id)
    if current is task:
        _artifact_tasks.pop(paper_id, None)
    try:
        task.result()
        _artifact_task_errors.pop(paper_id, None)
    except asyncio.CancelledError:
        _artifact_task_errors.pop(paper_id, None)
        logger.info("Paper artifact refresh cancelled for paper %s", paper_id)
    except Exception as exc:
        _artifact_task_errors[paper_id] = explain_odl_failure(exc)
        logger.exception("Paper artifact refresh failed for paper %s", paper_id)


async def _get_or_create_artifact_task(
    paper_id: int,
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> asyncio.Task[dict[str, Any]]:
    async with _artifact_tasks_lock:
        existing = _artifact_tasks.get(paper_id)
        if existing and not existing.done():
            return existing

        task = asyncio.create_task(
            _refresh_paper_artifacts(
                paper_id,
                paper_dir,
                mode=mode,
                extraction_pipeline_version=extraction_pipeline_version,
                force=force,
            ),
            name=f"ensure-paper-artifacts:{paper_id}",
        )
        _artifact_tasks[paper_id] = task
        task.add_done_callback(lambda finished: _cleanup_artifact_task(paper_id, finished))
        return task


async def ensure_paper_artifacts(
    paper_id: int,
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    task = await _get_or_create_artifact_task(
        paper_id,
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
        force=force,
    )
    return await task


async def schedule_paper_artifacts_refresh(
    paper_id: int,
    paper_dir: Path,
    mode: str | None = None,
    extraction_pipeline_version: str | None = None,
    force: bool = False,
) -> None:
    await _get_or_create_artifact_task(
        paper_id,
        paper_dir,
        mode=mode,
        extraction_pipeline_version=extraction_pipeline_version,
        force=force,
    )


def get_artifact_refresh_error(paper_id: int) -> tuple[int, str] | None:
    return _artifact_task_errors.get(paper_id)


def is_artifact_refresh_running(paper_id: int) -> bool:
    task = _artifact_tasks.get(paper_id)
    return bool(task and not task.done())


def figure_row_to_api_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert DB rows into API-friendly payloads."""
    payload = dict(row)
    bbox_json = payload.pop("bbox_json", None)
    if bbox_json:
        try:
            payload["bbox"] = json.loads(bbox_json)
        except (TypeError, json.JSONDecodeError):
            payload["bbox"] = None
    else:
        payload["bbox"] = None
    payload["file_path"] = _library_asset_to_static_url(payload.get("file_path"))
    if "is_composite" in payload:
        payload["is_composite"] = bool(payload.get("is_composite"))
    return payload


def table_row_to_api_dict(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    bbox_json = payload.pop("bbox_json", None)
    if bbox_json:
        try:
            payload["bbox"] = json.loads(bbox_json)
        except (TypeError, json.JSONDecodeError):
            payload["bbox"] = None
    else:
        payload["bbox"] = None
    payload["csv_path"] = _library_asset_to_static_url(payload.get("csv_path"))
    payload["html_path"] = _library_asset_to_static_url(payload.get("html_path"))
    if "repair_attempted" in payload:
        payload["repair_attempted"] = bool(payload.get("repair_attempted"))
    if "review_required" in payload:
        payload["review_required"] = bool(payload.get("review_required"))
    return payload


def _library_asset_to_static_url(asset_path: Any) -> Any:
    if not isinstance(asset_path, str) or not asset_path:
        return asset_path
    if asset_path.startswith("/static/library/"):
        return asset_path

    try:
        relative_path = Path(asset_path).resolve(strict=False).relative_to(
            get_library_root().resolve(strict=False)
        )
    except (TypeError, ValueError):
        return asset_path

    return f"/static/library/{quote(relative_path.as_posix(), safe='/')}"


def explain_odl_failure(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, FileNotFoundError):
        return 404, str(exc)
    if isinstance(exc, OdlRuntimeError):
        return 503, str(exc)
    if isinstance(exc, OdlParserError):
        return 422, str(exc)
    return 503, f"OpenDataLoader failed: {exc}"
