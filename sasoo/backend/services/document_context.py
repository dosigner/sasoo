"""
Shared document context builder for analysis phase inputs and cache keys.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from models.database import fetch_one
from services.odl_parser import ensure_text_artifacts, get_pdf_signature
from services.section_splitter import SectionSplitter

logger = logging.getLogger(__name__)

DOCUMENT_CONTEXT_FILENAME = ".document_context.json"
CONTEXT_BUILDER_VERSION = "document-context-v3"
_INPUT_HASH_LENGTH = 16
_SECTION_SPLITTER = SectionSplitter()
_QUANT_UNIT_PATTERN = (
    r"%|wt%|at%|ppm|ppb|nm|um|μm|mm|cm|m|km|mg|ug|μg|g|kg|ng|mL|uL|μL|L|"
    r"M|mM|uM|μM|nM|pM|V|mV|A|mA|uA|μA|W|mW|kW|Hz|kHz|MHz|GHz|THz|"
    r"s|ms|us|μs|min|h|hr|hrs|day|days|K|C|degC|°C|Pa|kPa|MPa|bar|Torr|atm|"
    r"rpm|eV|meV|dB|mol|mmol|umol|μmol|mAh/g|A/g|W/kg|Wh/kg|mS/cm|S/cm"
)
_QUANT_PATTERN = re.compile(
    rf"(?P<value>\d+(?:\.\d+)?(?:\s*[x×]\s*\d+(?:\.\d+)?)?)\s*(?P<unit>{_QUANT_UNIT_PATTERN})\b",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[\.\?!])\s+")


@dataclass(slots=True)
class CachedPhaseResult:
    result_text: str
    result_data: dict[str, Any]
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    input_hash: Optional[str]


def compute_input_hash(input_text: str) -> str:
    """Compute a short, stable hash for an analysis input string."""
    return hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:_INPUT_HASH_LENGTH]


def parse_result_json(result_text: str) -> dict[str, Any]:
    try:
        return json.loads(result_text)
    except (TypeError, json.JSONDecodeError):
        return {"raw_text": result_text}


async def find_cached_phase_result(
    paper_id: int,
    phase: str,
    input_text: str,
) -> Optional[CachedPhaseResult]:
    """Return the latest cached result for the same paper/phase/input hash."""
    if not input_text:
        return None

    input_hash = compute_input_hash(input_text)
    row = await fetch_one(
        """
        SELECT result, model_used, tokens_in, tokens_out, cost_usd, input_hash
        FROM analysis_results
        WHERE paper_id = ? AND phase = ? AND input_hash = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (paper_id, phase, input_hash),
    )
    if not row or not row.get("result"):
        return None

    return CachedPhaseResult(
        result_text=row["result"],
        result_data=parse_result_json(row["result"]),
        model_used=row.get("model_used") or "",
        tokens_in=row.get("tokens_in") or 0,
        tokens_out=row.get("tokens_out") or 0,
        cost_usd=row.get("cost_usd") or 0.0,
        input_hash=row.get("input_hash"),
    )


