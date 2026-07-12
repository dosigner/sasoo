"""
Sasoo - Analysis API Router
Endpoints for running, monitoring, and retrieving the 4-phase analysis pipeline.

Phases:
  1. Screening       - Domain classification, relevance scoring, topic extraction
  2. Visual          - Figure extraction, quality assessment, diagram identification
  3. Recipe          - Experimental procedure extraction into structured recipe card
  4. Deep Dive       - Comprehensive analysis, strengths/weaknesses, novelty assessment
"""

import asyncio
import json
import logging
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

from models.database import (
    execute_insert,
    execute_update,
    fetch_all,
    fetch_one,
    get_paper_dir,
    get_paperbanana_dir,
)
from models.schemas import (
    AnalysisPhase,
    AnalysisResult,
    AnalysisStatus,
    DomainResult,
    FigureExplanationResponse,
    FigureInfo,
    FigureListResponse,
    FullAnalysisResponse,
    MermaidRepairRequest,
    MermaidResult,
    PaperBananaRequest,
    PaperBananaResponse,
    PhaseStatus,
    RecipeCard,
    ReportResponse,
    TableInfo,
    TableListResponse,
    VisualizationItem,
    VisualizationPlanResponse,
)
from services.odl_parser import (
    OdlParserError,
    OdlRuntimeError,
    ensure_text_artifacts_async,
    explain_odl_failure,
    figure_row_to_api_dict,
    schedule_paper_artifacts_refresh,
    table_row_to_api_dict,
)
from services.analysis_results import (
    get_latest_completed_phase_row,
    get_latest_completed_phase_rows,
)
from services.artifact_status import resolve_artifact_status_contract
from services.concurrency import run_chat_blocking, run_pipeline_blocking
from services.document_context import (
    build_visual_partial_cache_input,
    compute_input_hash,
    find_cached_phase_result,
    load_or_build_document_context,
)
from services.pricing import calc_cost

from api.analysis_state import _running_analyses, _cancel_events, _analyses_lock
from api.analysis_helpers import (
    _call_gemini,
    _clean_llm_json,
    _is_error_result,
    _get_gemini_client,
    _SYSTEM_INSTRUCTION_KO,
)
from services.models import (
    MODEL_SCREENING,
    MODEL_CITATION,
    MODEL_VISUAL,
    MODEL_RECIPE,
    MODEL_DEEP_DIVE,
    MODEL_VIZ_PLANNING,
    MODEL_MERMAID,
    MODEL_CHAT,
)
from api.report_service import (
    _format_phase_data,
    _generate_paperbanana_image,
)
from api.figure_service import explain_figure_handler

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


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


async def _get_cached_phase_result(paper_id: int, phase: str, input_text: str) -> Optional[dict]:
    cached = await find_cached_phase_result(paper_id, phase, input_text)
    if cached is None:
        return None
    await execute_insert(
        """
        INSERT INTO analysis_cache_events
            (paper_id, phase, input_hash, source_model, estimated_cost_usd, tokens_in, tokens_out)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            phase,
            cached.input_hash or compute_input_hash(input_text),
            cached.model_used or "cached",
            cached.cost_usd or 0.0,
            cached.tokens_in or 0,
            cached.tokens_out or 0,
        ),
    )
    return {
        "text": cached.result_text,
        "model": cached.model_used or "cached",
        "tokens_in": cached.tokens_in,
        "tokens_out": cached.tokens_out,
        "cost_usd": cached.cost_usd,
        "input_hash": cached.input_hash or compute_input_hash(input_text),
    }


def _screening_gate_decision(screening_result_text: Optional[str]) -> tuple[bool, str]:
    if not screening_result_text:
        return (False, "")
    try:
        payload = json.loads(_clean_llm_json(screening_result_text))
    except (TypeError, json.JSONDecodeError):
        return (False, "")

    if "relevance_score" not in payload or payload.get("relevance_score") in {None, ""}:
        return (False, "")

    try:
        relevance = float(payload.get("relevance_score"))
    except (TypeError, ValueError):
        return (False, "")

    domain = str(payload.get("domain") or "").strip().lower()
    key_topics = payload.get("key_topics") or []
    is_experimental = bool(payload.get("is_experimental", True))

    if relevance < 0.35:
        return (True, "low_relevance_screening")
    if relevance < 0.5 and domain in {"general", "unknown"} and (not is_experimental or len(key_topics) < 2):
        return (True, "low_confidence_screening")
    return (False, "")


async def _store_skipped_phase_result(
    *,
    paper_id: int,
    phase: str,
    phase_status: PhaseStatus,
    status: AnalysisStatus,
    progress_pct: float,
    reason: str,
    title: str,
) -> dict:
    result_text = json.dumps(
        {
            "skipped": True,
            "reason": reason,
            "message": f"{title} 단계는 스크리닝 신호가 약해 자동 실행을 건너뛰었습니다.",
        },
        ensure_ascii=False,
    )
    await _insert_analysis_result(
        paper_id,
        phase,
        result_text,
        "system",
        0,
        0,
        0.0,
        json.dumps({"phase": phase, "skip_reason": reason}, ensure_ascii=False, sort_keys=True),
    )
    phase_status.status = "completed"
    phase_status.completed_at = _utcnow_iso()
    phase_status.model_used = "system"
    phase_status.tokens_in = 0
    phase_status.tokens_out = 0
    phase_status.cost_usd = 0.0
    status.progress_pct = max(status.progress_pct, progress_pct)
    return {"text": result_text, "model": "system", "tokens_in": 0, "tokens_out": 0}


def _phase_result_snippet(row: Optional[dict], limit: int) -> str:
    if not row:
        return ""
    return str(row.get("result") or "")[:limit]


def _result_was_skipped(result: Optional[dict]) -> bool:
    if not result or not result.get("text"):
        return False
    try:
        payload = json.loads(_clean_llm_json(str(result["text"])))
    except (TypeError, json.JSONDecodeError):
        return False
    return bool(payload.get("skipped"))


async def _insert_analysis_result(
    paper_id: int,
    phase: str,
    result_text: str,
    model_used: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    input_text: str,
) -> None:
    await execute_insert(
        """
        INSERT INTO analysis_results
            (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd, input_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            phase,
            result_text,
            model_used,
            tokens_in,
            tokens_out,
            cost_usd,
            compute_input_hash(input_text),
        ),
    )


async def _get_visual_contract(
    paper_id: int,
    paper_dir: Path,
    *,
    schedule_refresh: bool,
) -> tuple[dict, int, int]:
    figure_count, table_count = await _get_visual_row_counts(paper_id)
    artifact_status = await resolve_artifact_status_contract(
        paper_id=paper_id,
        paper_dir=paper_dir,
        row_count=figure_count + table_count,
        schedule_if_needed=schedule_refresh,
        schedule_error_message="시각 artifact 동기화를 시작하지 못했습니다.",
    )
    return {
        "visual_ready": artifact_status.visual_ready,
        "visual_state": artifact_status.visual_state,
        "visual_error": artifact_status.visual_error,
        "artifacts_ready": artifact_status.visual_ready,
        "artifacts_error": artifact_status.visual_error,
    }, figure_count, table_count

# ---------------------------------------------------------------------------
# Phase execution functions
# ---------------------------------------------------------------------------

