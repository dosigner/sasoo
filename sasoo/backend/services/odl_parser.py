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

from models.database import DB_PATH, execute_insert, fetch_all, get_db, get_library_root
from services.document_audit import _page_text_map, find_suspect_pages
from services.document_manifest import build_document_manifest, resolve_paper_journal
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
GEMINI_ENGINE_NAME = "gemini"
# visual 단계 Gemini 파서의 토큰/비용 집계를 _run_convert(mock 경계)를 건드리지 않고
# _run_convert_gemini → ensure_visual_artifacts로 끌어올리기 위한 out-of-band 채널.
# 전 호출 경로가 동기·단일 스레드(executor 스레드)라 thread-local이면 논문 병렬 파싱에도 안전하다.
_visual_parse_usage_channel = threading.local()
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
IMAGE_ELEMENT_TYPES = {"image", "picture"}
TEXTUAL_FIGURE_TYPES = {"caption", "paragraph", "list item", "text block", "heading"}
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


# (java 실행 파일 경로 → 동작 여부) 검증 결과 캐시. `java -version` subprocess 프로브는
# 비용이 있으므로 경로별 결과를 모듈 레벨에 캐싱해 반복 호출을 없앤다. 테스트는
# 이 dict를 clear()해 프로브를 다시 강제할 수 있다.
_JAVA_VALIDATION_CACHE: dict[str, bool] = {}
_JAVA_PROBE_TIMEOUT_SECONDS = 10.0


