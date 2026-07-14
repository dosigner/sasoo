"""
Sasoo - Papers API Router
Endpoints for uploading, listing, retrieving, updating, and deleting papers.
"""

import json
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Final, Optional
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from models.database import (
    execute_insert,
    execute_update,
    fetch_all,
    fetch_one,
    get_db,
    get_paper_dir,
)
from models.schemas import (
    DomainType,
    AgentType,
    PaperListResponse,
    PaperResponse,
    PaperUpdate,
)
from services.odl_parser import (
    OdlParserError,
    OdlRuntimeError,
    ensure_text_artifacts_async,
    explain_odl_failure,
    resolve_paper_title,
    schedule_paper_artifacts_refresh,
)
from services.artifact_status import resolve_artifact_status_contract
from models.analysis_runs import request_cancel

router = APIRouter(prefix="/api/papers", tags=["papers"])
logger = logging.getLogger(__name__)

MAX_PDF_UPLOAD_BYTES: Final = 100 * 1024 * 1024
UPLOAD_CHUNK_BYTES: Final = 1024 * 1024

# ---------------------------------------------------------------------------
# Domain classification heuristic (fast, pre-LLM)
# ---------------------------------------------------------------------------

# 도메인 키워드와 도메인→에이전트 매핑은 에이전트 .md 레지스트리
# (backend/agents/*.md 의 frontmatter keywords/domain/name)가 단일 소스다.
# classify_domain()이 list_all_agents()로 그 키워드를 직접 스코어링한다.

_DOMAIN_NOISE_PATTERNS = [
    re.compile(r"^\s*---\s*Page\s+\d+\s*---\s*$", re.IGNORECASE),
    re.compile(r"\barxiv:\s*\S+", re.IGNORECASE),
    re.compile(r"^\s*(?:[A-Za-z-]+\.){1,}[A-Za-z-]+\s*$"),
    re.compile(r"^\s*(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s,.-]+\d{4}\s*$", re.IGNORECASE),
]