async def _run_screening(paper_id: int, screening_input: str, status: AnalysisStatus) -> dict:
    """Phase 1: Screening - classify domain, score relevance, extract topics."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.SCREENING,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.SCREENING
    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문을 분석해서 스크리닝 평가를 해줘.

모든 텍스트 내용(summary, key_topics 등)은 반드시 한국어로 작성해.
JSON key 이름만 영어로 유지하고, value는 전부 한국어로 써줘.

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "domain": "optics|materials|bio|energy|quantum|general",
  "agent_recommended": "photon|crystal|helix|volt|qubit|atlas",
  "relevance_score": 0.0-1.0,
  "key_topics": ["주제1", "주제2", ...],
  "methodology_type": "experimental|computational|theoretical|review",
  "summary": "2-3문장 요약 (한국어)",
  "is_experimental": true/false,
  "has_figures": true/false,
  "estimated_complexity": "low|medium|high"
}}

논문 텍스트:
{screening_input}
"""

    cached = await _get_cached_phase_result(paper_id, "screening", prompt)
    if cached is not None:
        phase_status.status = "completed"
        phase_status.completed_at = _utcnow_iso()
        phase_status.model_used = cached["model"]
        phase_status.tokens_in = cached["tokens_in"]
        phase_status.tokens_out = cached["tokens_out"]
        phase_status.cost_usd = cached["cost_usd"]
        status.progress_pct = max(status.progress_pct, 16.0)
        status.total_cost_usd += cached["cost_usd"]
        status.total_tokens_in += cached["tokens_in"]
        status.total_tokens_out += cached["tokens_out"]
        return cached

    result = await _call_gemini(prompt, model=MODEL_SCREENING)
    # Clean markdown fences from JSON response
    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 1 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    # Store in DB
    await _insert_analysis_result(
        paper_id,
        "screening",
        result["text"],
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        prompt,
    )

    # Update status
    phase_status.status = "completed"
    phase_status.completed_at = _utcnow_iso()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    status.progress_pct = max(status.progress_pct, 16.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


async def _run_citation(
    paper_id: int,
    sections: dict[str, str],
    citation_body: str,
    citation_references: str,
    paper_authors: str,
    status: AnalysisStatus,
) -> dict:
    """Phase 2: Citation Analysis - parse references, count citation frequency, analyze roles."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.CITATION,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.CITATION

    # --- Step 1: Parse references and count citations locally ---
    from services.citation_analyzer import analyze_citations

    analysis = analyze_citations(
        references_text=citation_references,
        body_text=citation_body,
        sections=sections,
        paper_authors=paper_authors,
    )
    local_result = analysis.to_dict()

    # --- Step 2: LLM analysis of top 10 cited references ---
    top_refs = local_result.get("top_cited", [])[:10]
    llm_prompt = ""
    if top_refs:
        top_refs_text = ""
        for i, ref in enumerate(top_refs, 1):
            contexts = ref.get("cite_contexts", [])
            ctx_str = "; ".join(c.get("sentence", "")[:100] for c in contexts[:3])
            top_refs_text += (
                f"{i}. {ref.get('ref_id', '')} {ref.get('authors', '')} "
                f"({ref.get('year', '?')}): \"{ref.get('title', '')}\" "
                f"[{ref.get('journal', '')}] — 인용 {ref.get('cite_count', 0)}회\n"
                f"   인용 맥락: {ctx_str}\n\n"
            )

        llm_prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 논문의 인용/참고문헌 분석을 해줘.

모든 텍스트 내용은 반드시 한국어로 작성해. JSON key 이름만 영어로 유지해.

이 논문의 총 참고문헌 수: {local_result.get('total_references', 0)}
인용 스타일: {local_result.get('citation_style', 'numbered')}
셀프 인용: {local_result.get('self_citation_count', 0)}건 (비율: {local_result.get('self_citation_ratio', 0):.1%})

가장 많이 인용된 상위 10개 참고문헌과 인용 맥락:
{top_refs_text}

위 데이터를 분석하여 각 참고문헌의 인용 역할을 분류하고,
이 논문이 선행연구를 어떻게 활용하고 있는지 평가해줘.

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "ref_analyses": [
    {{
      "ref_id": "[1]",
      "citation_role": "foundational|methodological|comparative|supporting|contrasting",
      "why_cited": "이 참고문헌이 왜 자주 인용되었는지 2-3문장 설명 (한국어)"
    }}
  ],
  "summary": "전체 인용 패턴에 대한 종합 평가 2-3문장 (한국어). 어떤 선행연구에 가장 많이 의존하는지, 인용이 공정한지 등.",
  "citation_balance": "balanced|heavily_reliant|self_citation_heavy|diverse",
  "key_influences": ["가장 영향을 많이 준 연구 그룹/논문 1-3개 (한국어)"]
}}

논문 본문 텍스트 (맥락용):
{citation_body[:3000]}
"""

        cached = await _get_cached_phase_result(paper_id, "citation", llm_prompt)
        if cached is not None:
            phase_status.status = "completed"
            phase_status.completed_at = _utcnow_iso()
            phase_status.model_used = cached["model"]
            phase_status.tokens_in = cached["tokens_in"]
            phase_status.tokens_out = cached["tokens_out"]
            phase_status.cost_usd = cached["cost_usd"]
            status.progress_pct = max(status.progress_pct, 16.0)
            status.total_cost_usd += cached["cost_usd"]
            status.total_tokens_in += cached["tokens_in"]
            status.total_tokens_out += cached["tokens_out"]
            return cached

        try:
            result = await _call_gemini(llm_prompt, model=MODEL_CITATION)
            cleaned_text = _clean_llm_json(result["text"])

            try:
                llm_data = json.loads(cleaned_text)
            except json.JSONDecodeError:
                llm_data = {}

            # Merge LLM analysis into local_result
            ref_analyses = llm_data.get("ref_analyses", [])
            for ra in ref_analyses:
                ref_id = ra.get("ref_id", "")
                for tc in local_result.get("top_cited", []):
                    if tc.get("ref_id") == ref_id:
                        tc["citation_role"] = ra.get("citation_role", "")
                        tc["why_cited"] = ra.get("why_cited", "")
                        break

            local_result["summary"] = llm_data.get("summary", "")
            local_result["citation_balance"] = llm_data.get("citation_balance", "")
            local_result["key_influences"] = llm_data.get("key_influences", [])

            cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

            phase_status.model_used = result["model"]
            phase_status.tokens_in = result["tokens_in"]
            phase_status.tokens_out = result["tokens_out"]
            phase_status.cost_usd = cost
            status.total_cost_usd += cost
            status.total_tokens_in += result["tokens_in"]
            status.total_tokens_out += result["tokens_out"]

        except Exception as exc:
            logger.warning("Citation LLM analysis failed: %s. Using local results only.", exc)
            local_result["summary"] = f"LLM 분석 실패 ({exc}). 로컬 파싱 결과만 제공됩니다."
            cost = 0.0

    else:
        local_result["summary"] = ""
        cost = 0.0

    input_hash_source = (
        llm_prompt
        if top_refs
        else json.dumps(
            {
                "citation_body": citation_body,
                "citation_references": citation_references,
                "paper_authors": paper_authors,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    if not top_refs:
        cached = await _get_cached_phase_result(paper_id, "citation", input_hash_source)
        if cached is not None:
            phase_status.status = "completed"
            phase_status.completed_at = _utcnow_iso()
            phase_status.model_used = cached["model"]
            phase_status.tokens_in = cached["tokens_in"]
            phase_status.tokens_out = cached["tokens_out"]
            phase_status.cost_usd = cached["cost_usd"]
            status.progress_pct = max(status.progress_pct, 16.0)
            status.total_cost_usd += cached["cost_usd"]
            status.total_tokens_in += cached["tokens_in"]
            status.total_tokens_out += cached["tokens_out"]
            return cached

    # Store result in DB
    result_json = json.dumps(local_result, ensure_ascii=False)
    await _insert_analysis_result(
        paper_id,
        "citation",
        result_json,
        phase_status.model_used or "local",
        phase_status.tokens_in or 0,
        phase_status.tokens_out or 0,
        cost,
        input_hash_source,
    )

    phase_status.status = "completed"
    phase_status.completed_at = _utcnow_iso()
    status.progress_pct = max(status.progress_pct, 16.0)

    return {"text": result_json, "model": phase_status.model_used or "local",
            "tokens_in": phase_status.tokens_in or 0, "tokens_out": phase_status.tokens_out or 0}


async def _run_visual(
    paper_id: int,
    visual_input: str,
    folder_name: str,
    status: AnalysisStatus,
) -> dict:
    """Phase 3: Visual verification - analyze figures, assess quality."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.VISUAL,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.VISUAL
    paper_dir = get_paper_dir(folder_name)
    visual_contract, figure_count, table_count = await _get_visual_contract(
        paper_id,
        paper_dir,
        schedule_refresh=True,
    )

    # Get existing figures from DB
    figures = await fetch_all(
        """
        SELECT * FROM figures
        WHERE paper_id = ? AND COALESCE(extraction_status, 'resolved') != 'rejected'
        """,
        (paper_id,),
    )
    tables = await fetch_all(
        """
        SELECT * FROM tables
        WHERE paper_id = ? AND COALESCE(extraction_status, 'resolved') != 'rejected'
        """,
        (paper_id,),
    )
    figure_count = len(figures)
    table_count = len(tables)

    if visual_contract["visual_state"] != "ready" or (figure_count == 0 and table_count == 0):
        if figure_count == 0 and table_count == 0:
            quality_summary = "추출된 figure/table artifact가 없어 visual phase를 partial mode로 저장했습니다."
            key_findings = ["시각 asset이 준비되지 않아 텍스트 분석만으로 후속 단계를 진행했습니다."]
        else:
            quality_summary = "시각 artifact가 아직 준비되지 않아 현재 확보된 DB 메타데이터만으로 partial visual result를 저장했습니다."
            key_findings = [
                f"현재 DB 기준 resolved figure {figure_count}개, resolved table {table_count}개가 있습니다.",
            ]
        if visual_contract["visual_error"]:
            key_findings.append(str(visual_contract["visual_error"]))

        partial_result = {
            "figure_count": figure_count,
            "tables_found": table_count,
            "equations_found": 0,
            "diagram_types": [],
            "quality_summary": quality_summary,
            "key_findings_from_visuals": key_findings,
            "visual_ready": visual_contract["visual_ready"],
            "visual_state": visual_contract["visual_state"],
            "visual_error": visual_contract["visual_error"],
            "artifacts_ready": visual_contract["artifacts_ready"],
            "artifacts_error": visual_contract["artifacts_error"],
            "artifacts_partial": True,
        }
        result_text = json.dumps(partial_result, ensure_ascii=False)
        partial_hash_source = build_visual_partial_cache_input(
            visual_input=visual_input,
            figure_count=figure_count,
            table_count=table_count,
            visual_state=str(visual_contract["visual_state"]),
            visual_error=visual_contract["visual_error"],
        )
        cached = await _get_cached_phase_result(paper_id, "visual", partial_hash_source)
        if cached is None:
            await _insert_analysis_result(
                paper_id,
                "visual",
                result_text,
                "system",
                0,
                0,
                0.0,
                partial_hash_source,
            )
        else:
            result_text = cached["text"]

        phase_status.status = "completed"
        phase_status.completed_at = _utcnow_iso()
        phase_status.model_used = "system"
        phase_status.tokens_in = 0
        phase_status.tokens_out = 0
        phase_status.cost_usd = 0.0
        status.progress_pct = max(status.progress_pct, 32.0)
        return {"text": result_text, "model": "system", "tokens_in": 0, "tokens_out": 0}

    figure_desc = ""
    if figures or tables:
        figure_desc = f"\n\nExtracted {figure_count} resolved figures and {table_count} resolved tables from the paper."
        for fig in figures:
            figure_desc += (
                f"\n- {fig['figure_num']}: quality={fig['quality']}, "
                f"confidence={fig.get('confidence')}, resolver={fig.get('resolver_version')}"
            )
        for table in tables[:10]:
            figure_desc += (
                f"\n- {table['table_num']}: confidence={table.get('confidence')}, "
                f"method={table.get('parse_method')}, resolver={table.get('resolver_version')}"
            )

    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문의 시각적 요소를 분석해줘.

모든 텍스트 내용(quality_summary, key_findings_from_visuals 등)은 반드시 한국어로 작성해.
JSON key 이름만 영어로 유지하고, value는 전부 한국어로 써줘.

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "figure_count": <int>,
  "tables_found": <int>,
  "equations_found": <int>,
  "diagram_types": ["SEM", "TEM", "spectrum", "graph", "photograph", "schematic", ...],
  "quality_summary": "그림 품질에 대한 전체 평가 (한국어)",
  "key_findings_from_visuals": ["시각자료에서 발견한 핵심 사항1", "핵심 사항2", ...]
}}

논문 관련 텍스트:
{visual_input}
{figure_desc}
"""

    cached = await _get_cached_phase_result(paper_id, "visual", prompt)
    if cached is not None:
        phase_status.status = "completed"
        phase_status.completed_at = _utcnow_iso()
        phase_status.model_used = cached["model"]
        phase_status.tokens_in = cached["tokens_in"]
        phase_status.tokens_out = cached["tokens_out"]
        phase_status.cost_usd = cached["cost_usd"]
        status.progress_pct = max(status.progress_pct, 32.0)
        status.total_cost_usd += cached["cost_usd"]
        status.total_tokens_in += cached["tokens_in"]
        status.total_tokens_out += cached["tokens_out"]
        return cached

    result = await _call_gemini(prompt, model=MODEL_VISUAL)
    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        parsed = json.loads(cleaned_text)
        parsed["figure_count"] = figure_count
        parsed["tables_found"] = table_count
        result["text"] = json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError as exc:
        logger.warning("Phase 2 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    await _insert_analysis_result(
        paper_id,
        "visual",
        result["text"],
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        prompt,
    )

    phase_status.status = "completed"
    phase_status.completed_at = _utcnow_iso()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    status.progress_pct = max(status.progress_pct, 32.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


async def _run_recipe(
    paper_id: int,
    recipe_input: str,
    status: AnalysisStatus,
    screening_result_text: Optional[str] = None,
) -> dict:
    """Phase 3: Recipe extraction - extract structured experimental procedure."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.RECIPE,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.RECIPE

    should_skip, skip_reason = _screening_gate_decision(screening_result_text)
    if should_skip:
        return await _store_skipped_phase_result(
            paper_id=paper_id,
            phase="recipe",
            phase_status=phase_status,
            status=status,
            progress_pct=48.0,
            reason=skip_reason,
            title="Recipe",
        )

    # --------------- Domain-specific parameter hints ---------------
    domain_hint = ""
    if screening_result_text:
        try:
            screening_data = json.loads(_clean_llm_json(screening_result_text))
            domain = screening_data.get("domain", "")
            if domain in ("optics", "photonics"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Optics/Photonics) — extract ALL of these if mentioned:
wavelength (nm), laser_power (W/mW), pulse_duration (fs/ps/ns), repetition_rate (Hz/MHz),
beam_diameter (mm/um), numerical_aperture (NA), focal_length (mm), magnification,
cavity_finesse, cavity_Q_factor, fiber_type (SMF/MMF), coupling_efficiency (%),
beam_quality_M2, polarization, modulation_frequency, detection_method,
signal_to_noise_ratio (dB), dark_count_rate, BER (bit error rate),
turbulence_strength (Cn2), propagation_distance (m/km), aperture_diameter,
pixel_pitch, resolution, phase_mask_levels, diffraction_efficiency"""
            elif domain in ("bio", "biology"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Biology/Biomedical) — extract ALL of these if mentioned:
cell_type, passage_number, seeding_density (cells/cm2), culture_medium,
incubation_temperature (C), incubation_duration (h/days), CO2_concentration (%),
assay_type, antibody_primary, antibody_secondary, staining_protocol,
detection_method, sample_size_n, cell_viability (%), drug_concentration,
exposure_time, imaging_modality, magnification, resolution"""
            elif domain in ("ai_ml", "neural", "computer_science"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (AI/ML) — extract ALL of these if mentioned:
architecture, num_layers, hidden_units, activation_function, optimizer,
learning_rate, batch_size, epochs, training_time, regularization,
dropout_rate, weight_initialization, training_data_size, test_data_split,
loss_function, evaluation_metric, GPU_type, precision (fp16/fp32),
augmentation_method, pretrained_model, fine_tuning_strategy"""
            elif domain in ("materials", "crystal"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Materials Science) — extract ALL of these if mentioned:
substrate_type, substrate_temperature (C/K), deposition_rate (nm/s, A/s), chamber_pressure (Pa/Torr),
film_thickness (nm/um), annealing_temperature (C/K), annealing_duration (min/h), annealing_atmosphere,
precursor_materials, target_composition, sputtering_power (W), RF_frequency (MHz),
grain_size (nm/um), crystal_structure, lattice_parameter (A/nm), surface_roughness (nm),
hardness (GPa), Young_modulus (GPa), thermal_conductivity (W/mK), electrical_resistivity (ohm*cm),
XRD_peaks (2theta), FWHM, crystallinity (%), porosity (%)"""
            elif domain in ("energy", "volt"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Energy) — extract ALL of these if mentioned:
cell_efficiency (%), open_circuit_voltage (V), short_circuit_current (mA/cm2),
fill_factor, bandgap (eV), absorber_thickness (nm/um), electrode_material,
electrolyte_composition, charge_capacity (mAh/g), discharge_rate (C),
cycle_number, capacity_retention (%), coulombic_efficiency (%),
power_density (W/kg), energy_density (Wh/kg), internal_resistance (ohm),
operating_temperature (C), illumination_intensity (mW/cm2, sun),
active_area (cm2), HTL_material, ETL_material, perovskite_composition"""
            elif domain in ("quantum", "qubit"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Quantum) — extract ALL of these if mentioned:
qubit_type, coherence_time_T1 (us/ms), coherence_time_T2 (us/ms), gate_fidelity (%),
readout_fidelity (%), operating_temperature (mK/K), coupling_strength (MHz/GHz),
resonator_frequency (GHz), anharmonicity (MHz), quantum_volume,
error_rate, circuit_depth, number_of_qubits, connectivity,
magnetic_field (T/mT), microwave_frequency (GHz), microwave_power (dBm),
Rabi_frequency (MHz), detuning (MHz), photon_number, squeezing_parameter (dB)"""
            else:
                domain_hint = """
Look for ALL quantitative parameters: temperatures, pressures, durations, concentrations,
voltages, currents, frequencies, distances, speeds, sizes, ratios, percentages, etc."""
        except (json.JSONDecodeError, TypeError):
            pass

    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문에서 실험 레시피를 완전하고 철저하게 추출해줘.

모든 텍스트 내용은 반드시 한국어로 작성해. JSON key 이름만 영어로 유지해.

핵심 지시사항:
1. 논문에 언급된 모든 정량적 파라미터를 추출해. Results나 Discussion에 있는 것도 포함.
2. 각 파라미터마다 name, value, unit, notes(출처/컨텍스트)를 반드시 포함.
3. 값이 불명확해도 notes="추정값" 또는 notes="근사값"으로 포함시켜.
4. 사소해 보이는 파라미터도 절대 건너뛰지 마 — 재현성을 위해 모든 세부사항 필요.
5. Methods 섹션뿐 아니라 논문 전체에서 파라미터를 찾아.
{domain_hint}

Return ONLY valid JSON (마크다운 펜스 없이, 설명 없이):
{{
  "title": "레시피 제목 (뭘 하는 실험인지, 한국어)",
  "objective": "이 실험의 목적 (한국어)",
  "materials": ["재료1 (규격 포함)", "재료2 (제조사, 순도, 등급)", ...],
  "equipment": ["장비1 (모델번호 포함)", "장비2", ...],
  "parameters": [
    {{"name": "파라미터 이름", "value": "수치 값", "unit": "단위", "notes": "출처/컨텍스트 (한국어)"}},
    {{"name": "다른 파라미터", "value": "값", "unit": "단위", "notes": ""}},
    ...
  ],
  "steps": [
    "단계 1: 구체적인 설정 포함한 상세 설명 (한국어)...",
    "단계 2: 온도, 시간, 속도 등 포함 (한국어)...",
    ...
  ],
  "critical_notes": ["재현을 위한 중요 참고사항 (한국어)", ...],
  "expected_results": "예상되는 결과 (한국어)",
  "safety_notes": "안전 주의사항 (한국어)",
  "confidence": 0.0-1.0,
  "missing_info": ["논문에서 찾지 못한 파라미터나 세부사항 (한국어)"],
  "reproducibility_score": 0.0-1.0
}}

중요: "parameters" 배열에 최소 8-15개 항목이 있어야 해.
5개 미만이면 텍스트를 다시 꼼꼼히 읽어 — 분명 놓친 게 있을 거야.

논문 텍스트:
{recipe_input}
"""

    cached = await _get_cached_phase_result(paper_id, "recipe", prompt)
    if cached is not None:
        phase_status.status = "completed"
        phase_status.completed_at = _utcnow_iso()
        phase_status.model_used = cached["model"]
        phase_status.tokens_in = cached["tokens_in"]
        phase_status.tokens_out = cached["tokens_out"]
        phase_status.cost_usd = cached["cost_usd"]
        status.progress_pct = max(status.progress_pct, 48.0)
        status.total_cost_usd += cached["cost_usd"]
        status.total_tokens_in += cached["tokens_in"]
        status.total_tokens_out += cached["tokens_out"]
        return cached

    result = await _call_gemini(prompt, model=MODEL_RECIPE)

    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 3 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    await _insert_analysis_result(
        paper_id,
        "recipe",
        result["text"],
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        prompt,
    )

    phase_status.status = "completed"
    phase_status.completed_at = _utcnow_iso()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    status.progress_pct = max(status.progress_pct, 48.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


async def _run_deep_dive(
    paper_id: int,
    deep_dive_input: str,
    previous_results: list[str],
    status: AnalysisStatus,
    screening_result_text: Optional[str] = None,
) -> dict:
    """Phase 4: Deep dive - comprehensive analysis using Gemini Pro."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.DEEP_DIVE,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.DEEP_DIVE

    should_skip, skip_reason = _screening_gate_decision(screening_result_text)
    if should_skip:
        return await _store_skipped_phase_result(
            paper_id=paper_id,
            phase="deep_dive",
            phase_status=phase_status,
            status=status,
            progress_pct=64.0,
            reason=skip_reason,
            title="Deep Dive",
        )

    prev_context = "\n\n".join(previous_results[:4]) if previous_results else ""

    prompt = f"""너는 Sasoo(사수)라는 AI Co-Scientist야. 이 연구 논문에 대한 심층 분석을 해줘.

모든 텍스트 내용은 반드시 한국어로 작성해. JSON key 이름만 영어로 유지해.
전문적이면서도 이해하기 쉽게, 마치 선배 연구자가 후배에게 설명하듯이 써줘.

이전 분석 단계의 결과:
{prev_context[:4000]}

위 정보를 바탕으로 포괄적인 심층 분석을 제공해줘.

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "detailed_analysis": "논문의 기여도, 방법론, 결과에 대한 상세 분석 (여러 문단, 한국어)",
  "strengths": ["강점1 (한국어)", "강점2", ...],
  "weaknesses": ["약점1 (한국어)", "약점2", ...],
  "novelty_assessment": "이 연구의 새로움 평가 (한국어)",
  "comparison_to_prior_work": "기존 연구 대비 비교 (한국어)",
  "suggested_improvements": ["개선 제안1 (한국어)", ...],
  "follow_up_questions": ["후속 질문1 (한국어)", ...],
  "practical_applications": ["실용적 응용1 (한국어)", ...]
}}

논문 텍스트:
{deep_dive_input}
"""

    cached = await _get_cached_phase_result(paper_id, "deep_dive", prompt)
    if cached is not None:
        phase_status.status = "completed"
        phase_status.completed_at = _utcnow_iso()
        phase_status.model_used = cached["model"]
        phase_status.tokens_in = cached["tokens_in"]
        phase_status.tokens_out = cached["tokens_out"]
        phase_status.cost_usd = cached["cost_usd"]
        status.progress_pct = max(status.progress_pct, 64.0)
        status.total_cost_usd += cached["cost_usd"]
        status.total_tokens_in += cached["tokens_in"]
        status.total_tokens_out += cached["tokens_out"]
        return cached

    result = await _call_gemini(prompt, model=MODEL_DEEP_DIVE)

    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 4 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    await _insert_analysis_result(
        paper_id,
        "deep_dive",
        result["text"],
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        prompt,
    )

    phase_status.status = "completed"
    phase_status.completed_at = _utcnow_iso()
    phase_status.model_used = result["model"]
    phase_status.tokens_in = result["tokens_in"]
    phase_status.tokens_out = result["tokens_out"]
    phase_status.cost_usd = cost
    # 64% — visualization step still needs to run after deep_dive
    status.progress_pct = max(status.progress_pct, 64.0)
    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    return result


# ---------------------------------------------------------------------------
# Phase 5: Visualization Planning & Generation  (Gemini Pro 3)
# ---------------------------------------------------------------------------

_MERMAID_SYNTAX_RULES = """CRITICAL RULES (Mermaid v10.x compatibility):
1. Start with the diagram type keyword (flowchart TD, flowchart LR, sequenceDiagram, mindmap, etc.).
2. NEVER use --- frontmatter blocks, accTitle/accDescr, or %%{init: ...}%% directives.
3. Use simple alphanumeric node IDs (A, B, step1). NEVER use Korean in node IDs.
4. ALWAYS wrap labels containing special characters in double quotes: A["레이저 소스 (1064nm)"].
5. Special characters that MUST be quoted: parentheses (), colons :, semicolons ;, pipes |, angles <>.
6. For edge labels use: A -->|"label text"| B
7. Keep labels concise (under 30 chars). Use Korean for all labels.
8. Do NOT use HTML tags except <br/> for line breaks.
9. NEVER use the `A & B --> C` multi-link shorthand — write each edge on its own line.
10. Return ONLY the Mermaid code. No markdown fences, no explanation."""

_MERMAID_STYLE_RULES = """STYLING RULES — make the diagram visually rich and easy to scan (색·모양·화살표로 의미를 구분해):

A. Flowchart (flowchart TD/LR) — ALWAYS apply styling:
   - Give EVERY node a semantic class with :::className, e.g. A["입력 데이터"]:::data
   - Define all classDefs at the END of the diagram. Use this theme-safe palette
     (dark fill + bright stroke + pale text — readable on dark AND light backgrounds):
       classDef data fill:#1e3a5f,stroke:#4a9eff,stroke-width:2px,color:#e8f4ff
       classDef process fill:#3b2a5f,stroke:#a78bfa,stroke-width:2px,color:#f3e8ff
       classDef measure fill:#134e4a,stroke:#2dd4bf,stroke-width:2px,color:#e0fffb
       classDef decision fill:#5f4a1e,stroke:#fbbf24,stroke-width:2px,color:#fff7e0
       classDef result fill:#1e5f3a,stroke:#34d399,stroke-width:2px,color:#e0fff0
       classDef caution fill:#5f1e2a,stroke:#fb7185,stroke-width:2px,color:#ffe8ec
     Only define the classes you actually use. You may add more classes in the
     same format (keep fill dark, color pale).
   - Vary node shapes by meaning: ["단계"] 일반, ("시작/끝"), {"판단"}, [("데이터 저장")], (("핵심 개념")), [["서브루틴"]]
   - Vary arrow styles by meaning:
       ==>   핵심 주 흐름 (굵은 선)
       -->   일반 흐름
       -.->  피드백 / 반복 / 선택적 경로
       --o   참조 / 데이터 연결
       --x   실패 / 배제 경로
       <-->  양방향 상호작용
   - Group related steps with subgraphs (alphanumeric id + quoted title), then style them:
       subgraph SG1["학습 파이프라인"] ... end
       style SG1 fill:transparent,stroke:#8b5cf6,stroke-width:1.5px,stroke-dasharray:5 5
   - Color important arrows with linkStyle (0-based edge index, counted in
     order of appearance from the top). Use bright strokes from the palette:
       linkStyle 0,3 stroke:#4a9eff,stroke-width:2.5px
       linkStyle 1 stroke:#fb7185,stroke-width:2px
     e.g. 주 흐름=파랑, 피드백=보라, 실패 경로=장미. Count indices carefully.

B. sequenceDiagram:
   - Use autonumber and participant aliases: participant A as 레이저 소스
   - Group phases with translucent backgrounds (alpha <= 0.2 so both themes stay readable):
       rect rgba(94, 106, 210, 0.15) ... end
   - Vary arrows: ->> 요청/명령, -->> 응답(점선), -x 실패, -) 비동기
   - Use Note over/left of/right of for annotations.
   - classDef/linkStyle are NOT supported here — do not use them.

C. mindmap / timeline:
   - classDef, style, linkStyle are NOT supported — never emit them.
   - For mindmap, vary node shapes instead: root((중심)), (둥근), [사각], ((원)).

EXAMPLE (flowchart pattern to imitate — structure, shapes, arrows, classes):
flowchart TD
    A("논문 입력"):::data ==> B["전처리"]:::process
    B --> C{"품질 충족?"}:::decision
    C -->|"예"| D[["모델 학습"]]:::process
    C -.->|"아니오"| B
    D --o E[("결과 DB")]:::data
    D ==> F["성능 평가"]:::measure
    F --x G["과적합 사례"]:::caution
    F ==> H(("최종 모델")):::result
    subgraph SG1["학습 루프"]
        B
        C
        D
    end
    style SG1 fill:transparent,stroke:#8b5cf6,stroke-width:1.5px,stroke-dasharray:5 5
    classDef data fill:#1e3a5f,stroke:#4a9eff,stroke-width:2px,color:#e8f4ff
    classDef process fill:#3b2a5f,stroke:#a78bfa,stroke-width:2px,color:#f3e8ff
    classDef measure fill:#134e4a,stroke:#2dd4bf,stroke-width:2px,color:#e0fffb
    classDef decision fill:#5f4a1e,stroke:#fbbf24,stroke-width:2px,color:#fff7e0
    classDef result fill:#1e5f3a,stroke:#34d399,stroke-width:2px,color:#e0fff0
    classDef caution fill:#5f1e2a,stroke:#fb7185,stroke-width:2px,color:#ffe8ec"""

_MERMAID_KEYWORDS = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "mindmap",
    "timeline",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie",
    "quadrantChart",
    "journey",
)


# Flowchart edge connectors: -->, ---, -.->, ==>, ===, --o, --x, <-->, ~~~ …
# Greedy quantifiers collapse long forms (---->) into a single match.
_MERMAID_LINK_RE = re.compile(r"<?(?:-{2,}[>ox]?|={2,}[>x]?|-\.+->?|~{3,})")

_MERMAID_NON_EDGE_PREFIXES = (
    "classDef",
    "class ",
    "style ",
    "linkStyle",
    "subgraph",
    "direction",
    "%%",
)


def _filter_out_of_range_linkstyles(code: str) -> str:
    """Drop numbered linkStyle lines whose edge index cannot exist.

    Mermaid hard-fails the whole diagram on an out-of-range linkStyle index,
    so guarding here lets the prompt use per-edge colors freely. Counting is
    done on quote-stripped non-style lines; `&` multi-links make the count
    ambiguous, in which case every numbered linkStyle is dropped.
    """
    lines = code.split("\n")
    first = lines[0].strip() if lines else ""
    if not first.startswith(("flowchart", "graph")):
        return code

    edge_count = 0
    ambiguous = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(_MERMAID_NON_EDGE_PREFIXES):
            continue
        unquoted = re.sub(r'"[^"]*"', '""', stripped)
        if "&" in unquoted:
            ambiguous = True
        edge_count += len(_MERMAID_LINK_RE.findall(unquoted))

    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("linkStyle"):
            kept.append(line)
            continue
        if stripped.startswith("linkStyle default"):
            kept.append(line)
            continue
        match = re.match(r"linkStyle\s+((?:\d+\s*,\s*)*\d+)\b", stripped)
        if match is None or ambiguous:
            continue
        indices = [int(n) for n in re.findall(r"\d+", match.group(1))]
        if all(i < edge_count for i in indices):
            kept.append(line)
    return "\n".join(kept)


def _sanitize_mermaid_code(raw: str) -> str:
    """Best-effort cleanup of LLM-generated Mermaid code (v10.x compatibility)."""
    code = raw.strip()

    # Strip markdown fences
    if code.startswith("```"):
        code = "\n".join(
            line for line in code.split("\n") if not line.strip().startswith("```")
        ).strip()

    # Strip YAML frontmatter block
    fm_match = re.match(r"^\s*---\s*\n.*?\n\s*---\s*\n?", code, re.DOTALL)
    if fm_match:
        code = code[fm_match.end():]

    # Strip init directives and accessibility lines (not supported / theme conflicts)
    code = re.sub(r"%%\{init:.*?\}%%\s*", "", code, flags=re.DOTALL)
    code = re.sub(r"^\s*accTitle\s*:.*$", "", code, flags=re.MULTILINE)
    code = re.sub(r"^\s*accDescr\s*:.*$", "", code, flags=re.MULTILINE)
    code = code.strip()

    # Drop any prose before the first diagram keyword line
    lines = code.split("\n")
    if lines and not lines[0].strip().startswith(_MERMAID_KEYWORDS):
        for i, line in enumerate(lines):
            if line.strip().startswith(_MERMAID_KEYWORDS):
                code = "\n".join(lines[i:])
                break

    return _filter_out_of_range_linkstyles(code.strip()).strip()


async def _plan_visualizations(
    paper_id: int,
    visualization_input: str,
    previous_results: list[str],
    status: AnalysisStatus,
) -> list[dict]:
    """
    Use Gemini Pro 3 to decide which visualizations (up to 10) will best help
    understand the paper's methodology. Returns a plan as a list of dicts.
    """
    phase_status = PhaseStatus(
        phase=AnalysisPhase.DEEP_DIVE,  # piggyback on deep_dive phase for status
        status="running",
        started_at=_utcnow_iso(),
    )
    # Don't append a new phase — we update the existing deep_dive phase's progress

    prev_context = "\n---\n".join(previous_results[:4])

    prompt = f"""너는 연구 논문 분석 시스템의 시각화 기획자야.

아래 분석 결과를 모두 읽고, 이 논문의 방법론과 기여를 완전히 이해하는 데
가장 도움이 될 다이어그램/그림을 결정해줘.

반드시 6~10개의 시각화 항목을 반환해. 가장 임팩트 있는 것을 선택해.
논문의 핵심 개념과 작동 원리를 시각적으로 설명하는 일러스트(paperbanana 개념도)를
충분히 포함해 — 방법론 다이어그램만으로 채우지 마.

각 시각화를 두 가지 도구 중 하나로 분류해:
- "mermaid": 구조적/논리적 다이어그램 (플로우차트, 시퀀스, 마인드맵, 타임라인, 비교)
- "paperbanana": 물리적/시각적 일러스트 (장비 셋업, 광학 레이아웃, 세포/분자 도식, 개념도)

Return ONLY valid JSON (마크다운 펜스 없이). 아래 구조를 정확히 따라:
{{
  "visualizations": [
    {{
      "title": "짧은 설명 제목 (한국어)",
      "tool": "mermaid" or "paperbanana",
      "diagram_type": "flowchart|sequence|mindmap|timeline|methodology|conceptual|comparison",
      "description": "이 시각화가 왜 필요한지, 무엇을 보여주는지 2-3문장 설명 (한국어)",
      "category": "experimental_protocol|algorithm_flow|signal_flow|system_architecture|component_relationships|timeline|comparison|equipment_appearance|optical_table_layout|cell_molecule_schematic|physical_setup|conceptual_illustration"
    }}
  ]
}}

실험 방법을 최대한 이해할 수 있는 시각화를 우선시해.
고려할 것: 프로세스 흐름, 파라미터 관계, 장비 구성, 신호 경로, 비교표.

--- 분석 결과 (Phase 1-4) ---
{prev_context[:9000]}

--- 관련 텍스트 요약 ---
{visualization_input}
"""

    cached = await _get_cached_phase_result(paper_id, "viz_plan", prompt)
    if cached is not None:
        try:
            return json.loads(cached["text"]).get("visualizations", [])
        except (json.JSONDecodeError, TypeError, AttributeError):
            return []

    result = await _call_gemini(prompt, model=MODEL_VIZ_PLANNING)
    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    status.total_cost_usd += cost
    status.total_tokens_in += result["tokens_in"]
    status.total_tokens_out += result["tokens_out"]

    # Parse the plan
    raw = result["text"].strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()

    try:
        plan_data = json.loads(raw)
        items = plan_data.get("visualizations", [])
    except (json.JSONDecodeError, TypeError):
        # Fallback: create a single default flowchart
        items = [{
            "title": "실험 프로세스 흐름도",
            "tool": "mermaid",
            "diagram_type": "flowchart",
            "description": "논문의 실험 방법론 전체 흐름을 보여주는 플로우차트",
            "category": "experimental_protocol",
        }]

    # Cap at 10
    items = items[:10]

    # Store the plan in DB
    result_text = json.dumps({"visualizations": items}, ensure_ascii=False)
    await _insert_analysis_result(
        paper_id,
        "viz_plan",
        result_text,
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        prompt,
    )

    return items


async def _generate_single_mermaid(
    paper_id: int,
    viz_item: dict,
    visualization_input: str,
    previous_results: list[str],
) -> str:
    """Generate Mermaid code for a single visualization item using Gemini Pro 3."""
    title = viz_item.get("title", "Diagram")
    diagram_type = viz_item.get("diagram_type", "flowchart")
    description = viz_item.get("description", "")

    prev_context = "\n---\n".join(previous_results[:4])

    prompt = f"""아래 시각화에 맞는 Mermaid {diagram_type} 다이어그램을 생성해줘.

제목: {title}
설명: {description}

{_MERMAID_SYNTAX_RULES}

{_MERMAID_STYLE_RULES}

추가 규칙: 모든 노드 레이블과 엣지 레이블을 반드시 한국어로 작성해.

분석 데이터와 논문 텍스트를 소스로 사용해:

--- 분석 데이터 ---
{prev_context[:5000]}

--- 관련 텍스트 요약 ---
{visualization_input}

다이어그램 타입 키워드로 시작하는 유효한 Mermaid 코드만 반환해.
"""

    result = await _call_gemini(prompt, model=MODEL_MERMAID)

    return _sanitize_mermaid_code(result["text"])


async def _generate_single_paperbanana(
    paper_id: int,
    viz_item: dict,
    visualization_input: str,
    folder_name: str,
    recipe_result: str,
    deep_dive_result: str,
) -> dict:
    """
    Generate a PaperBanana illustration for a single visualization item.
    Returns {"image_path": ..., "image_url": ..., "provider": ..., "duration_s": ...,
    "cost_usd": ...} on success, or {"error": ...} on failure.
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    title = viz_item.get("title", "Illustration")
    description = viz_item.get("description", "")
    enriched_item = dict(viz_item)
    context_parts = [description]
    if recipe_result:
        context_parts.append(f"Recipe context: {recipe_result[:1800]}")
    if deep_dive_result:
        context_parts.append(f"Deep dive context: {deep_dive_result[:1800]}")
    if visualization_input:
        context_parts.append(f"Paper context: {visualization_input[:2200]}")
    enriched_item["description"] = "\n\n".join(part for part in context_parts if part)

    from services.viz.figure_gen import generate_illustration
    from api.settings import _get_all_settings

    settings = await _get_all_settings()
    result = await generate_illustration(
        enriched_item,
        str(get_paper_dir(folder_name)),
        preferred_provider=settings.get("image_provider", "openai"),
        quality=settings.get("image_quality", "high"),
    )
    if result.path:
        url = f"/static/library/{folder_name}/paperbanana/{Path(result.path).name}"
        _logger.info(
            "figure_gen ok '%s' via %s in %.1fs ($%.3f)",
            title, result.provider, result.duration_s, result.cost_usd,
        )
        return {
            "image_path": result.path,
            "image_url": url,
            "provider": result.provider,
            "duration_s": result.duration_s,
            "cost_usd": result.cost_usd,
        }
    _logger.warning("figure_gen failed for '%s': %s", title, result.error)
    return {"error": result.error or "generation failed"}


async def _store_visualization_progress(
    paper_id: int, items: list[dict], cache_input: str, done: bool
) -> None:
    """항목이 하나 끝날 때마다 visualization 행을 갱신한다 (중간 사망 시 유실 방지).

    UPDATE 대상 SELECT는 input_hash까지 걸어 같은 실행(run)의 행만 찾는다. paper_id+phase
    최신 1건만 보면, 재분석(다른 input_hash로 재실행)이 이전 실행의 완료된 행을 이어달리기로
    착각하고 덮어써버린다 — 새 실행은 반드시 새 행을 INSERT해야 한다.
    """
    input_hash = compute_input_hash(cache_input)
    total_cost_usd = sum(it.get("cost_usd") or 0 for it in items)
    payload = json.dumps(
        {
            "items": sorted(items, key=lambda x: x.get("id", 0)),
            "total_count": len(items),
            "model_used": MODEL_VIZ_PLANNING,
            "planned_at": _utcnow_iso(),
            "complete": done,
        },
        ensure_ascii=False,
    )
    row = await fetch_one(
        """
        SELECT id FROM analysis_results
        WHERE paper_id = ? AND phase = 'visualization' AND input_hash = ?
        ORDER BY id DESC LIMIT 1
        """,
        (paper_id, input_hash),
    )
    if row:
        await execute_update(
            "UPDATE analysis_results SET result = ?, input_hash = ?, cost_usd = ? WHERE id = ?",
            (payload, input_hash, total_cost_usd, row["id"]),
        )
    else:
        await _insert_analysis_result(
            paper_id, "visualization", payload, MODEL_VIZ_PLANNING, 0, 0, total_cost_usd, cache_input,
        )


async def _run_visualizations(
    paper_id: int,
    visualization_input: str,
    folder_name: str,
    previous_results: list[str],
    recipe_result: str,
    deep_dive_result: str,
    status: AnalysisStatus,
) -> list[dict]:
    """
    Full visualization pipeline:
    1. Gemini Pro 3 plans up to 10 visualizations
    2. Generate each (Mermaid or PaperBanana) in parallel
    3. Store results in DB
    """
    visualization_cache_input = json.dumps(
        {
            "visualization_input": visualization_input,
            "previous_results": previous_results,
            "recipe_result": recipe_result,
            "deep_dive_result": deep_dive_result,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cached = await _get_cached_phase_result(paper_id, "visualization", visualization_cache_input)
    if cached is not None:
        try:
            cached_data = json.loads(cached["text"])
            # `complete` was introduced with per-item checkpointing (f577fe2): a mid-run
            # crash can leave behind a partial checkpoint row (complete=False) that shares
            # the same input_hash as a full run. Rows written before checkpointing existed
            # have no `complete` field at all, but every one of them was a final save, so
            # default to True for those and only reject an explicit complete=False.
            if cached_data.get("complete", True) is not False:
                status.progress_pct = 100.0
                return list(cached_data.get("items", []))
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    # Step 1: Plan
    viz_plan = await _plan_visualizations(paper_id, visualization_input, previous_results, status)

    # Step 2: Generate all in parallel
    async def generate_one(idx: int, item: dict) -> dict:
        tool = item.get("tool", "mermaid")
        result_item = {
            "id": idx + 1,
            "title": item.get("title", f"Visualization {idx + 1}"),
            "tool": tool,
            "diagram_type": item.get("diagram_type", "flowchart"),
            "description": item.get("description", ""),
            "category": item.get("category", ""),
            "status": "generating",
        }
        try:
            if tool == "mermaid":
                code = await _generate_single_mermaid(
                    paper_id,
                    item,
                    visualization_input,
                    previous_results,
                )
                result_item["mermaid_code"] = code
                result_item["status"] = "completed"
            elif tool == "paperbanana":
                pb_result = await _generate_single_paperbanana(
                    paper_id,
                    item,
                    visualization_input,
                    folder_name,
                    recipe_result,
                    deep_dive_result,
                )
                result_item["image_url"] = pb_result.get("image_url")
                result_item["image_path"] = pb_result.get("image_path")
                if pb_result.get("image_path"):
                    result_item["status"] = "completed"
                    if pb_result.get("provider"):
                        result_item["provider"] = pb_result["provider"]
                    if pb_result.get("duration_s") is not None:
                        result_item["duration_s"] = pb_result["duration_s"]
                    if pb_result.get("cost_usd") is not None:
                        result_item["cost_usd"] = pb_result["cost_usd"]
                else:
                    result_item["status"] = "error"
                    result_item["error_message"] = pb_result.get("error", "generation failed")
            else:
                result_item["status"] = "error"
                result_item["error_message"] = f"Unknown tool: {tool}"
        except Exception as e:
            result_item["status"] = "error"
            result_item["error_message"] = str(e)
        return result_item

    # Separate mermaid (can run in parallel) from paperbanana (run sequentially to avoid rate limits)
    mermaid_items = [(i, item) for i, item in enumerate(viz_plan) if item.get("tool") == "mermaid"]
    paperbanana_items = [(i, item) for i, item in enumerate(viz_plan) if item.get("tool") == "paperbanana"]
    other_items = [(i, item) for i, item in enumerate(viz_plan)
                   if item.get("tool") not in ("mermaid", "paperbanana")]

    # Accumulates completed items so far, so a mid-run crash doesn't lose progress.
    accumulated: list[dict] = []

    # Run mermaid generations in parallel
    mermaid_tasks = [generate_one(i, item) for i, item in mermaid_items]
    mermaid_results = await asyncio.gather(*mermaid_tasks, return_exceptions=False) if mermaid_tasks else []
    if mermaid_results:
        accumulated.extend(mermaid_results)
        await _store_visualization_progress(paper_id, accumulated, visualization_cache_input, done=False)

    # Run paperbanana generations sequentially to avoid API rate limits
    paperbanana_results = []
    for idx, (i, item) in enumerate(paperbanana_items):
        result = await generate_one(i, item)
        paperbanana_results.append(result)
        accumulated.append(result)
        await _store_visualization_progress(paper_id, accumulated, visualization_cache_input, done=False)
        # Small delay between PaperBanana calls to avoid rate limiting
        if idx < len(paperbanana_items) - 1:
            await asyncio.sleep(2.0)

    # Run other tool types in parallel
    other_tasks = [generate_one(i, item) for i, item in other_items]
    other_results = await asyncio.gather(*other_tasks, return_exceptions=False) if other_tasks else []
    if other_results:
        accumulated.extend(other_results)
        await _store_visualization_progress(paper_id, accumulated, visualization_cache_input, done=False)

    # Combine and sort by original index
    all_results = list(mermaid_results) + paperbanana_results + list(other_results)
    generated_items = sorted(all_results, key=lambda x: x.get("id", 0))

    # Step 3: Store all visualization results in DB (final, complete=True)
    await _store_visualization_progress(paper_id, generated_items, visualization_cache_input, done=True)

    # Visualization complete — set progress to 100%
    status.progress_pct = 100.0

    return list(generated_items)


# ---------------------------------------------------------------------------
# Background analysis pipeline
# ---------------------------------------------------------------------------

async def _run_full_analysis(paper_id: int):
    """
    Execute the complete 4-phase analysis pipeline in background.
    Updates paper status and in-memory tracking as it progresses.
    """
    status = AnalysisStatus(
        paper_id=paper_id,
        overall_status="running",
        phases=[],
        progress_pct=0.0,
    )

    async with _analyses_lock:
        _running_analyses[paper_id] = status

    # Create cancellation event
    cancel_event = asyncio.Event()
    _cancel_events[paper_id] = cancel_event

    try:
        # Mark paper as analyzing
        await execute_update(
            "UPDATE papers SET status = ? WHERE id = ?",
            ("analyzing", paper_id),
        )

        # Load paper text
        paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
        if paper is None:
            raise ValueError(f"Paper {paper_id} not found")

        folder_name = paper["folder_name"]
        paper_dir = get_paper_dir(folder_name)

        document_context = await run_pipeline_blocking(load_or_build_document_context, paper_dir)
        phase_inputs = document_context.get("phase_inputs", {})
        sections = document_context.get("sections", {})
        try:
            await schedule_paper_artifacts_refresh(paper_id, paper_dir)
        except Exception as exc:
            logger.warning("Background visual refresh scheduling failed for paper %s: %s", paper_id, exc)

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Phase 1: Screening
        r1 = await _run_screening(
            paper_id,
            str(phase_inputs.get("screening", "")),
            status,
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Phase 2: Citation Analysis (after screening, before visual)
        paper_authors = paper.get("authors", "") or ""
        r_cit = await _run_citation(
            paper_id,
            sections=sections,
            citation_body=str(phase_inputs.get("citation_body", "")),
            citation_references=str(phase_inputs.get("citation_references", "")),
            paper_authors=paper_authors,
            status=status,
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Phase 3: Visual Verification (independent of citation)
        r2 = await _run_visual(
            paper_id,
            str(phase_inputs.get("visual", "")),
            folder_name,
            status,
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Collect only successful results for downstream use
        previous = []
        if r1.get("text") and not _is_error_result(r1["text"]):
            previous.append(r1["text"])
        if r_cit.get("text") and not _is_error_result(r_cit["text"]):
            previous.append(r_cit["text"])
        if r2.get("text") and not _is_error_result(r2["text"]):
            previous.append(r2["text"])

        # Phase 4: Recipe Extraction (depends on text only)
        r3 = await _run_recipe(
            paper_id,
            str(phase_inputs.get("recipe", "")),
            status,
            screening_result_text=r1.get("text", ""),
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        if r3.get("text") and not _is_error_result(r3["text"]):
            previous.append(r3["text"])

        # Phase 4: Deep Dive (depends on all previous results)
        r4 = await _run_deep_dive(
            paper_id,
            str(phase_inputs.get("deep_dive", "")),
            previous,
            status,
            screening_result_text=r1.get("text", ""),
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        if r4.get("text") and not _is_error_result(r4["text"]):
            previous.append(r4["text"])

        # Phase 6: Visualization Planning & Generation (Gemini Pro 3)
        # Gemini Pro 3 decides up to 10 visualizations, each Mermaid or PaperBanana
        all_results = []
        if r1.get("text") and not _is_error_result(r1["text"]):
            all_results.append(r1["text"])
        if r_cit.get("text") and not _is_error_result(r_cit["text"]):
            all_results.append(r_cit["text"])
        if r2.get("text") and not _is_error_result(r2["text"]):
            all_results.append(r2["text"])
        if r3.get("text") and not _is_error_result(r3["text"]):
            all_results.append(r3["text"])
        if r4.get("text") and not _is_error_result(r4["text"]):
            all_results.append(r4["text"])

        if not (_result_was_skipped(r3) and _result_was_skipped(r4)):
            try:
                await _run_visualizations(
                    paper_id,
                    str(phase_inputs.get("visualization", "")),
                    folder_name,
                    all_results,
                    r3.get("text", ""),
                    r4.get("text", ""),
                    status,
                )
            except Exception as viz_err:
                # Visualization failure should NOT block the analysis from completing
                import logging
                logging.getLogger(__name__).warning(
                    "Visualization generation failed for paper %d: %s", paper_id, viz_err
                )

        # Check for cancellation one last time
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Mark paper as completed
        await execute_update(
            "UPDATE papers SET status = ?, analyzed_at = ? WHERE id = ?",
            ("completed", _utcnow_iso(), paper_id),
        )
        status.overall_status = "completed"

    except Exception as e:
        # Mark as error
        error_msg = f"{type(e).__name__}: {str(e)}"
        await execute_update(
            "UPDATE papers SET status = ? WHERE id = ?",
            ("error", paper_id),
        )
        status.overall_status = "error"

        # Record error in the current phase
        if status.phases:
            status.phases[-1].status = "error"
            status.phases[-1].error_message = error_msg

        # Store error as analysis result for debugging
        await execute_insert(
            """
            INSERT INTO analysis_results (paper_id, phase, result, model_used, input_hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                "error",
                json.dumps({"error": error_msg, "traceback": traceback.format_exc()}),
                "system",
                compute_input_hash(error_msg),
            ),
        )

    finally:
        # Clean up cancellation event
        _cancel_events.pop(paper_id, None)
        # Schedule cleanup of stale analyses after 1 hour
        async def _cleanup_stale():
            await asyncio.sleep(3600)  # 1 hour
            async with _analyses_lock:
                if paper_id in _running_analyses:
                    status = _running_analyses[paper_id]
                    if status.overall_status != "running":
                        del _running_analyses[paper_id]
        asyncio.create_task(_cleanup_stale())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/{paper_id}/run", status_code=202)
async def run_analysis(paper_id: int, background_tasks: BackgroundTasks):
    """
    Start the 4-phase analysis pipeline for a paper.
    Runs in background. Poll /status for progress.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    try:
        await ensure_text_artifacts_async(get_paper_dir(paper["folder_name"]))
    except (OdlParserError, OdlRuntimeError, FileNotFoundError) as exc:
        status_code, detail = explain_odl_failure(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to prepare text artifacts before analysis: {exc}",
        ) from exc

    async with _analyses_lock:
        # Check if already running
        if paper_id in _running_analyses:
            running = _running_analyses[paper_id]
            if running.overall_status == "running":
                raise HTTPException(
                    status_code=409,
                    detail=f"Analysis for paper {paper_id} is already running.",
                )

        # Clear in-memory state from previous run
        if paper_id in _running_analyses:
            del _running_analyses[paper_id]

    # Check budget before starting
    from api.settings import _get_all_settings
    settings = await _get_all_settings()
    monthly_limit = float(settings.get("monthly_budget_limit", "50.0"))

    # Calculate current month spending
    current_month = _utcnow().strftime("%Y-%m")
    month_start = f"{current_month}-01"
    month_num = int(current_month.split("-")[1])
    year = int(current_month.split("-")[0])
    if month_num == 12:
        month_end = f"{year + 1}-01-01"
    else:
        month_end = f"{year}-{month_num + 1:02d}-01"

    cost_rows = await fetch_all(
        "SELECT cost_usd FROM analysis_results WHERE created_at >= ? AND created_at < ? AND phase != 'error'",
        (month_start, month_end),
    )
    current_spending = sum(r.get("cost_usd") or 0.0 for r in cost_rows)

    if current_spending >= monthly_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget limit exceeded (${current_spending:.2f} / ${monthly_limit:.2f}). "
                   f"Increase your budget in Settings to continue.",
        )

    # Launch background analysis
    background_tasks.add_task(_run_full_analysis, paper_id)

    return {
        "paper_id": paper_id,
        "status": "started",
        "message": "Analysis pipeline started. Poll /status for progress.",
    }


@router.post("/{paper_id}/cancel", status_code=200)
async def cancel_analysis(paper_id: int):
    """
    Cancel a running analysis for a paper.
    """
    # Check if there's a cancel event for this paper
    if paper_id in _cancel_events:
        _cancel_events[paper_id].set()
        return {"paper_id": paper_id, "status": "cancelling"}

    # Check if the paper is running and update its status
    if paper_id in _running_analyses:
        running = _running_analyses[paper_id]
        if running.overall_status == "running":
            running.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return {"paper_id": paper_id, "status": "cancelled"}

    raise HTTPException(status_code=404, detail=f"No running analysis for paper {paper_id}")


@router.get("/{paper_id}/status", response_model=AnalysisStatus)
async def get_analysis_status(paper_id: int):
    """Get current analysis progress for a paper."""
    # Check in-memory status first
    if paper_id in _running_analyses:
        return _running_analyses[paper_id]

    # Fall back to DB
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    latest_results = await get_latest_completed_phase_rows(
        paper_id,
        phases=["screening", "citation", "visual", "recipe", "deep_dive", "visualization", "viz_plan"],
    )

    phases: list[PhaseStatus] = []
    total_cost = 0.0
    total_in = 0
    total_out = 0

    phase_order = ["screening", "citation", "visual", "recipe", "deep_dive"]
    completed_phases = set(latest_results.keys())

    for phase_name in phase_order:
        r = latest_results.get(phase_name)
        if r:
            cost = r.get("cost_usd") or 0.0
            tin = r.get("tokens_in") or 0
            tout = r.get("tokens_out") or 0
            phases.append(PhaseStatus(
                phase=AnalysisPhase(phase_name),
                status="completed",
                model_used=r.get("model_used"),
                tokens_in=tin,
                tokens_out=tout,
                cost_usd=cost,
                completed_at=r.get("created_at"),
            ))
            total_cost += cost
            total_in += tin
            total_out += tout
        else:
            phases.append(PhaseStatus(phase=AnalysisPhase(phase_name), status="pending"))

    # Check if visualization is also completed
    has_viz = "visualization" in completed_phases or "viz_plan" in completed_phases
    completed_main = len(completed_phases & set(phase_order))
    if has_viz:
        progress = (completed_main / 5) * 80 + 20  # 80% for 5 phases + 20% for viz
    else:
        progress = (completed_main / 5) * 80  # Max 80% without viz
    progress = min(progress, 100.0)

    return AnalysisStatus(
        paper_id=paper_id,
        overall_status=paper["status"],
        phases=phases,
        progress_pct=progress,
        total_cost_usd=total_cost,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
    )


@router.get("/{paper_id}/results", response_model=FullAnalysisResponse)
async def get_analysis_results(paper_id: int):
    """Get full analysis results across all phases."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    latest_results = await get_latest_completed_phase_rows(
        paper_id,
        phases=["screening", "citation", "visual", "recipe", "deep_dive"],
    )

    # Build status
    status = await get_analysis_status(paper_id)

    # Parse results by phase
    phase_data: dict[str, Optional[dict]] = {
        "screening": None,
        "citation": None,
        "visual": None,
        "recipe": None,
        "deep_dive": None,
    }

    for phase in phase_data:
        row = latest_results.get(phase)
        if row:
            phase_data[phase] = row.get("parsed_result")

    return FullAnalysisResponse(
        paper_id=paper_id,
        status=status,
        screening=phase_data["screening"],
        citation=phase_data["citation"],
        visual=phase_data["visual"],
        recipe=phase_data["recipe"],
        deep_dive=phase_data["deep_dive"],
    )


