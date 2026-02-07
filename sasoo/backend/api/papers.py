"""
Sasoo - Papers API Router
Endpoints for uploading, listing, retrieving, updating, and deleting papers.
"""

import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from models.database import (
    PAPERS_DIR,
    execute_insert,
    execute_update,
    fetch_all,
    fetch_one,
    get_db,
    get_figures_dir,
    get_paper_dir,
)
from models.schemas import (
    DomainType,
    AgentType,
    PaperListResponse,
    PaperResponse,
    PaperUpdate,
)

router = APIRouter(prefix="/api/papers", tags=["papers"])

# ---------------------------------------------------------------------------
# Domain classification heuristic (fast, pre-LLM)
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS: dict[DomainType, list[str]] = {
    DomainType.OPTICS: [
        "optical", "photonic", "laser", "waveguide", "lens", "refractive",
        "diffraction", "spectroscopy", "fluorescence", "photoluminescence",
        "plasmon", "metamaterial", "holograph", "fiber optic", "polarization",
    ],
    DomainType.MATERIALS: [
        "thin film", "deposition", "sputtering", "annealing", "crystal growth",
        "nanoparticle", "alloy", "ceramic", "polymer", "composite",
        "microstructure", "grain boundary", "phase diagram", "SEM", "TEM",
    ],
    DomainType.BIO: [
        "protein", "DNA", "RNA", "cell", "enzyme", "antibody", "biomarker",
        "tissue", "in vivo", "in vitro", "clinical", "pathogen", "genome",
        "biosensor", "drug delivery",
    ],
    DomainType.ENERGY: [
        "solar cell", "photovoltaic", "battery", "fuel cell", "supercapacitor",
        "perovskite", "electrolyte", "cathode", "anode", "energy harvest",
        "thermoelectric", "hydrogen", "wind turbine",
    ],
    DomainType.QUANTUM: [
        "quantum dot", "qubit", "entanglement", "superposition", "quantum computing",
        "quantum well", "quantum wire", "coherence", "decoherence",
        "quantum efficiency", "spin", "topological",
    ],
}

DOMAIN_AGENT_MAP: dict[DomainType, AgentType] = {
    DomainType.OPTICS: AgentType.PHOTON,
    DomainType.MATERIALS: AgentType.CRYSTAL,
    DomainType.BIO: AgentType.HELIX,
    DomainType.ENERGY: AgentType.VOLT,
    DomainType.QUANTUM: AgentType.QUBIT,
    DomainType.GENERAL: AgentType.ATLAS,
}


def classify_domain(text: str) -> tuple[DomainType, AgentType]:
    """
    Simple keyword-based domain classification.
    Returns (domain, agent) tuple. Falls back to GENERAL/ATLAS.
    """
    text_lower = text.lower()
    scores: dict[DomainType, int] = {}

    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[domain] = score

    if not scores:
        return DomainType.GENERAL, AgentType.ATLAS

    best_domain = max(scores, key=scores.get)  # type: ignore[arg-type]
    return best_domain, DOMAIN_AGENT_MAP[best_domain]


# ---------------------------------------------------------------------------
# PDF Metadata Extraction
# ---------------------------------------------------------------------------

def extract_pdf_metadata(pdf_path: str) -> dict:
    """
    Extract metadata and first-page text from a PDF using PyMuPDF.
    Returns dict with title, authors, year, etc.
    """
    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}

    # Extract text from first 3 pages for classification
    full_text_parts: list[str] = []
    for page_num in range(min(3, len(doc))):
        page = doc[page_num]
        full_text_parts.append(page.get_text())

    first_pages_text = "\n".join(full_text_parts)

    # Try to get title from metadata or first line of text
    title = meta.get("title", "").strip()
    if not title:
        lines = [l.strip() for l in first_pages_text.split("\n") if l.strip()]
        title = lines[0] if lines else "Untitled Paper"
        # Truncate overly long first-line "titles"
        if len(title) > 200:
            title = title[:200] + "..."

    # Authors
    authors = meta.get("author", "").strip() or None

    # Year - try metadata, then regex from text
    year = None
    creation_date = meta.get("creationDate", "")
    if creation_date:
        year_match = re.search(r"(\d{4})", creation_date)
        if year_match:
            y = int(year_match.group(1))
            if 1900 <= y <= 2100:
                year = y
    if year is None:
        year_matches = re.findall(r"\b(19|20)\d{2}\b", first_pages_text[:3000])
        if year_matches:
            # Pick the most common year in the first chunk
            from collections import Counter
            year_counts = Counter(int(m + first_pages_text[first_pages_text.find(m):first_pages_text.find(m)+4][-2:]) for m in [])
            # Simpler: just take the first plausible year
            for ym in year_matches:
                full_year = int(first_pages_text[first_pages_text.find(ym):first_pages_text.find(ym)+4])
                if 1990 <= full_year <= 2100:
                    year = full_year
                    break

    # DOI
    doi = None
    doi_match = re.search(r"10\.\d{4,}/[^\s]+", first_pages_text)
    if doi_match:
        doi = doi_match.group(0).rstrip(".,;)")

    # Journal - heuristic: check common patterns
    journal = None
    journal_patterns = [
        r"(?:Published in|Journal of|Proceedings of)\s+(.+?)[\.\n]",
        r"(?:Nature|Science|ACS|IEEE|Optics|Applied|Physical Review)\s*\w*",
    ]
    for pat in journal_patterns:
        jm = re.search(pat, first_pages_text[:2000], re.IGNORECASE)
        if jm:
            journal = jm.group(0).strip()[:100]
            break

    # Domain classification
    domain, agent = classify_domain(first_pages_text)

    # Total pages
    total_pages = len(doc)
    doc.close()

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "journal": journal,
        "doi": doi,
        "domain": domain.value,
        "agent_used": agent.value,
        "total_pages": total_pages,
        "first_pages_text": first_pages_text,
    }