async def _get_visual_row_counts(paper_id: int) -> tuple[int, int]:
    row = await fetch_one(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM figures
                WHERE paper_id = ?
                  AND COALESCE(extraction_status, 'resolved') != 'rejected'
            ) AS figure_count,
            (
                SELECT COUNT(*)
                FROM tables
                WHERE paper_id = ?
                  AND COALESCE(extraction_status, 'resolved') != 'rejected'
            ) AS table_count
        """,
        (paper_id, paper_id),
    )
    return int(row["figure_count"] or 0), int(row["table_count"] or 0)


async def _paper_payload(
    row: dict,
    *,
    schedule_refresh: bool = False,
) -> dict:
    paper_id = int(row["id"])
    folder_name = str(row["folder_name"])
    paper_dir = get_paper_dir(folder_name)

    figure_count, table_count = await _get_visual_row_counts(paper_id)
    payload = dict(row)
    try:
        artifact_status = await resolve_artifact_status_contract(
            paper_id=paper_id,
            paper_dir=paper_dir,
            row_count=figure_count + table_count,
            schedule_if_needed=schedule_refresh,
            schedule_error_message="시각 artifact 동기화를 시작하지 못했습니다.",
        )
        payload["text_ready"] = artifact_status.text_ready
        payload["visual_ready"] = artifact_status.visual_ready
        payload["visual_state"] = artifact_status.visual_state
        payload["visual_error"] = artifact_status.visual_error
        payload["artifacts_ready"] = artifact_status.artifacts_ready
    except FileNotFoundError as exc:
        logger.warning(
            "Paper %s is missing its PDF under %s; returning degraded payload.",
            paper_id,
            paper_dir,
        )
        payload.update(_missing_pdf_payload())

    pdf_files = sorted(paper_dir.glob("*.pdf")) if paper_dir.exists() else []
    fallback_title = pdf_files[0].stem if pdf_files else str(payload.get("title") or "Untitled Paper")
    payload["title"] = resolve_paper_title(str(payload.get("title") or ""), "", fallback_title)

    return payload


def _missing_pdf_payload() -> dict[str, object]:
    return {
        "text_ready": False,
        "visual_ready": False,
        "visual_state": "error",
        "visual_error": "PDF not found",
        "artifacts_ready": False,
    }


def classify_domain(text: str) -> tuple[str, str]:
    """
    키워드 기반 도메인 분류. 에이전트 .md 레지스트리(단일 소스)의
    keywords/weighted_keywords로 점수를 매겨 (domain, agent_name)을 돌려준다.
    일치하는 키워드가 없으면 기본값(optics / photon)으로 떨어진다.
    """
    from services.agents import list_all_agents

    text_lower = text.lower()
    best_profile = None
    best_score = 0
    for profile in list_all_agents():
        if not profile.enabled:
            continue
        score = sum(1 for kw in profile.keywords if kw.lower() in text_lower)
        score += 2 * sum(1 for kw in profile.weighted_keywords if kw.lower() in text_lower)
        if score > best_score:
            best_score = score
            best_profile = profile

    if best_profile is None:
        return DomainType.OPTICS.value, AgentType.PHOTON.value
    return best_profile.domain, best_profile.agent_name


def _clean_domain_classification_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(pattern.search(line) for pattern in _DOMAIN_NOISE_PATTERNS):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=PaperResponse, status_code=201)
async def upload_paper(file: UploadFile = File(...)):
    """
    Upload a PDF file.
    1. Save the PDF to the library.
    2. Extract metadata (title, authors, year, DOI, domain).
    3. Extract figures.
    4. Insert record into the database.
    5. Return the paper record.
    """
    safe_filename = safe_pdf_filename(file.filename)
    first_chunk = await file.read(UPLOAD_CHUNK_BYTES)
    if b"%PDF-" not in first_chunk[:1024]:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF.")

    fallback_folder = f"{uuid.uuid4().hex[:12]}_{_sanitize_filename(safe_filename)}"
    paper_dir = get_paper_dir(fallback_folder)
    paper_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = paper_dir / safe_filename
    try:
        bytes_written = 0
        chunk = first_chunk
        with pdf_path.open("wb") as destination:
            while chunk:
                bytes_written += len(chunk)
                if bytes_written > MAX_PDF_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF files must not exceed 100 MB.")
                destination.write(chunk)
                chunk = await file.read(UPLOAD_CHUNK_BYTES)
    except HTTPException:
        shutil.rmtree(paper_dir, ignore_errors=True)
        raise

    try:
        manifest = await ensure_text_artifacts_async(paper_dir, force=True)
    except (OdlParserError, OdlRuntimeError, FileNotFoundError) as exc:
        shutil.rmtree(paper_dir, ignore_errors=True)
        status_code, detail = explain_odl_failure(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        shutil.rmtree(paper_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}") from exc

    metadata = dict(manifest.get("metadata", {}))
    full_text = str(manifest.get("full_text", ""))
    domain, agent = classify_domain(_clean_domain_classification_text(full_text)[:3000])
    metadata["domain"] = domain
    metadata["agent_used"] = agent

    folder_name = fallback_folder
    try:
        from services.naming_service import generate_folder_name

        suggested_name = await generate_folder_name(
            title=metadata.get("title", safe_filename),
            year=metadata.get("year"),
            journal=metadata.get("journal"),
            domain=metadata.get("domain"),
            abstract=full_text[:500],
        )
        folder_name = _make_unique_folder_name(suggested_name, fallback_folder)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Folder name generation failed, using fallback: %s", exc)

    if folder_name != fallback_folder:
        target_dir = get_paper_dir(folder_name)
        if not target_dir.exists():
            paper_dir.rename(target_dir)
            paper_dir = target_dir

    # Insert paper into DB
    paper_id = await execute_insert(
        """
        INSERT INTO papers (title, authors, year, journal, doi, domain, agent_used,
                            folder_name, tags, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            metadata["title"],
            metadata["authors"],
            metadata["year"],
            metadata["journal"],
            metadata["doi"],
            metadata["domain"],
            metadata["agent_used"],
            folder_name,
            None,  # tags
            "pending",
            None,  # notes
        ),
    )

    try:
        await schedule_paper_artifacts_refresh(paper_id, paper_dir)
    except Exception:
        logger.exception("Failed to schedule initial visual artifact refresh for paper %s", paper_id)

    # Fetch and return the created record
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created paper.")

    return PaperResponse(
        **await _paper_payload(
            paper,
        )
    )


@router.get("", response_model=PaperListResponse)
async def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
):
    """
    List papers with filtering, sorting, and pagination.
    """
    # Build WHERE clauses
    conditions: list[str] = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if domain:
        conditions.append("domain = ?")
        params.append(domain)
    if search:
        conditions.append("(title LIKE ? OR authors LIKE ? OR tags LIKE ? OR notes LIKE ?)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern] * 4)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Validate sort column to prevent SQL injection
    allowed_sort_cols = {"created_at", "title", "year", "status", "domain", "analyzed_at"}
    if sort_by not in allowed_sort_cols:
        sort_by = "created_at"
    if sort_order.lower() not in ("asc", "desc"):
        sort_order = "desc"

    # Count total
    count_row = await fetch_one(
        f"SELECT COUNT(*) as cnt FROM papers {where_clause}", tuple(params)
    )
    total = count_row["cnt"] if count_row else 0

    # Fetch page
    offset = (page - 1) * page_size
    rows = await fetch_all(
        f"SELECT * FROM papers {where_clause} ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?",
        tuple(params) + (page_size, offset),
    )

    papers = [
        PaperResponse(
            **await _paper_payload(
                row,
            )
        )
        for row in rows
    ]
    return PaperListResponse(papers=papers, total=total, page=page, page_size=page_size)


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: int):
    """Get a single paper by ID."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    try:
        payload = await _paper_payload(paper, schedule_refresh=True)
    except FileNotFoundError as exc:
        status_code, detail = explain_odl_failure(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return PaperResponse(**payload)


@router.get("/{paper_id}/pdf")
async def get_paper_pdf(paper_id: int):
    """Serve the PDF file for a given paper."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    folder_name = paper["folder_name"]
    paper_dir = get_paper_dir(folder_name)

    if not paper_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Paper directory not found: {paper_dir}",
        )

    pdf_files = list(paper_dir.glob("*.pdf"))

    if not pdf_files:
        raise HTTPException(status_code=404, detail="PDF file not found on disk.")

    pdf_path = pdf_files[0]

    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="PDF path is not a valid file.")

    # Use RFC 5987 encoding for non-ASCII filenames (e.g. Korean)
    # to avoid Content-Disposition header encoding errors on macOS
    ascii_name = pdf_path.name.encode("ascii", errors="replace").decode("ascii")
    utf8_name = quote(pdf_path.name)
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"inline; filename=\"{ascii_name}\"; "
                f"filename*=UTF-8''{utf8_name}"
            )
        },
    )