@router.get("/{paper_id}/figures", response_model=FigureListResponse)
async def get_figures(paper_id: int):
    """Get all extracted figures for a paper with AI analysis."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    paper_dir = get_paper_dir(paper["folder_name"])
    try:
        visual_contract, _, _ = await _get_visual_contract(
            paper_id,
            paper_dir,
            schedule_refresh=True,
        )
    except FileNotFoundError as exc:
        status_code, detail = explain_odl_failure(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc

    rows = await fetch_all(
        "SELECT * FROM figures WHERE paper_id = ? ORDER BY COALESCE(page_number, 999999), figure_num",
        (paper_id,),
    )

    figures = [FigureInfo(**figure_row_to_api_dict(row)) for row in rows]
    return FigureListResponse(
        figures=figures,
        total=len(figures),
        visual_state=visual_contract["visual_state"],
        visual_error=visual_contract["visual_error"],
        artifacts_ready=visual_contract["artifacts_ready"],
        artifacts_error=visual_contract["artifacts_error"],
    )


@router.get("/{paper_id}/tables", response_model=TableListResponse)
async def get_tables(paper_id: int):
    """Get all extracted tables for a paper."""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    paper_dir = get_paper_dir(paper["folder_name"])
    try:
        visual_contract, _, _ = await _get_visual_contract(
            paper_id,
            paper_dir,
            schedule_refresh=True,
        )
    except FileNotFoundError as exc:
        status_code, detail = explain_odl_failure(exc)
        raise HTTPException(status_code=status_code, detail=detail) from exc

    rows = await fetch_all(
        "SELECT * FROM tables WHERE paper_id = ? ORDER BY COALESCE(page_number, 999999), table_num",
        (paper_id,),
    )
    tables = [TableInfo(**table_row_to_api_dict(row)) for row in rows]
    return TableListResponse(
        tables=tables,
        total=len(tables),
        visual_state=visual_contract["visual_state"],
        visual_error=visual_contract["visual_error"],
        artifacts_ready=visual_contract["artifacts_ready"],
        artifacts_error=visual_contract["artifacts_error"],
    )


@router.get("/{paper_id}/recipe")
async def get_recipe(paper_id: int):
    """Get the extracted recipe card for a paper."""
    result = await get_latest_completed_phase_row(paper_id, "recipe")
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No recipe found for paper {paper_id}. Run analysis first.",
        )

    return {
        "paper_id": paper_id,
        "recipe": result.get("parsed_result"),
        "model_used": result.get("model_used"),
        "created_at": result.get("created_at"),
    }


@router.get("/{paper_id}/mermaid", response_model=MermaidResult)
async def get_mermaid(paper_id: int):
    """
    Generate a Mermaid diagram for the paper's experimental process flow.
    Uses Gemini for fast diagram generation.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # Check if recipe exists (we need it for the flow)
    folder_name = paper["folder_name"]
    paper_dir = get_paper_dir(folder_name)
    visualization_input = ""
    recipe_text = ""
    try:
        document_context = await run_pipeline_blocking(load_or_build_document_context, paper_dir)
        visualization_input = str(document_context.get("phase_inputs", {}).get("visualization", ""))
    except FileNotFoundError:
        pass
    recipe_result = await get_latest_completed_phase_row(paper_id, "recipe")
    if recipe_result:
        recipe_text = f"\n\nRecipe data:\n{_phase_result_snippet(recipe_result, 3000)}"

    prompt = f"""Generate a Mermaid flowchart diagram that shows the experimental process/methodology flow of this research paper.

{_MERMAID_SYNTAX_RULES}

{_MERMAID_STYLE_RULES}

추가 규칙: 모든 노드 레이블과 엣지 레이블을 반드시 한국어로 작성해.

Paper title: {paper['title']}
{recipe_text}

Paper text excerpt:
{visualization_input}

Return ONLY valid Mermaid syntax starting with "flowchart TD" or "flowchart LR".
"""

    result = await _call_gemini(prompt)

    mermaid_code = _sanitize_mermaid_code(result["text"])

    return MermaidResult(
        paper_id=paper_id,
        mermaid_code=mermaid_code,
        diagram_type="flowchart",
        description=f"Process flow diagram for: {paper['title']}",
    )