def _java_executable_works(java_exe: str | Path) -> bool:
    """`java -version`을 실제로 실행해 이 java 실행 파일이 동작하는지 검증한다.

    macOS는 JDK가 없어도 `/usr/bin/java` 스텁을 제공하는데, 이 스텁은 실행 시
    "Unable to locate a Java Runtime. Please visit http://www.java.com ..."를 stderr로
    내고 종료코드 1로 죽는다. 따라서 존재 여부(exists())만으로는 스텁을 걸러낼 수 없고,
    반드시 실행해 종료코드 0을 확인해야 한다.

    - GUI 다이얼로그/입력 대기를 유발하지 않도록 stdin=DEVNULL과 timeout으로 감싼다.
    - 프로브 비용을 없애기 위해 (경로→bool)을 모듈 레벨에 캐싱한다.
    """
    key = str(java_exe)
    cached = _JAVA_VALIDATION_CACHE.get(key)
    if cached is not None:
        return cached

    ok = False
    try:
        if Path(key).exists():
            proc = subprocess.run(
                [key, "-version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=_JAVA_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
            ok = proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False

    _JAVA_VALIDATION_CACHE[key] = ok
    return ok


def _java_runtime_unavailable_message() -> str:
    return (
        "표·그림 추출에 필요한 Java 실행 환경을 찾지 못했습니다. "
        "동작하는 Java 11+ 런타임을 설치하거나 `backend/java-runtime`에 번들 런타임을 두세요. "
        "(GEMINI_API_KEY가 설정돼 있으면 Gemini 엔진으로 자동 대체됩니다.)"
    )


def ensure_java_runtime() -> str:
    """
    Ensure Java is available for OpenDataLoader.
    Returns the java executable path.

    후보 java 실행 파일은 반드시 `java -version`으로 실제 동작을 검증한 뒤에만 반환한다.
    검증 없이 반환하면 macOS의 `/usr/bin/java` 스텁을 유효한 java로 오인해, 서드파티
    wrapper가 PATH의 "java"(=스텁)를 실행 → exit 1 + java.com 안내가 표/그림 오류로 노출된다.
    """
    _ensure_java_tool_options()
    for candidate in _runtime_candidates():
        if candidate.exists():
            java_exe = _java_executable_for_home(candidate)
            if java_exe.exists() and _java_executable_works(java_exe):
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
    if java_on_path and _java_executable_works(java_on_path):
        # PATH의 java가 실제로 동작할 때만 반환한다. 스텁(exit≠0)은 여기서 거부되어
        # 아래 OdlRuntimeError로 떨어진다(그러면 text는 PyMuPDF, visual은 Gemini로 대체).
        return java_on_path

    raise OdlRuntimeError(_java_runtime_unavailable_message())


def _java_runtime_available() -> bool:
    """`ensure_java_runtime`이 예외 없이 동작하는(=실제 실행 가능한 java가 있는) 경우 True.

    검증 통과 시 ensure_java_runtime의 부수효과(PATH prepend + JAVA_HOME)가 그대로 적용되어,
    이후 ODL 엔진이 선택되면 번들 java가 실제로 실행된다. 결과 자체는 검증 캐시로 저렴하다.
    """
    try:
        ensure_java_runtime()
        return True
    except OdlRuntimeError:
        return False


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
    # "[]" 같은 문자 없는 플레이스홀더 메타데이터는 저자명으로 취급하지 않는다.
    author_text = _maybe_text(root.get("author"))
    author = author_text if re.search(r"[^\W\d_]", author_text) else None
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

    journal = resolve_paper_journal(full_text[:2000])

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
    page_count = metadata.get("page_count") or len(manifest.get("pages", []))

    # F4: gemini slim 스키마에선 트리에 본문 paragraph가 없어(heading/caption만) pages[*].text_blocks
    # 가 본문을 담지 못한다 → 아래 text_blocks 경로로 {stem}.json을 만들면 본문이 공동화되어
    # 자매 파일 {stem}.md(=full_text)와 본문이 어긋난다. gemini는 full_text가 완전한 본문
    # (페이지 마커 포함 markdown)이므로, 이를 페이지별로 쪼개 paragraph 노드로 복원해 텍스트 계약이
    # 본문을 갖게 한다(.md와 .json의 본문 일치). ODL/pymupdf 경로는 기존 text_blocks 로직 불변.
    engine = str(manifest.get("engine") or "").strip().lower()
    full_text = str(manifest.get("full_text") or "")
    if engine == GEMINI_ENGINE_NAME and full_text.strip():
        page_map = _page_text_map(full_text)  # document_audit과 동일한 "--- Page N ---" 분할
        if page_map:
            gemini_kids: list[dict[str, Any]] = []
            for page_number in sorted(page_map):
                text = _maybe_text(page_map[page_number])
                if not text:
                    continue
                gemini_kids.append(
                    {"type": "paragraph", "page number": page_number, "content": text}
                )
            if gemini_kids:
                return {
                    "title": metadata.get("title"),
                    "author": metadata.get("authors"),
                    "number of pages": page_count,
                    "kids": gemini_kids,
                }

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
        "number of pages": page_count,
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


_VALID_ENGINES = {"odl", GEMINI_ENGINE_NAME}
DEFAULT_TEXT_ENGINE = "odl"
DEFAULT_VISUAL_ENGINE = GEMINI_ENGINE_NAME


def _normalize_engine(value: str | None, default: str) -> str:
    selected = (value or "").strip().lower()
    return selected if selected in _VALID_ENGINES else default


def _resolve_stage_engine(stage: str, engine_override: str | None = None) -> str:
    """스테이지(text/visual)별 파서 엔진을 한 곳에서 결정한다.

    우선순위:
      1. engine_override — 함수 인자(파일럿/폴백 강제)
      2. 전역 SASOO_PDF_ENGINE — 하위호환. 있으면 두 스테이지 모두를 덮어쓴다.
      3. 스테이지 env — SASOO_PDF_TEXT_ENGINE / SASOO_PDF_VISUAL_ENGINE
      4. 스테이지 기본 — text=odl(즉시성/축자), visual=gemini(수식·표·읽기순서)
    부수효과 없음 — 키 존재 검사·다운그레이드는 _run_convert 디스패치 지점에서만 한다.
    """
    if engine_override:
        return _normalize_engine(engine_override, default=DEFAULT_TEXT_ENGINE)
    global_override = os.environ.get("SASOO_PDF_ENGINE")
    if global_override and global_override.strip():
        return _normalize_engine(global_override, default=DEFAULT_TEXT_ENGINE)
    if stage == "visual":
        return _normalize_engine(os.environ.get("SASOO_PDF_VISUAL_ENGINE"), default=DEFAULT_VISUAL_ENGINE)
    return _normalize_engine(os.environ.get("SASOO_PDF_TEXT_ENGINE"), default=DEFAULT_TEXT_ENGINE)


def _resolve_pdf_engine(engine: str | None) -> str:
    """하위호환 별칭: 명시 인자 > 전역 SASOO_PDF_ENGINE > "odl" (스테이지 무관)."""
    return _resolve_stage_engine("text", engine)


def _run_convert(
    pdf_path: Path,
    output_dir: Path,
    figures_dir: Path,
    mode: str,
    engine: str | None = None,
    stage: str = "text",
) -> tuple[dict[str, Any], str, str]:
    """엔진 디스패처. 반환 계약 (root_json, markdown_text, actual_engine)은 엔진 불문 동일.

    스테이지(text/visual)별로 _resolve_stage_engine이 엔진을 고른다. gemini로 결정됐지만
    GEMINI_API_KEY가 없으면 조용히 ODL로 내려간다(경고 1줄) — 페이지별 재시도 폭주를 피한다.
    gemini 실행 실패는 _run_convert_gemini가 OdlParserError로 변환한다(상위 폴백 체인이 처리).
    이 저수준 디스패처는 자동 폴백을 하지 않는다 — 폴백은 프로덕션 경로(ensure_visual_artifacts)가 담당.
    """
    selected = _resolve_stage_engine(stage, engine)
    if selected == GEMINI_ENGINE_NAME and not (os.environ.get("GEMINI_API_KEY") or "").strip():
        logger.warning(
            "GEMINI_API_KEY not set; %s stage falling back to ODL parser engine.", stage
        )
        selected = "odl"
    if selected == GEMINI_ENGINE_NAME:
        return _run_convert_gemini(pdf_path, output_dir, figures_dir)
    return _run_convert_odl(pdf_path, output_dir, figures_dir, mode)


def _visual_runtime_unavailable_message() -> str:
    return (
        "표·그림 추출에 Java 실행 환경 또는 Gemini API 키가 필요합니다. "
        "동작하는 Java 런타임(backend/java-runtime)이 없고 GEMINI_API_KEY도 설정돼 있지 않습니다."
    )


def _plan_visual_engines() -> list[str]:
    """visual 단계에서 시도할 엔진을 우선순위대로 반환한다(빈 리스트 = 가용 엔진 없음).

    - 스테이지 기본 엔진(_resolve_stage_engine("visual"))을 먼저, 실패 대비로 반대 엔진을 뒤에.
    - gemini는 GEMINI_API_KEY가 있을 때만 후보에 넣는다. (없으면 _run_convert가 내부적으로
      ODL로 downgrade해 스텁 java 에러를 만들 뿐이므로 애초에 시도하지 않는다.)
    - odl은 ensure_java_runtime 검증이 통과할 때만 후보에 넣는다. (스텁 오탐지 시 굳이
      시도해 java.com 에러를 만들지 말고 건너뛰어 Gemini로 넘어간다.)

    이 순서화가 "Java가 안 되면 Gemini로, Gemini가 안 되면 Java로"의 양방향 폴백을 만든다.
    """
    stage_default = _resolve_stage_engine("visual")
    ordered = [stage_default] + [
        engine for engine in (GEMINI_ENGINE_NAME, "odl") if engine != stage_default
    ]
    gemini_ok = bool((os.environ.get("GEMINI_API_KEY") or "").strip())
    java_ok = _java_runtime_available()

    plan: list[str] = []
    for engine in ordered:
        if engine == GEMINI_ENGINE_NAME and not gemini_ok:
            continue
        if engine == "odl" and not java_ok:
            continue
        plan.append(engine)
    return plan


def _run_convert_odl(pdf_path: Path, output_dir: Path, figures_dir: Path, mode: str) -> tuple[dict[str, Any], str, str]:
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


def _run_convert_gemini(pdf_path: Path, output_dir: Path, figures_dir: Path) -> tuple[dict[str, Any], str, str]:
    """Gemini 비전 엔진 어댑터. 비동기 run_convert_gemini를 기존 동기 브리지로 감싸고,
    실패는 OdlParserError로 변환해 폴백이 ODL 실패와 동일하게 동작하도록 한다.

    상위 ensure_visual_artifacts가 채널에 빈 usage dict를 심어두면, 그 dict를 그대로
    run_convert_gemini(usage_out=...)로 넘겨 토큰/비용 집계를 채운다. dict은 참조로
    전달되므로 _run_coroutine_sync의 자식 스레드에서 채워도 join 후 상위에서 보인다.
    채널이 비어 있으면(text 단계 등) None을 넘겨 아무것도 집계하지 않는다."""
    from services.gemini_parser import GeminiParserError, run_convert_gemini

    usage_out = getattr(_visual_parse_usage_channel, "usage", None)
    try:
        return _run_coroutine_sync(
            run_convert_gemini(pdf_path, output_dir, figures_dir, usage_out=usage_out)
        )
    except GeminiParserError as exc:
        raise OdlParserError(f"Gemini parser engine failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - F1: 비-GeminiParserError도 폴백 대상으로 변환
        # gemini 경로가 GeminiParserError가 아닌 예외(예: fitz.open의 raw RuntimeError,
        # _run_coroutine_sync 스레드에서 새어나온 임의 예외)를 던지면, ensure_visual_artifacts의
        # 폴백(except OdlParserError)이 이를 못 잡아 아티팩트 태스크가 통째로 실패하고
        # explain_odl_failure가 엔진을 오귀속("OpenDataLoader failed: ...")한다. 이 초크포인트에서
        # 모든 gemini-경로 예외를 OdlParserError로 감싸(원인 체이닝) 폴백이 ODL 실패와 동일하게 동작.
        raise OdlParserError(f"Gemini parser engine failed: {exc}") from exc


# 서드파티 wrapper/JVM 스텁이 내는 "java 미탐지" 신호. 이 문자열이 보이면 실제 ODL 파싱
# 실패가 아니라 Java 실행 환경이 없다는 뜻이므로, raw java.com 안내 대신 한국어 안내를 준다.
_JAVA_MISSING_SIGNATURES = (
    "www.java.com",
    "unable to locate a java runtime",
    "'java' command not found",
    "java command not found",
    "no java runtime present",
)


def _looks_like_java_missing(text: str | None) -> bool:
    lowered = (text or "").lower()
    return any(signature in lowered for signature in _JAVA_MISSING_SIGNATURES)


def _java_missing_user_message() -> str:
    return (
        "표·그림 추출에 Java 실행 환경 또는 Gemini API 키가 필요합니다. "
        "Java 런타임이 설치돼 있지 않거나 실행되지 않았습니다. "
        "Java 11+를 설치하거나 GEMINI_API_KEY를 설정하면 표·그림을 추출할 수 있습니다."
    )


def _convert_error_message(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        output = exc.stderr or exc.stdout or exc.output
        if _looks_like_java_missing(output if isinstance(output, str) else None):
            # 스텁 java가 exit≠0으로 죽은 경우 — 파싱 실패가 아니라 런타임 부재.
            return _java_missing_user_message()
        details: list[str] = [f"OpenDataLoader convert failed with exit code {exc.returncode}."]
        if output:
            last_line = output.strip().splitlines()[-1][:400]
            details.append(last_line)
        return " ".join(details)
    if _looks_like_java_missing(str(exc)):
        # wrapper가 던지는 FileNotFoundError("Error: 'java' command not found ...") 등.
        return _java_missing_user_message()
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


def _prune_orphan_figure_files(paper_dir: Path, figures: list[dict[str, Any]]) -> None:
    """최종 매니페스트가 참조하지 않는 figures/*.png를 지운다.

    resolve 패스는 후보를 고를 때마다 크롭 PNG를 쓰는데, 재시도 패스가 같은 페이지를
    다시 해석하면 이전 패스의 크롭은 매니페스트에서 밀려나고도 디스크에 그대로 남는다
    (실측: figures 21개인 논문의 figures/ 폴더에 PNG 41개). 라이브러리 용량이 새고,
    파일 목록만 보고 그림 수를 세는 곳에서 오해를 만든다.

    참조되는 파일만 남기고 지운다. 디렉터리 안의 .png만 대상으로 하며, 삭제 실패는
    무시한다 — 청소는 아티팩트 생성을 실패시킬 사유가 아니다.
    """
    figures_dir = paper_dir / "figures"
    if not figures_dir.is_dir():
        return

    referenced: set[Path] = set()
    for figure in figures:
        file_path = figure.get("file_path")
        if not file_path:
            continue
        path = Path(file_path)
        candidate = path if path.is_absolute() else (paper_dir / path)
        try:
            referenced.add(candidate.resolve())
        except OSError:
            continue

    for existing in figures_dir.glob("*.png"):
        try:
            if existing.resolve() in referenced:
                continue
            existing.unlink()
        except OSError as exc:  # noqa: PERF203 - 개별 실패가 나머지 청소를 막지 않는다
            logger.debug("고아 크롭 정리 실패 %s: %s", existing, exc)


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

    # gemini 파서가 못 읽어 PyMuPDF 텍스트로 메운 페이지는 caption/image 요소가 없다.
    # audit은 본문 텍스트 기준이라 이런 페이지를 놓칠 수 있으므로 명시적으로 suspect에 넣어
    # aggressive 후보 재생성을 태운다(pymupdf image 블록은 파서와 무관하게 살아 있다).
    parser_failed_pages = {
        page for page in (manifest.get("parser_failed_pages") or []) if isinstance(page, int)
    }
    if parser_failed_pages:
        suspect_pages |= parser_failed_pages
        audit["suspect_pages"] = sorted(suspect_pages)
        audit["triggered"] = True
        audit["reason"] = audit.get("reason") or "parser_page_failure"

    # 재시도 패스 병합: 예전에는 (1) low_confidence 재시도와 (2) audit suspect 재시도가
    # 그림·표 각각 따로 돌아 문서당 최대 6번의 resolve 패스가 나갔다. 두 페이지 집합을
    # 합쳐 한 번만 재시도하면 최대 4패스로 줄고, 커버리지는 합집합이라 이전 이상이다.
    #
    # audit은 여전히 표 resolve 이후에 계산한다 — find_suspect_pages가 tables /
    # table_candidates를 실제로 읽어 판정하므로(document_audit.py) 앞당기면 판정이 달라진다.
    # 바뀐 점은 audit이 "low_confidence 재시도 이후" 대신 "1차 결과" 기준이라는 것뿐이며,
    # 그래서 suspect가 더 넓게 잡힐 수는 있어도 좁아지지는 않는다.
    retry_figure_pages = low_figure_pages | suspect_pages
    retry_table_pages = low_table_pages | suspect_pages

    if retry_figure_pages:
        regenerated_figures = build_figure_candidates(
            manifest,
            pdf_path=pdf_path,
            page_numbers=retry_figure_pages,
            aggressive=True,
        )
        manifest["figure_candidates"] = _merge_page_scoped_items(
            manifest.get("figure_candidates", []),
            regenerated_figures,
            retry_figure_pages,
        )
        retried_figures = await resolve_figure_candidates(
            manifest,
            paper_dir=paper_dir,
            pdf_path=pdf_path,
            resolver_version=RESOLVER_VERSION,
            page_numbers=retry_figure_pages,
        )
        manifest["figures"] = _merge_page_scoped_items(
            manifest.get("figures", []),
            retried_figures["figures"],
            retry_figure_pages,
        )

    if retry_table_pages:
        regenerated_tables = build_table_candidates(
            manifest,
            pdf_path=pdf_path,
            paper_dir=paper_dir,
            page_numbers=retry_table_pages,
            aggressive=True,
        )
        manifest["table_candidates"] = _merge_page_scoped_items(
            manifest.get("table_candidates", []),
            regenerated_tables,
            retry_table_pages,
        )
        retried_tables = await resolve_table_candidates(
            manifest,
            paper_dir=paper_dir,
            resolver_version=RESOLVER_VERSION,
            page_numbers=retry_table_pages,
        )
        manifest["tables"] = _merge_page_scoped_items(
            manifest.get("tables", []),
            retried_tables["tables"],
            retry_table_pages,
        )

    _prune_orphan_figure_files(paper_dir, manifest.get("figures", []))

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


def _promote_text_from_visual(
    paper_dir: Path,
    manifest: dict[str, Any],
    *,
    odl_reference_snapshot: str | None,
    visual_engine: str,
) -> bool:
    """visual 단계가 gemini로 성공하면, 그 변환 markdown(=manifest['full_text'])을 text
    아티팩트로 승격한다. Gemini를 재호출하지 않는다 — 1회 변환으로 두 용도(figure/caption + 본문).

    - odl_reference_snapshot(삭제되기 전에 캡처한 text 스테이지 .md 원문)이 있으면
      {stem}.odl-reference.md로 보존한다. 멱등의 핵심은 스냅샷 유무다: 재실행(force, PDF 불변)
      에선 text 스테이지가 이미 gemini current라 스냅샷이 None → 레퍼런스 불변(gemini 텍스트로
      덮어쓰는 사고 없음). PDF가 바뀌면 text가 ODL을 재생성 → 스냅샷 갱신 → 레퍼런스도 새
      PDF 기준으로 갱신된다.
    - .document_context.json 사이드카를 무효화(삭제)한다. 이 사이드카는 pdf서명+parser_version
      으로만 current 판정하므로, full_text가 ODL→gemini로 바뀌어도 자동 갱신되지 않는다.
    - manifest에 provenance(text_engine/visual_engine)를 기록한다.

    반환: 승격 시 True — 호출부가 .md/.json 계약 파일을 overwrite로 다시 쓰게 한다. 승격 아님
    (ODL visual 또는 폴백)이면 False + 필드/파일 불변으로 기존 ODL-only 경로 바이트를 유지한다.

    설계 노트(코드리뷰 F3, 미수정=의도된 설계): 승격은 본문 텍스트 계약(full_text/{stem}.md/.json)을
    Gemini 전사본으로 교체하므로, 하류 인용·정량 분석은 ODL 축자 텍스트가 아니라 Gemini 전사
    기준으로 수행된다(Gemini는 저자명·grant번호·수치를 산발 변조할 수 있다). 이는 수식·표·읽기순서
    품질을 위해 받아들인 트레이드오프이며, 축자 원문은 {stem}.odl-reference.md로 보존된다
    (get_odl_reference_text). 인용 검증을 레퍼런스에 배선하는 작업은 별도 보류 과제다.
    """
    if visual_engine != GEMINI_ENGINE_NAME:
        return False

    stem = Path(str(manifest.get("pdf_file") or _paper_pdf(paper_dir).name)).stem
    ref_path = paper_dir / f"{stem}.odl-reference.md"
    # ODL 원문 보존: 스냅샷이 있을 때만(=이번 사이클에 text 스테이지가 ODL 원문을 새로 만든 경우)
    # 기록/갱신. 재실행(force, PDF 불변)에선 스냅샷=None → 레퍼런스 불변(멱등).
    if odl_reference_snapshot:
        ref_path.write_text(odl_reference_snapshot, encoding="utf-8")

    # stale 파생 캐시 무효화(지연 import로 순환참조 회피).
    from services.document_context import DOCUMENT_CONTEXT_FILENAME

    (paper_dir / DOCUMENT_CONTEXT_FILENAME).unlink(missing_ok=True)

    manifest["text_engine"] = GEMINI_ENGINE_NAME
    manifest["visual_engine"] = visual_engine
    return True


def get_odl_reference_text(paper_dir: Path) -> str | None:
    """승격된 논문의 ODL 축자 레퍼런스({stem}.odl-reference.md) 텍스트를 반환.

    visual 단계가 gemini로 승격되면 원래 ODL .md가 이 파일로 보존된다(환각 0·축자 충실).
    gemini는 축자 어휘/저자명/grant번호를 산발 변조하므로, 인용·정량 축자 검증 시 이 레퍼런스를
    교차 확인용으로 쓴다. 승격되지 않았거나 파일이 없으면 None.
    """
    paper_dir = Path(paper_dir)
    try:
        pdf_stem = _paper_pdf(paper_dir).stem
    except FileNotFoundError:
        return None
    ref_path = paper_dir / f"{pdf_stem}.odl-reference.md"
    if not ref_path.exists():
        return None
    try:
        return ref_path.read_text(encoding="utf-8")
    except OSError:
        return None


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
        root, markdown_text, actual_engine = _run_convert(
            pdf_path, output_dir, raw_image_dir, requested_mode, stage="text"
        )
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

    # 승격 대비: text 스테이지가 어떤 엔진으로 현재 .md를 만들었는지(디스크 manifest 기준).
    # 아래 clear 단계가 text 스테이지 .md를 지우므로, ODL 원문을 메모리로 먼저 스냅샷한다.
    # text 스테이지가 이미 gemini(전역 오버라이드/재실행 current)면 보존할 ODL 원문이 없으므로
    # 스냅샷을 남기지 않는다 → 승격 시 gemini 텍스트가 레퍼런스를 오염시키지 않는다(멱등).
    text_stage_manifest = _load_manifest(paper_dir)
    text_stage_engine = str((text_stage_manifest or {}).get("engine", "")).strip().lower()
    md_path = paper_dir / f"{pdf_path.stem}.md"
    odl_reference_snapshot: str | None = None
    if text_stage_engine != GEMINI_ENGINE_NAME and md_path.exists():
        try:
            odl_reference_snapshot = md_path.read_text(encoding="utf-8")
        except OSError:
            odl_reference_snapshot = None

    output_dir = paper_dir
    raw_image_dir = paper_dir / RAW_IMAGE_DIRNAME
    shutil.rmtree(raw_image_dir, ignore_errors=True)
    raw_image_dir.mkdir(parents=True, exist_ok=True)
    for output_file in (output_dir / f"{pdf_path.stem}.json", output_dir / f"{pdf_path.stem}.md"):
        if output_file.exists():
            output_file.unlink()

    # visual 단계 Gemini 파서의 usage를 담을 빈 dict를 채널에 심는다. 실제 gemini 변환이
    # 일어날 때만 채워지고, ODL 폴백/키 부재/캐시 히트에선 빈 채로 남는다(→ 미기록).
    _visual_parse_usage_channel.usage = {}
    try:
        # 프로덕션 폴백(양방향): 가용한 엔진을 우선순위대로 시도한다. 기본 엔진이 실패하면
        # 아직 안 써본 반대 엔진으로 넘어가 사용자 눈엔 visual이 그냥 되게 한다.
        #   - Java가 안 되면 odl은 계획에서 빠지고 Gemini(키 있을 때)로 넘어간다.
        #   - Gemini가 안 되면(키 부재/변환 실패) Java(검증 통과 시)로 넘어간다.
        # _run_convert 저수준 디스패처는 불변 — 여기서만 engine을 명시해 엔진을 강제한다.
        # 스테이지 기본 엔진은 engine=None으로 넘겨 _resolve_stage_engine 의미를 그대로 태운다.
        engine_plan = _plan_visual_engines()
        if not engine_plan:
            raise OdlRuntimeError(_visual_runtime_unavailable_message())
        stage_default = _resolve_stage_engine("visual")
        root = markdown_text = actual_engine = None  # type: ignore[assignment]
        last_error: Exception | None = None
        for attempt_index, engine_name in enumerate(engine_plan):
            if attempt_index > 0:
                # 각 엔진 재시도 전 raw 이미지 디렉터리를 청소해 부분 결과 오염을 막는다.
                shutil.rmtree(raw_image_dir, ignore_errors=True)
                raw_image_dir.mkdir(parents=True, exist_ok=True)
            engine_override = None if engine_name == stage_default else engine_name
            try:
                root, markdown_text, actual_engine = _run_convert(
                    pdf_path,
                    output_dir,
                    raw_image_dir,
                    requested_mode,
                    stage="visual",
                    engine=engine_override,
                )
                break
            except (OdlParserError, OdlRuntimeError) as exc:
                last_error = exc
                logger.warning(
                    "Visual parser engine '%s' failed for %s; trying next engine: %s",
                    engine_name,
                    paper_dir.name,
                    exc,
                )
        else:
            # 계획한 모든 엔진이 실패 → 마지막 예외를 그대로 던진다(사용자 대면 메시지는
            # _run_convert/_convert_error_message가 Java 미탐지면 한국어로 이미 변환).
            raise last_error if last_error is not None else OdlRuntimeError(
                _visual_runtime_unavailable_message()
            )
    finally:
        visual_parse_usage = getattr(_visual_parse_usage_channel, "usage", None)
        _visual_parse_usage_channel.usage = None
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
    # visual이 gemini로 성공했으면 그 변환 markdown을 text 아티팩트로 승격(+ ODL 원문 보존
    # + document_context 사이드카 무효화 + provenance 기록). ODL visual/폴백이면 no-op(False).
    promoted = _promote_text_from_visual(
        paper_dir,
        manifest,
        odl_reference_snapshot=odl_reference_snapshot,
        visual_engine=actual_engine,
    )
    _ensure_text_contract_files(paper_dir, manifest, overwrite=promoted)
    _write_cache_files(paper_dir, manifest)
    _write_manifest(paper_dir, manifest)
    # gemini visual 파서가 실제로 돌아 usage가 채워졌을 때만, 디스크 영속(_write_manifest)
    # 이후에 인메모리 전용 키로 얹는다. 디스크에 남기지 않으므로 캐시 히트 경로(상단 조기 반환)의
    # manifest엔 이 키가 없고, 상위(_refresh_paper_artifacts)가 이 키 유무로 1회 기록을 판정한다.
    if visual_parse_usage and visual_parse_usage.get("engine") == GEMINI_ENGINE_NAME:
        manifest["_visual_parse_usage"] = visual_parse_usage
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


async def _record_visual_parse_usage(paper_id: int, usage: dict[str, Any]) -> None:
    """visual 단계 Gemini 파서의 토큰/비용을 기존 analysis_results 원장에 1회 집계 기록.

    phase는 분석 파이프라인의 "visual"(도표 텍스트 분석)과 충돌하지 않도록 "visual_parse".
    분석 단계들과 동일하게 (model, tokens_in, tokens_out)로 calc_cost를 재계산해 원장 관례를
    맞춘다. 기록은 best-effort — DB 미가용/오류로 파이프라인을 깨지 않는다(경고만 남기고 스킵)."""
    try:
        model = str(usage.get("model") or "")
        tokens_in = int(usage.get("tokens_in", 0) or 0)
        tokens_out = int(usage.get("tokens_out", 0) or 0)
        if tokens_in <= 0 and tokens_out <= 0:
            return

        from services.pricing import calc_cost
        from services.document_context import compute_input_hash

        cost = calc_cost(model, tokens_in, tokens_out)
        result_payload = json.dumps(
            {
                "engine": usage.get("engine"),
                "model": model,
                "pages": usage.get("pages"),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_thought": usage.get("tokens_thought"),
            },
            ensure_ascii=False,
        )
        await execute_insert(
            """
            INSERT INTO analysis_results
                (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd, input_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                "visual_parse",
                result_payload,
                model,
                tokens_in,
                tokens_out,
                cost,
                compute_input_hash(f"visual_parse:{paper_id}:{usage.get('pages')}"),
            ),
        )
    except Exception:  # noqa: BLE001 - 원장 기록은 best-effort, 파이프라인을 막지 않는다
        logger.warning("visual_parse usage 기록 실패 (paper %s)", paper_id, exc_info=True)


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
    # 인메모리 전용 usage 키를 걷어낸다(디스크엔 애초에 없다). 실제 gemini visual 파싱이
    # 일어난 이번 refresh에서만 존재하며, 아래에서 원장에 1회 집계 기록한다.
    visual_parse_usage = manifest.pop("_visual_parse_usage", None)
    await sync_figures_for_paper(paper_id, paper_dir, manifest=manifest)
    await sync_tables_for_paper(paper_id, paper_dir, manifest=manifest)
    if visual_parse_usage:
        await _record_visual_parse_usage(paper_id, visual_parse_usage)
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
        # OdlRuntimeError 메시지는 이미 소스에서 명확히 구성되므로 그대로 전달한다.
        return 503, str(exc)
    if isinstance(exc, OdlParserError):
        message = str(exc)
        if _looks_like_java_missing(message):
            # 실제 ODL 파싱 실패가 아니라 Java 실행 환경 부재(런타임 문제) → 503 + 한국어 안내.
            return 503, _java_missing_user_message()
        return 422, message
    if _looks_like_java_missing(str(exc)):
        return 503, _java_missing_user_message()
    return 503, f"OpenDataLoader failed: {exc}"