@router.patch("/{paper_id}", response_model=PaperResponse)
async def update_paper(paper_id: int, update: PaperUpdate):
    """Update paper metadata (tags, notes, title, etc.)."""
    # Check existence
    existing = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # Build SET clause from non-None fields
    update_data = update.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update.")

    # If the domain changes without an explicit agent_used override, keep the
    # persona badge (agent_used) in sync with the new domain's default agent.
    if "domain" in update_data and "agent_used" not in update_data:
        from services.agents import get_agent_for_domain

        domain_value = update_data["domain"]
        domain_key = domain_value.value if hasattr(domain_value, "value") else domain_value
        update_data["agent_used"] = get_agent_for_domain(domain_key).name

    set_parts: list[str] = []
    values: list = []
    for key, value in update_data.items():
        if key == "analysis_focus" and isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        set_parts.append(f"{key} = ?")
        values.append(value.value if hasattr(value, "value") else value)

    values.append(paper_id)
    await execute_update(
        f"UPDATE papers SET {', '.join(set_parts)} WHERE id = ?",
        tuple(values),
    )

    # Return updated record
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=500, detail=f"Failed to reload paper {paper_id}.")
    return PaperResponse(
        **await _paper_payload(
            paper,
        )
    )


@router.delete("/{paper_id}", status_code=204)
async def delete_paper(paper_id: int):
    """
    Delete a paper and all associated files/records.
    - Remove analysis_results rows
    - Remove figures rows and files
    - Remove paper folder from disk
    - Remove paper row
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    folder_name = paper["folder_name"]

    # Delete from DB (cascading via foreign keys, but be explicit)
    db = await get_db()
    # I4: 실행 중이던 워커가 삭제를 모른 채 계속 돌면 FK 위반·파일 오류로 이어진다 —
    # analysis_runs 잔여 행을 지워 워커를 멈춘다(아래). (남겨두면 reconcile_stale ①에서
    # papers 조회가 NULL=terminal 아님으로 보여 ④ requeue가 삭제된 논문에 워커를 재스폰한다.)
    # request_cancel은 cancel_requested=1만 세우는데 4행 뒤 DELETE FROM analysis_runs가
    # 그 행 자체를 지워버려 실질적으로 소비될 일이 거의 없는 조기 신호용 best-effort다.
    # 실제 워커 종료는 행 삭제로 fence(paper_id+generation 매치)가 끊겨 fenced_heartbeat가
    # rowcount 0을 받고 워커가 ≤1.5초 내 self-abort하는 경로가 담당한다.
    await request_cancel(db, paper_id)
    await db.execute("DELETE FROM analysis_results WHERE paper_id = ?", (paper_id,))
    await db.execute("DELETE FROM figures WHERE paper_id = ?", (paper_id,))
    await db.execute("DELETE FROM tables WHERE paper_id = ?", (paper_id,))
    await db.execute("DELETE FROM analysis_runs WHERE paper_id = ?", (paper_id,))
    await db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    await db.commit()

    # Remove files from disk (figures are now inside paper_dir)
    paper_dir = get_paper_dir(folder_name)
    if paper_dir.exists():
        shutil.rmtree(paper_dir, ignore_errors=True)

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_filename(filename: str) -> str:
    """Remove problematic characters from a filename for use in directory names."""
    name = Path(filename).stem
    # Keep only alphanumeric, hyphens, underscores, and dots
    sanitized = re.sub(r"[^\w\-.]", "_", name)
    # Collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized[:80]  # Limit length


def safe_pdf_filename(filename: str | None) -> str:
    raw_name = str(filename or "").replace("\\", "/")
    basename = Path(raw_name).name
    if not basename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    stem = _sanitize_filename(basename)
    if not stem:
        raise HTTPException(status_code=400, detail="Invalid PDF filename.")
    return f"{stem}.pdf"


def _make_unique_folder_name(preferred: str, fallback: str) -> str:
    """Avoid collisions when generating a stable paper folder name."""
    base = preferred or fallback
    candidate = _sanitize_filename(base)
    if not candidate:
        candidate = fallback
    if not get_paper_dir(candidate).exists():
        return candidate

    suffix = 2
    while get_paper_dir(f"{candidate}_{suffix}").exists():
        suffix += 1
    return f"{candidate}_{suffix}"