def extract_figures_from_pdf(pdf_path: str, output_dir: str) -> list[dict]:
    """
    Extract images/figures from a PDF and save them to output_dir.
    Returns list of figure metadata dicts.
    """
    doc = fitz.open(pdf_path)
    figures: list[dict] = []
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            if base_image is None:
                continue

            image_bytes = base_image.get("image")
            image_ext = base_image.get("ext", "png")
            width = base_image.get("width", 0)
            height = base_image.get("height", 0)

            if not image_bytes or width < 50 or height < 50:
                # Skip tiny images (icons, bullets, etc.)
                continue

            fig_num = f"p{page_num + 1}_img{img_idx + 1}"
            fig_filename = f"{fig_num}.{image_ext}"
            fig_path = output_path / fig_filename

            with open(fig_path, "wb") as f:
                f.write(image_bytes)

            # Determine quality heuristic
            quality = "high"
            if width < 200 or height < 200:
                quality = "low"
            elif width < 400 or height < 400:
                quality = "medium"

            figures.append({
                "figure_num": fig_num,
                "caption": None,  # Captions require LLM or heuristic parsing
                "file_path": str(fig_path),
                "quality": quality,
            })

    doc.close()
    return figures


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
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Generate unique folder name
    folder_name = f"{uuid.uuid4().hex[:12]}_{_sanitize_filename(file.filename)}"
    paper_dir = get_paper_dir(folder_name)
    paper_dir.mkdir(parents=True, exist_ok=True)

    # Save the uploaded PDF
    pdf_path = paper_dir / file.filename
    content = await file.read()
    with open(pdf_path, "wb") as f:
        f.write(content)

    # Extract metadata
    try:
        metadata = extract_pdf_metadata(str(pdf_path))
    except Exception as e:
        # Clean up on failure
        shutil.rmtree(paper_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {str(e)}")

    # Extract figures
    figures_dir = get_figures_dir(folder_name)
    try:
        figures = extract_figures_from_pdf(str(pdf_path), str(figures_dir))
    except Exception:
        figures = []

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

    # Insert extracted figures into DB
    db = await get_db()
    for fig in figures:
        await db.execute(
            """
            INSERT INTO figures (paper_id, figure_num, caption, file_path, quality)
            VALUES (?, ?, ?, ?, ?)
            """,
            (paper_id, fig["figure_num"], fig["caption"], fig["file_path"], fig["quality"]),
        )
    await db.commit()

    # Fetch and return the created record
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=500, detail="Failed to retrieve created paper.")

    return PaperResponse(**paper)


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

    papers = [PaperResponse(**row) for row in rows]
    return PaperListResponse(papers=papers, total=total, page=page, page_size=page_size)


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: int):
    """Get a single paper by ID."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")
    return PaperResponse(**paper)


@router.get("/{paper_id}/pdf")
async def get_paper_pdf(paper_id: int):
    """Serve the PDF file for a given paper."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    folder_name = paper["folder_name"]
    paper_dir = get_paper_dir(folder_name)
    pdf_files = list(paper_dir.glob("*.pdf"))

    if not pdf_files:
        raise HTTPException(status_code=404, detail="PDF file not found on disk.")

    pdf_path = pdf_files[0]
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{pdf_path.name}\""},
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

    set_parts: list[str] = []
    values: list = []
    for key, value in update_data.items():
        set_parts.append(f"{key} = ?")
        values.append(value.value if hasattr(value, "value") else value)

    values.append(paper_id)
    await execute_update(
        f"UPDATE papers SET {', '.join(set_parts)} WHERE id = ?",
        tuple(values),
    )

    # Return updated record
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    return PaperResponse(**paper)


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
    await db.execute("DELETE FROM analysis_results WHERE paper_id = ?", (paper_id,))
    await db.execute("DELETE FROM figures WHERE paper_id = ?", (paper_id,))
    await db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    await db.commit()

    # Remove files from disk
    paper_dir = get_paper_dir(folder_name)
    if paper_dir.exists():
        shutil.rmtree(paper_dir, ignore_errors=True)

    figures_dir = get_figures_dir(folder_name)
    if figures_dir.exists():
        shutil.rmtree(figures_dir, ignore_errors=True)

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