@router.get("/{paper_id}/visualizations", response_model=VisualizationPlanResponse)
async def get_visualizations(paper_id: int):
    """
    Get the visualization plan and generated diagrams/figures for a paper.
    Gemini Pro 3 plans up to 10 visualizations (Mermaid + PaperBanana mix).
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # Look for stored visualization results
    viz_result = await get_latest_completed_phase_row(paper_id, "visualization")

    if viz_result is None:
        # No visualizations generated yet
        return VisualizationPlanResponse(paper_id=paper_id)

    try:
        data = viz_result.get("parsed_result") or {}
        items = [VisualizationItem(**item) for item in data.get("items", [])]
        return VisualizationPlanResponse(
            paper_id=paper_id,
            items=items,
            total_count=data.get("total_count", len(items)),
            model_used=data.get("model_used", ""),
            planned_at=data.get("planned_at"),
        )
    except (json.JSONDecodeError, TypeError):
        return VisualizationPlanResponse(paper_id=paper_id)


async def _update_stored_visualization_item(
    paper_id: int, viz_id: int, new_fields: dict
) -> Optional[dict]:
    """Patch one item inside the latest stored visualization row.

    Returns the updated item dict, or None when no stored row/item matches.
    """
    viz_row = await get_latest_completed_phase_row(paper_id, "visualization")
    if viz_row is None:
        return None
    data = viz_row.get("parsed_result")
    if not isinstance(data, dict):
        return None
    items = data.get("items")
    if not isinstance(items, list):
        return None

    updated_item = None
    for item in items:
        if isinstance(item, dict) and item.get("id") == viz_id:
            item.update(new_fields)
            updated_item = item
            break
    if updated_item is None:
        return None

    await execute_update(
        "UPDATE analysis_results SET result = ? WHERE id = ?",
        (json.dumps(data, ensure_ascii=False), viz_row["id"]),
    )
    return updated_item


@router.post("/{paper_id}/mermaid/repair", response_model=MermaidResult)
async def repair_mermaid(paper_id: int, request: MermaidRepairRequest):
    """
    Self-heal a Mermaid diagram that failed to parse in the renderer.

    The client sends the failing code plus the parser error message; Gemini
    fixes the code while keeping the content and styling. When viz_id is
    given, the repaired code is persisted into the stored visualization row.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    prompt = f"""아래 Mermaid 코드가 파서 오류로 렌더링에 실패했어. 오류를 고친 전체 코드를 반환해줘.

{_MERMAID_SYNTAX_RULES}

파서 오류 메시지:
{request.error_message[:500]}

실패한 코드:
{request.mermaid_code[:6000]}

지침:
- 다이어그램의 내용(노드, 엣지, 레이블)과 스타일(classDef 색상, 화살표 종류)은 최대한 유지해.
- 파서 오류의 원인만 최소한으로 고쳐.
- linkStyle 인덱스가 엣지 수를 벗어나면 해당 linkStyle 줄을 삭제해.
- 수정된 전체 Mermaid 코드만 반환해. 설명 금지."""

    result = await _call_gemini(prompt, model=MODEL_MERMAID)
    repaired = _sanitize_mermaid_code(result["text"])
    if not repaired:
        raise HTTPException(status_code=502, detail="Repair produced empty Mermaid code.")

    if request.viz_id is not None:
        await _update_stored_visualization_item(
            paper_id,
            request.viz_id,
            {"mermaid_code": repaired, "status": "completed", "error_message": None},
        )

    return MermaidResult(
        paper_id=paper_id,
        mermaid_code=repaired,
        diagram_type="flowchart",
        description=None,
    )