def build_visual_partial_cache_input(
    *,
    visual_input: str,
    figure_count: int,
    table_count: int,
    visual_state: str,
    visual_error: Optional[str],
) -> str:
    del visual_input
    payload = {
        "figure_count": figure_count,
        "table_count": table_count,
        "visual_state": visual_state,
        "visual_error": visual_error,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_visualization_cache_input(
    *,
    visualization_input: str,
    previous_results: list[str],
) -> str:
    payload = {
        "visualization_input": visualization_input,
        "previous_results": previous_results,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def load_or_build_document_context(
    paper_dir: Path,
    *,
    manifest: Optional[dict[str, Any]] = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Load a current .document_context.json sidecar or rebuild it from text artifacts.
    """
    paper_dir = Path(paper_dir)
    manifest = manifest or ensure_text_artifacts(paper_dir, force=force)

    pdf_files = sorted(paper_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF found in {paper_dir}")
    pdf_path = pdf_files[0]

    pdf_signature = get_pdf_signature(pdf_path)
    parser_version = str(manifest.get("parser_version") or "unknown")
    context_path = paper_dir / DOCUMENT_CONTEXT_FILENAME

    if not force:
        cached = _read_context(context_path)
        if _context_is_current(cached, pdf_signature=pdf_signature, parser_version=parser_version):
            return cached

    full_text = str(manifest.get("full_text") or "").strip()
    if not full_text:
        raise RuntimeError(f"Text artifacts are missing full_text for {paper_dir.name}")

    context = build_document_context_from_text(
        full_text,
        pdf_signature=pdf_signature,
        parser_version=parser_version,
    )
    context_path.write_text(
        json.dumps(context, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return context


def build_document_context_from_text(
    full_text: str,
    *,
    pdf_signature: Optional[dict[str, int]] = None,
    parser_version: str = "unknown",
) -> dict[str, Any]:
    """
    Build an in-memory context payload when no paper directory sidecar exists.
    """
    sections = _SECTION_SPLITTER.split(full_text)
    return {
        "pdf_signature": pdf_signature or {"pdf_mtime_ns": 0, "pdf_size": 0},
        "parser_version": parser_version,
        "context_builder_version": CONTEXT_BUILDER_VERSION,
        "sections": sections,
        "phase_inputs": _build_phase_inputs(sections, full_text),
        "quantitative_candidates": _extract_quantitative_candidates(sections, full_text),
    }


def _read_context(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _context_is_current(
    context: dict[str, Any] | None,
    *,
    pdf_signature: dict[str, int],
    parser_version: str,
) -> bool:
    if not context:
        return False

    signature = context.get("pdf_signature")
    if not isinstance(signature, dict):
        return False

    return (
        signature.get("pdf_mtime_ns") == pdf_signature["pdf_mtime_ns"]
        and signature.get("pdf_size") == pdf_signature["pdf_size"]
        and context.get("parser_version") == parser_version
        and context.get("context_builder_version") == CONTEXT_BUILDER_VERSION
        and isinstance(context.get("sections"), dict)
        and isinstance(context.get("phase_inputs"), dict)
    )


def _build_phase_inputs(sections: dict[str, str], full_text: str) -> dict[str, str]:
    phase_sections = dict(sections)
    phase_sections.setdefault("full_text", full_text)

    screening = _truncate_text(_SECTION_SPLITTER.get_screening_input(phase_sections), 5000)
    citation_body = _SECTION_SPLITTER.get_body_text_without_references(phase_sections)
    citation_references = _SECTION_SPLITTER.get_references_text(phase_sections)

    visual_parts: list[str] = []
    for section_name in _SECTION_SPLITTER.get_visual_input(phase_sections)[:4]:
        section_text = phase_sections.get(section_name, "").strip()
        if not section_text:
            continue
        visual_parts.append(f"=== {section_name.upper()} ===\n{section_text}")
    visual = _truncate_text("\n\n".join(visual_parts) or full_text, 3500)

    recipe_input = _SECTION_SPLITTER.get_recipe_input(phase_sections)
    deep_dive_input = _SECTION_SPLITTER.get_deepdive_input(phase_sections)
    recipe = _truncate_text(
        "\n\n".join(
            part
            for part in (
                recipe_input,
                _truncate_text(deep_dive_input, 3000),
            )
            if part
        ) or full_text,
        14000,
    )
    deep_dive = _truncate_text(deep_dive_input, 7000)
    visualization = _truncate_text(
        "\n\n".join(
            part
            for part in (
                screening,
                _truncate_text(recipe_input, 2200),
                _truncate_text(deep_dive_input, 2200),
            )
            if part
        ) or full_text,
        4200,
    )
    chat = _compose_section_context(
        phase_sections,
        section_names=[
            "abstract",
            "introduction",
            "background",
            "method",
            "experimental",
            "materials_methods",
            "results_discussion",
            "results",
            "discussion",
            "conclusion",
        ],
        fallback=full_text,
        limit=7000,
    )
    figure_detail = _compose_section_context(
        phase_sections,
        section_names=[
            "method",
            "experimental",
            "materials_methods",
            "results_discussion",
            "results",
            "discussion",
        ],
        fallback=full_text,
        limit=9000,
    )

    return {
        "screening": screening,
        "citation_body": citation_body,
        "citation_references": citation_references,
        "visual": visual,
        "recipe": recipe,
        "deep_dive": deep_dive,
        "visualization": visualization,
        "chat": chat,
        "figure_detail": figure_detail,
    }


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n...(중략)..."


def _compose_section_context(
    sections: dict[str, str],
    *,
    section_names: list[str],
    fallback: str,
    limit: int,
) -> str:
    parts: list[str] = []
    for section_name in section_names:
        section_text = sections.get(section_name, "").strip()
        if not section_text:
            continue
        parts.append(f"=== {section_name.upper()} ===\n{section_text}")

    return _truncate_text("\n\n".join(parts) or fallback, limit)


def _extract_quantitative_candidates(sections: dict[str, str], full_text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    search_sections = sections or {"full_text": full_text}
    seen: set[tuple[str, str, str, str]] = set()

    for section_name, section_text in search_sections.items():
        if not section_text or section_name == "references":
            continue
        for sentence in _split_sentences(section_text):
            for match in _QUANT_PATTERN.finditer(sentence):
                value = match.group("value").strip()
                unit = match.group("unit").strip()
                snippet = sentence.strip()[:240]
                name_guess = _guess_parameter_name(sentence, match.start())
                key = (name_guess, value, unit, section_name)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "name_guess": name_guess,
                        "value": value,
                        "unit": unit,
                        "section": section_name,
                        "snippet": snippet,
                    }
                )
    return candidates


def _split_sentences(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    parts = _SENTENCE_BREAK.split(stripped)
    return [part for part in parts if part]


def _guess_parameter_name(sentence: str, match_start: int) -> str:
    prefix = sentence[:match_start].strip()
    if not prefix:
        return "unknown"

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-/]*", prefix)
    if not tokens:
        return "unknown"

    return " ".join(tokens[-4:]).lower()