@router.post(
    "/{paper_id}/visualizations/{viz_id}/regenerate",
    response_model=VisualizationItem,
)
async def regenerate_visualization(paper_id: int, viz_id: int):
    """
    Regenerate a single Mermaid visualization item with the current prompt
    (styling rules included) and persist it, without re-running the analysis.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    viz_row = await get_latest_completed_phase_row(paper_id, "visualization")
    data = (viz_row or {}).get("parsed_result") or {}
    items = data.get("items") if isinstance(data, dict) else None
    stored_item = next(
        (it for it in items or [] if isinstance(it, dict) and it.get("id") == viz_id),
        None,
    )
    if stored_item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Visualization {viz_id} not found for paper {paper_id}.",
        )
    if stored_item.get("tool") != "mermaid":
        raise HTTPException(
            status_code=400,
            detail="Only mermaid visualizations can be regenerated here.",
        )

    # Rebuild the generation contexts the pipeline used
    visualization_input = ""
    try:
        document_context = await run_pipeline_blocking(
            load_or_build_document_context, get_paper_dir(paper["folder_name"])
        )
        visualization_input = str(
            document_context.get("phase_inputs", {}).get("visualization", "")
        )
    except FileNotFoundError:
        pass

    phase_rows = await get_latest_completed_phase_rows(
        paper_id,
        phases=["screening", "citation", "visual", "recipe", "deep_dive"],
    )
    previous_results = [
        _phase_result_snippet(phase_rows[phase], 3000)
        for phase in ["screening", "citation", "visual", "recipe", "deep_dive"]
        if phase in phase_rows
    ]

    code = await _generate_single_mermaid(
        paper_id, stored_item, visualization_input, previous_results
    )
    if not code:
        raise HTTPException(status_code=502, detail="Regeneration produced empty Mermaid code.")

    updated = await _update_stored_visualization_item(
        paper_id,
        viz_id,
        {"mermaid_code": code, "status": "completed", "error_message": None},
    )
    return VisualizationItem(**(updated or {**stored_item, "mermaid_code": code}))


@router.get("/{paper_id}/report", response_model=ReportResponse)
async def get_report(paper_id: int):
    """
    Generate an integrated markdown report combining all analysis phases.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    latest_results = await get_latest_completed_phase_rows(
        paper_id,
        phases=["screening", "citation", "visual", "recipe", "deep_dive"],
    )

    if not latest_results:
        raise HTTPException(
            status_code=404,
            detail=f"No analysis results found for paper {paper_id}. Run analysis first.",
        )

    # Build report sections
    sections: list[str] = []
    sections.append(f"# Analysis Report: {paper['title']}\n")
    sections.append(f"**Authors:** {paper.get('authors', 'N/A')}")
    sections.append(f"**Year:** {paper.get('year', 'N/A')}")
    sections.append(f"**Journal:** {paper.get('journal', 'N/A')}")
    sections.append(f"**DOI:** {paper.get('doi', 'N/A')}")
    sections.append(f"**Domain:** {paper.get('domain', 'N/A')}")
    sections.append(f"**Agent:** {paper.get('agent_used', 'N/A')}")
    sections.append(f"**Analyzed:** {paper.get('analyzed_at', 'N/A')}")
    sections.append("")

    phase_titles = {
        "screening": "Phase 1: Screening",
        "citation": "Phase 2: Citation Analysis",
        "visual": "Phase 3: Visual Verification",
        "recipe": "Phase 4: Recipe Extraction",
        "deep_dive": "Phase 5: Deep Dive Analysis",
    }

    ordered_rows = [
        latest_results[phase]
        for phase in ["screening", "citation", "visual", "recipe", "deep_dive"]
        if phase in latest_results
    ]

    for r in ordered_rows:
        phase = r["phase"]
        title = phase_titles.get(phase, phase.title())
        sections.append(f"## {title}\n")
        sections.append(f"*Model: {r.get('model_used', 'N/A')} | "
                        f"Tokens: {r.get('tokens_in', 0):,} in / {r.get('tokens_out', 0):,} out | "
                        f"Cost: ${r.get('cost_usd', 0):.4f}*\n")

        parsed = r.get("parsed_result")
        sections.append(
            _format_phase_data(
                phase,
                parsed if isinstance(parsed, dict) else {"raw_text": r.get("result")},
            )
        )

        sections.append("")

    # Cost summary
    total_cost = sum(r.get("cost_usd", 0) or 0 for r in ordered_rows)
    total_in = sum(r.get("tokens_in", 0) or 0 for r in ordered_rows)
    total_out = sum(r.get("tokens_out", 0) or 0 for r in ordered_rows)
    sections.append("## Cost Summary\n")
    sections.append(f"- **Total Cost:** ${total_cost:.4f}")
    sections.append(f"- **Total Tokens In:** {total_in:,}")
    sections.append(f"- **Total Tokens Out:** {total_out:,}")

    markdown = "\n".join(sections)

    return ReportResponse(
        paper_id=paper_id,
        title=paper["title"],
        markdown=markdown,
        generated_at=_utcnow_iso(),
    )


@router.post("/{paper_id}/figures/{figure_id}/explain", response_model=FigureExplanationResponse)
async def explain_figure(paper_id: int, figure_id: int):
    """
    Generate a detailed expert-level explanation of a specific figure.
    Uses LLM to analyze the figure in context of the full paper text.
    Returns cached explanation if already generated.
    """
    return await explain_figure_handler(paper_id, figure_id)


@router.post("/{paper_id}/paperbanana", response_model=PaperBananaResponse)
async def generate_paperbanana(paper_id: int, request: PaperBananaRequest):
    """
    Generate a PaperBanana visual summary image for a paper.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    folder_name = paper["folder_name"]
    output_dir = get_paperbanana_dir(folder_name)

    # Get analysis results for the visual summary
    latest_results = await get_latest_completed_phase_rows(paper_id)
    analysis_data: dict = {}
    for phase, row in latest_results.items():
        parsed = row.get("parsed_result")
        if isinstance(parsed, dict) and "raw_text" in parsed:
            analysis_data[phase] = {"raw": parsed["raw_text"]}
        else:
            analysis_data[phase] = parsed

    # Generate the PaperBanana image
    try:
        image_path = await _generate_paperbanana_image(
            paper=paper,
            analysis_data=analysis_data,
            output_dir=output_dir,
            style=request.style,
            language=request.language,
            include_recipe=request.include_recipe,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate PaperBanana image: {str(e)}",
        )

    # Build the URL path for the static file server
    filename = Path(image_path).name
    image_url = f"/static/library/{folder_name}/paperbanana/{filename}"

    # Get image dimensions
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            width, height = img.size
    except Exception:
        width, height = 0, 0

    return PaperBananaResponse(
        paper_id=paper_id,
        image_path=str(image_path),
        image_url=image_url,
        width=width,
        height=height,
    )


# ---------------------------------------------------------------------------
# Experiment Planner
# ---------------------------------------------------------------------------

@router.post("/{paper_id}/experiment-plan")
async def generate_experiment_plan(paper_id: int):
    """Generate an experiment reproduction guide from the Recipe Card."""
    try:
        return await _generate_experiment_plan_impl(paper_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Experiment plan generation failed for paper %s", paper_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _generate_experiment_plan_impl(paper_id: int):
    from services.agents import get_agent_for_domain
    from services.pricing import calc_cost

    # 1. Load paper info
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # 2. Load recipe result (Phase 3 must be complete)
    recipe_row = await get_latest_completed_phase_row(paper_id, "recipe")
    if not recipe_row:
        raise HTTPException(
            status_code=400,
            detail="Recipe not found. Run analysis first (Phase 3 required).",
        )

    recipe_text = _phase_result_snippet(recipe_row, 5000)

    # 3. Load stable recipe context plus latest visual result for [MISSING] context
    paper_dir = get_paper_dir(paper["folder_name"])
    recipe_context = ""
    try:
        document_context = await run_pipeline_blocking(load_or_build_document_context, paper_dir)
        recipe_context = str(document_context.get("phase_inputs", {}).get("recipe", ""))
    except FileNotFoundError:
        pass

    visual_row = await get_latest_completed_phase_row(paper_id, "visual")
    visual_context = ""
    if visual_row:
        visual_context = f"\n\n시각 검증 결과:\n{_phase_result_snippet(visual_row, 2000)}"

    # 4. Get agent persona
    agent = get_agent_for_domain(paper["domain"] or "general")
    agent_persona = f"너는 {agent.profile.display_name_ko}({agent.profile.display_name}) 에이전트야. 성격: {agent.profile.personality}."

    # 5. Build prompt
    prompt = f"""{agent_persona}

너는 Sasoo(사수)라는 AI Co-Scientist의 실험 계획 도우미야.
아래 Recipe Card를 기반으로, 이 실험을 **재현하기 위한 실험 계획서**를 작성해줘.

모든 내용은 한국어로 작성해. JSON key만 영어로 유지.

Recipe Card:
{recipe_text}

논문 재현 컨텍스트:
{recipe_context}
{visual_context}

Return ONLY valid JSON (마크다운 펜스 없이):
{{
  "title": "실험 계획서 제목 (논문 기반)",
  "objective": "이 실험의 목표 (1-2문장)",
  "equipment_checklist": [
    {{"name": "장비명", "specification": "필요 사양", "essential": true/false}}
  ],
  "materials_checklist": [
    {{"name": "재료/시약명", "purity": "순도 (있으면)", "supplier": "공급처 (있으면)", "quantity": "필요량", "essential": true/false}}
  ],
  "procedure_steps": [
    {{"step": 1, "title": "단계 제목", "description": "구체적 절차 설명", "duration": "예상 소요 시간", "critical_params": ["핵심 파라미터1", "파라미터2"]}}
  ],
  "warnings": [
    {{"type": "missing_param | safety | calibration | environment", "severity": "high | medium | low", "message": "구체적 경고 메시지"}}
  ],
  "estimated_total_time": "전체 예상 소요 시간",
  "estimated_difficulty": "easy | moderate | hard",
  "mentor_comments": [
    "사수로서의 실전 팁이나 주의사항 (에이전트 성격 반영)"
  ]
}}
"""

    result = await _call_gemini(prompt)
    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Experiment plan JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])

    # 6. Save to DB
    plan_id = await execute_insert(
        """INSERT INTO experiment_plans (paper_id, content, model_used, tokens_in, tokens_out, cost_usd)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (paper_id, result["text"], result["model"],
         result["tokens_in"], result["tokens_out"], cost),
    )

    return {
        "id": plan_id,
        "paper_id": paper_id,
        "content": json.loads(result["text"]) if result["text"].strip().startswith("{") else {"raw": result["text"]},
        "model_used": result["model"],
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
        "cost_usd": cost,
    }


@router.get("/{paper_id}/experiment-plan")
async def get_experiment_plan(paper_id: int):
    """Get the most recent experiment plan for a paper."""
    row = await fetch_one(
        "SELECT * FROM experiment_plans WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1",
        (paper_id,),
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No experiment plan found for paper {paper_id}. Generate one first.",
        )

    try:
        content = json.loads(row["content"])
    except (json.JSONDecodeError, TypeError):
        content = {"raw": row["content"]}

    return {
        "id": row["id"],
        "paper_id": row["paper_id"],
        "content": content,
        "model_used": row["model_used"],
        "tokens_in": row["tokens_in"],
        "tokens_out": row["tokens_out"],
        "cost_usd": row["cost_usd"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Agent Chat (SSE streaming)
# ---------------------------------------------------------------------------

_CHAT_MODEL = MODEL_CHAT

# The analysis path already retries transient failures; chat used to fail on the
# first blip, which is exactly when the pipeline is hammering the same quota.
_CHAT_MAX_ATTEMPTS = 3


@router.post("/{paper_id}/chat")
async def chat_with_agent(paper_id: int, request: Request):
    """Stream a chat response from the agent about this paper via SSE."""
    try:
        return await _chat_with_agent_impl(paper_id, request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Chat endpoint failed for paper %s", paper_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _chat_with_agent_impl(paper_id: int, request: Request):
    from services.agents import get_agent_for_domain

    body = await request.json()
    message = body.get("message", "").strip()
    history = body.get("history", [])

    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    # 1. Load paper
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if not paper:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # 2. Load stable chat context plus latest completed phase snippets
    paper_dir = get_paper_dir(paper["folder_name"])
    chat_context = ""
    try:
        # Reserved pool: the pipeline must never be able to queue a question
        # behind its own fan-out.
        document_context = await run_chat_blocking(load_or_build_document_context, paper_dir)
        chat_context = str(document_context.get("phase_inputs", {}).get("chat", ""))
    except (FileNotFoundError, RuntimeError) as exc:
        # A `force` artifact refresh deletes and rebuilds the text sidecar; a chat
        # request landing inside that window raises rather than 404s. Answer from
        # the phase snippets alone instead of failing the turn.
        logger.warning("Chat context unavailable for paper %s: %s", paper_id, exc)

    latest_phase_rows = await get_latest_completed_phase_rows(
        paper_id,
        phases=["screening", "citation", "visual", "recipe", "deep_dive"],
    )
    phases_data: dict[str, str] = {}
    for phase in ["screening", "citation", "visual", "recipe", "deep_dive"]:
        row = latest_phase_rows.get(phase)
        if row:
            phases_data[phase] = _phase_result_snippet(row, 3000)

    # 3. Get agent persona
    agent = get_agent_for_domain(paper["domain"] or "general")
    agent_persona = (
        f"너는 {agent.profile.display_name_ko}({agent.profile.display_name}) 에이전트야. "
        f"성격: {agent.profile.personality}."
    )

    # 4. Build system prompt
    paper_info = f"논문: {paper['title']}"
    if paper.get("authors"):
        paper_info += f"\n저자: {paper['authors']}"
    if paper.get("year"):
        paper_info += f"\n연도: {paper['year']}"
    if paper.get("journal"):
        paper_info += f"\n저널: {paper['journal']}"

    phase_labels = {
        "screening": "스크리닝 결과",
        "citation": "인용 분석 결과",
        "visual": "시각 분석 결과",
        "recipe": "레시피 추출 결과",
        "deep_dive": "심층 분석 결과",
    }
    context_parts = [paper_info]
    if chat_context:
        context_parts.append(f"\n--- 논문 컨텍스트 ---\n{chat_context}")
    for phase, label in phase_labels.items():
        if phase in phases_data:
            context_parts.append(f"\n--- {label} ---\n{phases_data[phase]}")

    system_prompt = (
        f"{_SYSTEM_INSTRUCTION_KO}\n\n"
        f"{agent_persona}\n\n"
        f"아래는 이 논문의 분석 결과야. 사용자의 질문에 분석 결과를 바탕으로 답변해줘. "
        f"모르는 내용은 솔직히 모른다고 하고, 추측할 때는 추측임을 밝혀.\n\n"
        + "\n".join(context_parts)
    )

    # 5. Build Gemini contents from history
    from google.genai import types as _gtypes

    contents = []
    for msg in history[-20:]:  # limit history to last 20 messages
        role = "user" if msg.get("role") == "user" else "model"
        contents.append(
            _gtypes.Content(role=role, parts=[_gtypes.Part.from_text(text=msg.get("content", ""))])
        )
    contents.append(
        _gtypes.Content(role="user", parts=[_gtypes.Part.from_text(text=message)])
    )

    # 6. Stream via SSE, entirely on the event loop through the async SDK client.
    #
    # The previous implementation drove the sync stream from asyncio's default
    # thread pool and bridged chunks back with run_coroutine_threadsafe. When the
    # visualization phase filled that pool the bridge thread never started, and
    # the consumer below had no timeout — so the response opened, emitted nothing,
    # and hung forever. Taking no thread at all removes the failure mode instead
    # of tuning around it.
    async def event_generator():
        tokens_in = 0
        tokens_out = 0
        streamed_any = False
        last_error: Exception | None = None

        for attempt in range(_CHAT_MAX_ATTEMPTS):
            try:
                client = _get_gemini_client()
                config = _gtypes.GenerateContentConfig(system_instruction=system_prompt)
                stream = await client.aio.models.generate_content_stream(
                    model=_CHAT_MODEL,
                    contents=contents,
                    config=config,
                )

                async for chunk in stream:
                    if await request.is_disconnected():
                        logger.info(
                            "Chat client disconnected for paper %s; abandoning stream", paper_id
                        )
                        return

                    text = chunk.text or ""
                    if text:
                        streamed_any = True
                        yield f"data: {json.dumps({'type': 'token', 'content': text}, ensure_ascii=False)}\n\n"

                    usage = getattr(chunk, "usage_metadata", None)
                    if usage:
                        tokens_in = getattr(usage, "prompt_token_count", 0) or tokens_in
                        tokens_out = getattr(usage, "candidates_token_count", 0) or tokens_out

                cost = calc_cost(_CHAT_MODEL, tokens_in, tokens_out)
                yield f"data: {json.dumps({'type': 'done', 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'cost_usd': cost}, ensure_ascii=False)}\n\n"
                return

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Chat stream failed for paper %s (attempt %d/%d): %s",
                    paper_id, attempt + 1, _CHAT_MAX_ATTEMPTS, exc,
                )
                # Once tokens are on the wire the answer cannot be restarted, so a
                # mid-stream failure is terminal no matter how many attempts remain.
                if streamed_any or attempt == _CHAT_MAX_ATTEMPTS - 1:
                    break
                await asyncio.sleep(2 ** attempt)

        logger.error("Chat stream error for paper %s: %s", paper_id, last_error)
        yield f"data: {json.dumps({'type': 'error', 'message': str(last_error)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
