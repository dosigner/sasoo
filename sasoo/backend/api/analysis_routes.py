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
import base64
import json
import logging
import os
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
    AnalysisStatus,
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
    parse_phase_row,
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
from services.llm.interactions_client import call_interaction, stream_interaction

from api.analysis_state import _running_analyses, _cancel_events, _analyses_lock
from api.analysis_helpers import (
    _clean_llm_json,
    _is_error_result,
    _stage_result_defect,
    _SYSTEM_INSTRUCTION_KO,
)
from services.model_registry import ModelChoice, active_provider, resolve as resolve_model
from services.provider_state import key_env_for
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


async def _get_cached_phase_result(
    paper_id: int,
    phase: str,
    input_text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> Optional[dict]:
    cached = await find_cached_phase_result(
        paper_id, phase, input_text, provider=provider, model=model, effort=effort,
    )
    if cached is None:
        return None
    fallback_hash = compute_input_hash(input_text, provider=provider, model=model, effort=effort)
    await execute_insert(
        """
        INSERT INTO analysis_cache_events
            (paper_id, phase, input_hash, source_model, estimated_cost_usd, tokens_in, tokens_out)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            phase,
            cached.input_hash or fallback_hash,
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
        "input_hash": cached.input_hash or fallback_hash,
    }


def _config_hash(provider: str | None, model: str | None, effort: str | None) -> str:
    """(provider, model, effort) 지문 — 문서 내용을 포함하지 않는다.

    Task 11(스펙 §D 2단계 조회)의 stage-1 키. input_hash는 문서 전체를 포함해
    GET 상태 조회 시점에 재구성하려면 프롬프트 전체를 다시 만들어야 한다(비용
    큰 중복). 이 지문은 그 비용 없이 "이 설정으로 이미 분석해본 적이 있는가"만
    싸게 판정하기 위한 의도적 단순화다 — 문서가 바뀐 경우까지는 잡지 못하지만,
    Task 6이 바꾼 캐시 키(provider/model/effort)의 후속 조치인 이 배지 기능의
    범위 안에서는 충분하다. compute_input_hash(input_text="")의 퇴화형이라
    별도 해시 스킴을 새로 만들지 않는다.
    """
    return compute_input_hash("", provider=provider, model=model, effort=effort)


def _stale_model_for_row(row: dict, current_hash: str, current_model: str) -> Optional[str]:
    """phase의 최신 행 하나(row)만 보고 stale_model을 판정한다(추가 조회 없음, 순수함수).

    - config_hash가 있고 current_hash와 같으면: 이 설정으로 이미 분석해본 적이
      있다는 뜻 -> stale 아님(None).
    - config_hash가 있고 다르면(config_hash 컬럼 도입 이후 행인데 지금 설정과
      다름 — effort만 바뀐 경우 포함): stale, 옛 model_used를 그대로 싣는다
      (스펙 §D — 캐시 키가 다르면 다른 결과다).
    - config_hash가 NULL이면: config_hash 컬럼은 additive 마이그레이션이라 그
      이전에 쓰인 행은 전부 NULL이다 — 이 경우 "다른 설정으로 분석됨"을 판단할
      근거가 model_used뿐이므로, 옛 model_used를 현재 모델명과 직접 비교한다.
      같으면 stale 아님(리뷰 Important I1 — 안 그러면 아무것도 안 바꾼 사용자의
      기존 분석 전부에 "다른 모델로 분석됨" 배지가 상시 오탐된다), 다르면 stale.
    """
    config_hash = row.get("config_hash")
    if config_hash is not None:
        return None if config_hash == current_hash else row.get("model_used")
    return None if row.get("model_used") == current_model else row.get("model_used")


async def _lookup_phase_result_with_staleness(
    paper_id: int,
    phase: str,
    current_hash: str,
    current_model: str,
    *,
    latest_row: Optional[dict] = None,
) -> Optional[dict]:
    """phase 결과의 2단계 조회(스펙 §D) + 레거시 행 오탐 수정(I1) + 폴링 부하 완화(I2).

    latest_row: 호출측이 이미 들고 있는 이 phase의 최신 analysis_results 행
    (예: get_latest_completed_phase_rows가 SELECT *로 이미 가져온 dict — 거기엔
    config_hash·model_used가 이미 있다). 넘기면 이 함수는 DB를 전혀 조회하지
    않고 그 값만으로 stale을 판정한다 — /status가 2초 간격으로 폴링하며
    phase마다 최대 2쿼리씩 태우던 부하(리뷰 Important I2)를 없앤다. 대가로
    "최신 행은 다른 설정인데 그보다 오래된 행 중 현재 설정과 일치하는 게
    있는가"(stage-1의 전체 이력 매치)는 더 보지 않는다 — 최신 행 하나만 본다.
    None이면(호출측에 미리 가져온 행이 없으면) 아래 2단계 DB 조회로 폴백한다.

    1. 현재 (provider, model, effort) 지문(config_hash)으로 조회 → 히트하면
       이 설정으로 이미 분석해본 적이 있다는 뜻이라 stale_model=None으로 그대로
       쓴다.
    2. 미스면 phase의 최신 행을 stale_model과 함께 돌려준다 — "다른 모델로
       분석됨" 배지 + 재분석 안내(get_analysis_status)의 데이터 소스. 행이
       아예 없으면 None. stale_model 판정은 _stale_model_for_row를 공유한다
       (레거시 행 NULL config_hash 처리 포함).
    """
    if latest_row is not None:
        parsed = dict(latest_row)
        parsed["stale_model"] = _stale_model_for_row(parsed, current_hash, current_model)
        return parsed

    row = await fetch_one(
        """
        SELECT * FROM analysis_results
        WHERE paper_id = ? AND phase = ? AND config_hash = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (paper_id, phase, current_hash),
    )
    if row is not None:
        parsed = parse_phase_row(row)
        parsed["stale_model"] = None
        return parsed

    latest = await fetch_one(
        """
        SELECT * FROM analysis_results
        WHERE paper_id = ? AND phase = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (paper_id, phase),
    )
    if latest is None:
        return None
    parsed = parse_phase_row(latest)
    parsed["stale_model"] = _stale_model_for_row(parsed, current_hash, current_model)
    return parsed


# 게이트가 applicable=False로 스킵하기 전 요구하는 최소 확신도(잠정값 0.6 — e2e 분포로 재조정).
_GATE_CONFIDENCE_FLOOR = 0.6

# M6: citation phase 캐시 키 한정 버전 태그(현재 소비처: _citation_cache_key,
# _run_citation의 non-top_refs 폴백 input_hash — 둘 다 citation phase). 프롬프트
# 문구가 아닌 "안정 콘텐츠 + 이 버전"으로 캐시 키를 구성한다. 문구를 바꿔도 재과금이
# 없고, citation phase의 계약이 실제로 바뀔 때만 이 값을 올려 1회 무효화한다.
_CITATION_PROMPT_VERSION = "2026-07-14"


def _screening_gate_decision(
    screening_result_text: Optional[str], phase: str = "recipe"
) -> tuple[bool, str]:
    """스크리닝 결과로 phase(recipe|deep_dive)의 자동 실행 여부를 정한다.

    신규 스크리닝 결과는 phase별 applicable 플래그를 신뢰하고(리뷰 논문은
    recipe만 스킵, deep_dive는 실행), 플래그가 없는 과거 캐시 결과는 기존
    relevance 휴리스틱으로 폴백한다."""
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

    if relevance < 0.35:
        return (True, "low_relevance_screening")

    applicable = payload.get(f"{phase}_applicable")
    if applicable is False:
        # 확신이 낮은 오판정으로 phase를 차단하지 않는다: confidence가 floor 미만이면 실행.
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError):
            confidence = 1.0  # confidence 미제공(레거시)은 플래그를 신뢰
        if confidence < _GATE_CONFIDENCE_FLOOR:
            return (False, "")
        return (True, f"not_applicable_{phase}")
    if applicable is True:
        return (False, "")

    # 레거시 결과(applicable 플래그 없음): 기존 휴리스틱 유지
    domain = str(payload.get("domain") or "").strip().lower()
    key_topics = payload.get("key_topics") or []
    is_experimental = bool(payload.get("is_experimental", True))
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


def _build_chain_restart_context(
    previous_results: Optional[list[str]], per_stage_limit: int = 4000
) -> str:
    """체인 재시작 시 이전 스테이지 결과 텍스트를 프롬프트에 복원하기 위한 컨텍스트를 만든다.

    중간 스테이지가 캐시 히트/스킵되어 previous_interaction_id가 유실되면 서버측 체인
    상태가 끊긴다. 이때 다음 스테이지가 이전 분석 결과를 잃지 않도록, 지금까지 성공한
    이전 스테이지 결과를 스테이지당 per_stage_limit(폴백 경로의 4000자 관례)로 truncate해
    이어붙인다."""
    if not previous_results:
        return ""
    parts = [str(r)[:per_stage_limit] for r in previous_results if r]
    return "\n\n".join(parts)


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
    interaction_id: str | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> None:
    await execute_insert(
        """
        INSERT INTO analysis_results
            (paper_id, phase, result, model_used, tokens_in, tokens_out, cost_usd, input_hash, interaction_id, config_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            phase,
            result_text,
            model_used,
            tokens_in,
            tokens_out,
            cost_usd,
            compute_input_hash(input_text, provider=provider, model=model, effort=effort),
            interaction_id,
            _config_hash(provider, model, effort),
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

_SCREENING_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "enum": ["optics", "bio", "ai_ml", "ee", "general"]},
        "agent_recommended": {"type": "string", "enum": ["photon", "cell", "neural", "circuit"]},
        "relevance_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "recipe_applicable": {"type": "boolean"},
        "deep_dive_applicable": {"type": "boolean"},
        "applicability_reason": {"type": "string"},
        "key_topics": {"type": "array", "items": {"type": "string"}},
        "methodology_type": {"type": "string", "enum": ["experimental", "computational", "theoretical", "review"]},
        "summary": {"type": "string"},
        "is_experimental": {"type": "boolean"},
        "has_figures": {"type": "boolean"},
        "estimated_complexity": {"type": "string", "enum": ["low", "medium", "high"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [
        "domain", "summary", "relevance_score", "key_topics", "is_experimental",
        "methodology_type", "recipe_applicable", "deep_dive_applicable",
    ],
}

_CITATION_SCHEMA = {
    "type": "object",
    "properties": {
        "ref_analyses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref_id": {"type": "string"},
                    "citation_role": {
                        "type": "string",
                        "enum": ["foundational", "methodological", "comparative",
                                 "supporting", "contrasting", "unclear"],
                    },
                    "evidence_context": {"type": "string"},
                    "why_cited": {"type": "string"},
                },
                "required": ["ref_id", "citation_role", "why_cited"],
            },
        },
        "summary": {"type": "string"},
        "citation_balance": {
            "type": "string",
            "enum": ["balanced", "heavily_reliant", "self_citation_heavy", "diverse"],
        },
        "key_influences": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "string"},
    },
    "required": ["ref_analyses", "summary", "citation_balance"],
}


def _result_cost(result: dict) -> float:
    """LLM 호출 결과 하나의 USD 비용을 계산한다(R7-3).

    재시도가 있었던 결과는 tokens_in/tokens_out이 이미 attempt 합산값이라
    (사용량 표시를 위해 유지) calc_cost(model, tokens_in, tokens_out)을 그대로
    호출하면 마지막 attempt 단가가 합산 토큰 전체에 적용돼 앞선 attempt 비용이
    이중 계산되거나(평면 단가) 장문 임계값이 잘못 적용된다(단가 구간 있는
    모델). 재시도 게이트가 attempt별로 미리 계산해 둔 총비용
    (result["cost_usd_prior_attempts"])이 있으면 그 값을 그대로 쓰고,
    없으면(재시도가 없었던 결과) 평소대로 단일 attempt 비용을 계산한다.
    """
    prior_total = result.get("cost_usd_prior_attempts")
    if prior_total is not None:
        return prior_total
    return calc_cost(result["model"], result["tokens_in"], result["tokens_out"])


async def _run_screening(
    paper_id: int, screening_input: str, status: AnalysisStatus, *, provider: str = "gemini",
) -> dict:
    """Phase 1: Screening - classify domain, score relevance, extract topics."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.SCREENING,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.SCREENING
    prompt = f"""논문 텍스트:
{screening_input}

위 논문을 후속 분석 단계에 배정하기 위한 스크리닝 평가를 해줘.

판정 기준:
- domain: optics|bio|ai_ml|ee|general 중 하나
- agent_recommended: photon|cell|neural|circuit 중 하나
- relevance_score: 연구 논문으로서 분석할 실질이 있는지 (0.0=분석할 내용 없음, 1.0=분석 가치가 충분한 연구 논문)
- recipe_applicable: 재현 가능한 실험·학습·설계 절차가 논문에 있는지
- deep_dive_applicable: 기여·방법·근거·한계를 분석할 실질 내용이 있는지
- applicability_reason: 위 두 판정의 근거 1문장 (한국어)
- key_topics: 핵심 주제 리스트
- methodology_type: experimental|computational|theoretical|review 중 하나
- summary: 2-3문장 요약 (한국어)
- is_experimental: 실험 논문 여부 / has_figures: 그림 포함 여부
- estimated_complexity: low|medium|high 중 하나
- confidence: 이 스크리닝 판정 자체의 확신도 (0.0~1.0)

경계 예시:
- 리뷰 논문: recipe_applicable=false, deep_dive_applicable=true
- 실험 세부가 없는 사설·초록만 있는 문서: 둘 다 false 가능
불확실하면 applicable을 성급히 false로 두지 말고 confidence를 낮춰.
"""

    choice = resolve_model("screening", provider)
    cached = await _get_cached_phase_result(
        paper_id, "screening", prompt, provider=provider, model=choice.model, effort=choice.effort,
    )
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

    async def _invoke() -> dict:
        return await call_interaction(
            prompt,
            lane="pipeline",
            model=choice.model,
            thinking_level=choice.effort,
            response_schema=_SCREENING_SCHEMA,
            store=False,
        )

    result = await _invoke()
    defect = _stage_result_defect(result.get("text") or "")
    if defect:
        logger.warning(
            "screening %s (tokens_out=%s); retrying once",
            defect, result.get("tokens_out"),
        )
        retry = await _invoke()
        # 재시도 사용량은 attempt별로 비용을 계산해 합산한다(R7-3) — 토큰을
        # 합쳐 한 번에 계산하면 장문 임계값이 잘못 적용되거나(단가 구간 있는
        # 모델) 이후 tokens_in/out 합산과 겹쳐 비용이 이중 계산된다.
        retry["cost_usd_prior_attempts"] = calc_cost(
            result["model"], result.get("tokens_in") or 0, result.get("tokens_out") or 0,
        ) + calc_cost(
            retry["model"], retry.get("tokens_in") or 0, retry.get("tokens_out") or 0,
        )
        # 사용량 표시(tokens_in/out)는 실사용 총량이 맞으므로 토큰 합산은 유지한다.
        retry["tokens_in"] = (result.get("tokens_in") or 0) + (retry.get("tokens_in") or 0)
        retry["tokens_out"] = (result.get("tokens_out") or 0) + (retry.get("tokens_out") or 0)
        result = retry

    # structured output 실패 대비 안전망: 마크다운 펜스 제거 후 JSON 검증
    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 1 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = _result_cost(result)

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
        interaction_id=result.get("interaction_id"),
        provider=provider,
        model=choice.model,
        effort=choice.effort,
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


def _norm_ref_id(raw: object) -> str:
    """ref_id를 병합 비교용으로 정규화한다(대괄호·공백·'ref'/'#' 선행 표기 제거, 소문자)."""
    s = str(raw or "").strip().lower()
    for ch in ("[", "]", "(", ")", "#"):
        s = s.replace(ch, "")
    if s.startswith("ref"):
        s = s[3:]
    return s.strip()


def _build_top_by_norm(top_cited: list) -> dict:
    """정규화 키 → top_cited 항목. 동일 키 중복 시 첫 항목 우선(원본 병합 루프의 break 의미 보존)."""
    mapping: dict = {}
    for tc in top_cited:
        mapping.setdefault(_norm_ref_id(tc.get("ref_id")), tc)
    return mapping


def _citation_cache_key(local_result: dict, citation_body: str) -> str:
    """인용 phase 캐시 키: 프롬프트 문구가 아닌 안정 콘텐츠 + _CITATION_PROMPT_VERSION.

    문구를 고쳐도 재과금이 없고, 계약이 실제로 바뀔 때 _CITATION_PROMPT_VERSION을 올려 1회 무효화한다."""
    top = [
        {
            "ref_id": r.get("ref_id"),
            "cite_count": r.get("cite_count"),
            "contexts": [
                {"s": (c.get("sentence") or "")[:300], "sec": c.get("section") or ""}
                for c in (r.get("cite_contexts") or [])[:5]
            ],
        }
        for r in local_result.get("top_cited", [])[:10]
    ]
    payload = {
        "v": _CITATION_PROMPT_VERSION,
        "phase": "citation",
        "total_references": local_result.get("total_references", 0),
        "citation_style": local_result.get("citation_style", ""),
        "self_citation_count": local_result.get("self_citation_count", 0),
        "top": top,
        "body": citation_body[:3000],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


async def _run_citation(
    paper_id: int,
    sections: dict[str, str],
    citation_body: str,
    citation_references: str,
    paper_authors: str,
    status: AnalysisStatus,
    *,
    provider: str = "gemini",
) -> dict:
    """Phase 2: Citation Analysis - parse references, count citation frequency, analyze roles."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.CITATION,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.CITATION

    choice = resolve_model("citation", provider)

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
            ctx_parts = []
            for c in contexts[:5]:
                sentence = (c.get("sentence") or "")[:300]
                sec = (c.get("section") or "").strip()
                ctx_parts.append(f"[{sec or '위치미상'}] {sentence}" if sentence else "")
            ctx_str = "; ".join(p for p in ctx_parts if p)
            top_refs_text += (
                f"{i}. {ref.get('ref_id', '')} {ref.get('authors', '')} "
                f"({ref.get('year', '?')}): \"{ref.get('title', '')}\" "
                f"[{ref.get('journal', '')}] — 인용 {ref.get('cite_count', 0)}회\n"
                f"   인용 맥락: {ctx_str}\n\n"
            )

        llm_prompt = f"""아래는 로컬 파서가 이 논문에서 추출한 참고문헌 통계와 상위 인용 맥락이야.

[인용 데이터]
총 참고문헌 수: {local_result.get('total_references', 0)}
인용 스타일: {local_result.get('citation_style', 'numbered')}
셀프 인용: {local_result.get('self_citation_count', 0)}건 (비율: {local_result.get('self_citation_ratio', 0):.1%})

가장 많이 인용된 상위 10개 참고문헌과 인용 맥락:
{top_refs_text}

[논문 본문 발췌 (맥락용)]
{citation_body[:3000]}

위 데이터에 근거해서만 이 논문 내부의 인용 사용 패턴을 분석해줘.

규칙:
- citation_role은 인용 맥락과 참고문헌의 제목·저널 정보를 근거로 가장 그럴듯한 역할을 골라. 제목·저널도 위에 제공된 데이터니까 이를 근거로 판단하는 건 날조가 아니야.
- "unclear"는 최후 수단이야 — 인용 맥락과 제목·저널 어느 쪽으로도 판단할 수 없을 때만 써.
- evidence_context에는 분류 근거가 된 인용 맥락 문장을 위 자료에서 한 구절 그대로 옮겨 적어. 맥락이 아닌 제목·저널로 판단했다면 "(제목 근거)"라고 적어.
- why_cited는 왜 자주 인용됐는지 2-3문장(한국어)으로 써.
- 참고문헌의 실제 내용·존재 여부·학계 전체 영향력은 검증된 것처럼 말하지 마.
- key_influences는 위에 제시된 참고문헌 안에서만 골라 — 목록에 없는 연구를 추가하지 마.
- summary는 전체 인용 패턴 평가 2-3문장(한국어). limitations에는 상위 10개와 본문 발췌만 본 평가라는 한계를 한 문장으로 남겨.
"""

        cache_key = _citation_cache_key(local_result, citation_body)
        cached = await _get_cached_phase_result(
            paper_id, "citation", cache_key, provider=provider, model=choice.model, effort=choice.effort,
        )
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
            result = await call_interaction(
                llm_prompt,
                lane="pipeline",
                model=choice.model,
                thinking_level=choice.effort,
                response_schema=_CITATION_SCHEMA,
                store=False,
            )
            cleaned_text = _clean_llm_json(result["text"])

            try:
                llm_data = json.loads(cleaned_text)
            except json.JSONDecodeError:
                llm_data = {}

            # Merge LLM analysis into local_result (ref_id 포맷 드리프트 허용)
            ref_analyses = llm_data.get("ref_analyses", [])
            top_cited = local_result.get("top_cited", [])
            top_by_norm = _build_top_by_norm(top_cited)
            for ra in ref_analyses:
                norm = _norm_ref_id(ra.get("ref_id", ""))
                tc = top_by_norm.get(norm)
                if tc is None:
                    logger.warning(
                        "citation merge drop: ref_id=%r (norm=%r) not in top_cited for paper %s",
                        ra.get("ref_id"), norm, paper_id,
                    )
                    continue
                tc["citation_role"] = ra.get("citation_role", "")
                tc["why_cited"] = ra.get("why_cited", "")
                tc["evidence_context"] = ra.get("evidence_context", "")

            local_result["summary"] = llm_data.get("summary", "")
            local_result["citation_balance"] = llm_data.get("citation_balance", "")
            local_result["key_influences"] = llm_data.get("key_influences", [])
            local_result["citation_limitations"] = llm_data.get("limitations", "")

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
            # 최상위 error 키를 남겨 이 열화 결과가 캐시로 재사용되지 않게 한다.
            # (find_cached_phase_result가 _parse_error/error 키를 가진 행을 캐시 미스로 처리)
            # 없으면 일시적 네트워크·인증 실패가 인용 분석을 영구히 무력화한다 — 실측된 결함.
            local_result["error"] = f"citation LLM 분석 실패: {exc}"
            cost = 0.0

    else:
        local_result["summary"] = ""
        cost = 0.0

    input_hash_source = (
        _citation_cache_key(local_result, citation_body)
        if top_refs
        else json.dumps(
            {
                "v": _CITATION_PROMPT_VERSION,
                "phase": "citation",
                "citation_body": citation_body,
                "citation_references": citation_references,
                "paper_authors": paper_authors,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    if not top_refs:
        cached = await _get_cached_phase_result(
            paper_id, "citation", input_hash_source, provider=provider, model=choice.model, effort=choice.effort,
        )
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
        provider=provider,
        model=choice.model,
        effort=choice.effort,
    )

    phase_status.status = "completed"
    phase_status.completed_at = _utcnow_iso()
    status.progress_pct = max(status.progress_pct, 16.0)

    return {"text": result_json, "model": phase_status.model_used or "local",
            "tokens_in": phase_status.tokens_in or 0, "tokens_out": phase_status.tokens_out or 0}


# ---------------------------------------------------------------------------
# Stateful chain: Visual -> Recipe -> Deep Dive -> Viz planning (gemini-3.6-flash)
# ---------------------------------------------------------------------------

# 체인 스테이지 이름과 레지스트리 role의 번역표.
# "visualization"(파이프라인 내부 명)만 레지스트리 role "viz_planning"과 다르다.
_PHASE_TO_ROLE = {
    "visual": "visual",
    "recipe": "recipe",
    "deep_dive": "deep_dive",
    "visualization": "viz_planning",
}


def _stage_choice(phase: str, provider: str) -> ModelChoice:
    return resolve_model(_PHASE_TO_ROLE[phase], provider)


_VISUAL_SCHEMA = {
    "type": "object",
    "properties": {
        "figure_count": {"type": "integer"},
        "tables_found": {"type": "integer"},
        "equations_found": {"type": "integer"},
        "diagram_types": {"type": "array", "items": {"type": "string"}},
        "quality_summary": {"type": "string"},
        "key_findings_from_visuals": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["quality_summary", "key_findings_from_visuals"],
}

_VISUAL_INSTRUCTION = """이 논문의 그림·표·수식을 검증해줘.

figure_count(그림 수), tables_found(표 수), equations_found(수식 수),
diagram_types(다이어그램 종류: SEM/TEM/spectrum/graph/photograph/schematic 등),
quality_summary(그림 품질 전체 평가, 한국어), key_findings_from_visuals(시각자료에서
읽어낸 핵심 사항 리스트, 한국어)를 채워줘.

규칙:
- key_findings_from_visuals의 각 항목은 근거가 된 그림/표 번호로 시작해(예: "Fig. 3: ...", "Table 2: ...").
- 그림에서 실제로 읽을 수 있는 내용만 관찰로 적어. 수치·글자가 안 읽히면 추측하지 말고 "판독 불가"라고 표시해.
- 본문 주장과 그림 내용이 어긋나는 지점이 보이면 짚어줘.
- 함께 제공되는 figure/table 메타데이터(quality/confidence 등)는 추출 파이프라인 상태 정보일 뿐, 그림 내용의 과학적 타당성 근거가 아니야."""

_RECIPE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "objective": {"type": "string"},
        "materials": {"type": "array", "items": {"type": "string"}},
        "equipment": {"type": "array", "items": {"type": "string"}},
        "parameters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "notes": {"type": "string"},
                    "source_tag": {"type": "string", "enum": ["explicit", "inferred"]},
                },
                "required": ["name", "value"],
            },
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "critical_notes": {"type": "array", "items": {"type": "string"}},
        "expected_results": {"type": "string"},
        "safety_notes": {"type": "string"},
        "confidence": {"type": "number"},
        "missing_info": {"type": "array", "items": {"type": "string"}},
        "reproducibility_score": {"type": "number"},
        "score_rationale": {"type": "string"},
    },
    "required": ["title", "objective", "parameters", "steps"],
}

_DEEP_DIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "detailed_analysis": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "novelty_assessment": {"type": "string"},
        "comparison_to_prior_work": {"type": "string"},
        "suggested_improvements": {"type": "array", "items": {"type": "string"}},
        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
        "practical_applications": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["detailed_analysis", "strengths", "weaknesses"],
}

_DEEP_DIVE_INSTRUCTION = """이 논문에 대한 심층 분석을 해줘. 전문적이면서도 이해하기 쉽게,
선배 연구자가 후배에게 설명하듯이 써줘.

규칙:
- 논문 PDF(또는 논문 텍스트)가 최우선 근거야. 앞선 단계(시각·레시피·스크리닝·인용) 결과는
  탐색용 힌트일 뿐이니, 논문에서 직접 확인한 내용만 사실로 서술해.
- 강점·약점에는 근거가 된 논문 위치(섹션/그림/표)를 함께 적어.
- novelty_assessment와 comparison_to_prior_work는 논문이 스스로 제시한 비교 범위 안의
  평가임을 명시해 — 외부 문헌 검증은 하지 않았어.
- 논문에 없는 반례·실험·선행연구를 만들어내지 마.

출력 필드: detailed_analysis(기여도·방법론·결과 상세 분석, 여러 문단), strengths(강점 리스트),
weaknesses(약점 리스트), novelty_assessment(새로움 평가), comparison_to_prior_work(기존 연구 대비 비교),
suggested_improvements(개선 제안 리스트), follow_up_questions(후속 질문 리스트), practical_applications(실용적 응용 리스트)."""


def _stateless_digest(screening_result_text: str, citation_result_text: str) -> str:
    """스크리닝·인용 결과에서 심층 분석에 필요한 핵심 필드만 뽑아 digest 텍스트를 만든다.

    raw JSON 절단 주입(중간 절단으로 필드 유실 + 오류 전파) 대신 구조화 digest를 쓴다.
    파싱 실패 시 해당 결과는 기존 관례대로 앞부분 절단 텍스트로 폴백한다."""
    parts = []
    if screening_result_text:
        try:
            s = json.loads(_clean_llm_json(screening_result_text))
            if not isinstance(s, dict):
                raise TypeError("digest 입력이 dict가 아님")
            parts.append(
                "[스크리닝] "
                f"도메인={s.get('domain', '?')}, 관련성={s.get('relevance_score', '?')}, "
                f"방법론={s.get('methodology_type', '?')}, 실험여부={s.get('is_experimental', '?')}, "
                f"핵심주제={', '.join(map(str, s.get('key_topics') or [])) or '?'}\n"
                f"요약: {str(s.get('summary') or '')[:500]}"
            )
        except (json.JSONDecodeError, TypeError):
            parts.append(f"[스크리닝 결과]\n{screening_result_text[:1500]}")
    if citation_result_text:
        try:
            c = json.loads(_clean_llm_json(citation_result_text))
            if not isinstance(c, dict):
                raise TypeError("digest 입력이 dict가 아님")
            parts.append(
                "[인용 분석] "
                f"총 참고문헌={c.get('total_references', '?')}, 균형={c.get('citation_balance', '?')}, "
                f"핵심영향={', '.join(map(str, c.get('key_influences') or [])) or '?'}\n"
                f"종합: {str(c.get('summary') or '')[:500]}"
            )
        except (json.JSONDecodeError, TypeError):
            parts.append(f"[인용 분석 결과]\n{citation_result_text[:1500]}")
    return "\n\n".join(parts)


_VIZ_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "visualizations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "tool": {"type": "string", "enum": ["mermaid", "paperbanana"]},
                    "diagram_type": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["title", "tool", "description"],
            },
        }
    },
    "required": ["visualizations"],
}

_STAGE_SCHEMAS = {
    "visual": _VISUAL_SCHEMA,
    "recipe": _RECIPE_SCHEMA,
    "deep_dive": _DEEP_DIVE_SCHEMA,
    "visualization": _VIZ_PLAN_SCHEMA,
}


def _find_paper_pdf(paper_dir: Path) -> Optional[Path]:
    """실제 업로드된 PDF 파일을 찾는다.

    PDF 파일명은 원본 업로드명(고정 'paper.pdf' 아님)이라 glob으로 탐색한다.
    """
    try:
        pdfs = sorted(paper_dir.glob("*.pdf"))
    except OSError:
        return None
    return pdfs[0] if pdfs else None


_STAGE_OVERLAY_GETTERS = {
    "visual": "get_visual_prompt",
    "recipe": "get_recipe_prompt",
    "deep_dive": "get_deepdive_prompt",
}


def _build_persona_prompt(agent, stage: str | None = None) -> str:
    """스테이지별 페르소나: 말투(personality) + 해당 단계의 도메인 오버레이.

    agents/*.md의 # Visual/# Recipe/# Deep Dive 섹션을 스테이지에 맞춰 주입한다.
    stage가 None이거나 오버레이가 없는 스테이지(visualization 등)는 말투만 쓴다."""
    profile = getattr(agent, "profile", None)
    desc = (getattr(profile, "personality", "") if profile else getattr(agent, "description", "")) or ""
    getter_name = _STAGE_OVERLAY_GETTERS.get(stage or "")
    getter = getattr(agent, getter_name, None) if getter_name else None
    overlay = getter() if callable(getter) else ""
    return "\n\n".join(p.strip() for p in (desc, overlay) if p and p.strip())


# OpenAI 텍스트 체인(doc_text) 주입 상한. Task 0 스파이크 실측: 논문 전체 텍스트를
# 프롬프트에 그대로 실었을 때 관측된 입력 토큰 최대치는 80,882(gpt-5.6-luna 계열
# 기준). 문자:토큰 비율은 언어·인코딩에 따라 흔들릴 수 있어 실측치보다 넉넉한
# 150,000자를 상한으로 둔다 — 대부분의 논문은 절단 없이 통과시키면서, 극단적으로
# 긴 논문에서도 프롬프트가 무한정 커지지 않도록 안전판을 둔다(리뷰 Critical 수정).
_OPENAI_DOC_TEXT_CHAR_LIMIT = 150_000

# OpenAI 체인 첫 호출(visual)에 별도 첨부하는 그림 이미지 장수 상한(스펙 R1).
# OpenAI는 PDF 파트를 못 보므로(doc_text 텍스트 주입만) 그림은 이미지 파트로 직접
# 붙여야 "그림을 봤다"가 참이 된다. 무한정 붙이면 요청이 무거워지므로 상한을 둔다.
_OPENAI_VISUAL_IMAGE_LIMIT = 8

# figure_service.py의 단일 그림 이미지 mime 추정과 같은 표 — 그림 추출이 사실상
# PNG만 만들지만(figure_resolver.py) 과거 자산·수동 업로드 대비 나머지도 인식한다.
_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}


async def _load_openai_figure_parts(paper_id: int, paper_dir: Path) -> list[dict]:
    """OpenAI visual 첫 호출에 첨부할 그림 이미지 파트를 만든다(리뷰 Important I3).

    스펙 R1: "visual 스테이지는 추출된 그림 이미지 파트를 별도 첨부한다." OpenAI
    경로는 document 파트를 지원하지 않아(_translate_parts) PDF를 못 보므로,
    doc_text 텍스트 주입만으로는 프롬프트의 "PDF를 직접 보고"가 거짓이 된다 — 이
    함수가 그 간극을 메운다. 최대 _OPENAI_VISUAL_IMAGE_LIMIT장만 읽는다. 개별
    그림 파일이 없거나 읽기 실패하면 그 그림만 건너뛰고 경고 로그를 남긴다 —
    분석 전체를 막지 않는다.
    """
    rows = await fetch_all(
        """
        SELECT file_path FROM figures
        WHERE paper_id = ?
          AND COALESCE(extraction_status, 'resolved') != 'rejected'
          AND file_path IS NOT NULL AND file_path != ''
        ORDER BY id ASC
        LIMIT ?
        """,
        (paper_id, _OPENAI_VISUAL_IMAGE_LIMIT),
    )
    parts: list[dict] = []
    for row in rows:
        file_path = row.get("file_path")
        if not file_path:
            continue
        candidate = Path(file_path)
        resolved = candidate if candidate.is_absolute() else (paper_dir / candidate)
        try:
            image_bytes = resolved.read_bytes()
        except OSError as exc:
            logger.warning(
                "OpenAI visual figure image load failed (paper %s, %s): %s",
                paper_id, resolved, exc,
            )
            continue
        mime_type = _IMAGE_MIME_BY_SUFFIX.get(resolved.suffix.lower(), "image/png")
        parts.append({
            "type": "image",
            "data": base64.b64encode(image_bytes).decode("ascii"),
            "mime_type": mime_type,
        })
    return parts


def _doc_reference_phrase(provider: str) -> str:
    """체인 프롬프트가 가리키는 입력 소스 문구(리뷰 Important I3).

    Gemini 체인은 PDF 파일을 실제로 첨부하므로 "위 논문 PDF"가 사실이다. OpenAI
    체인은 PDF를 못 보고(document 파트 미지원) 로컬 추출 텍스트 + (visual 스테이지
    한정) 그림 이미지 파트만 받으므로, 그대로 "PDF"라고 쓰면 거짓 지시문이 된다 —
    각 호출부가 이 함수로 provider에 맞는 문구를 골라 쓴다.
    """
    if provider == "openai":
        return "위 논문 본문 텍스트(첫 단계에 첨부된 그림 이미지 포함)"
    return "위 논문 PDF"


async def _run_chain_stage(
    *,
    phase: str,
    prompt_chain: str,
    prompt_fallback: str,
    system_instruction: str,
    previous_interaction_id: Optional[str],
    pdf_uri: Optional[str],
    response_schema: dict,
    restart_context: str = "",
    provider: str = "gemini",
    doc_text: str = "",
    figure_parts: Optional[list[dict]] = None,
) -> dict:
    """체인/폴백 모드에 맞춰 call_interaction을 호출한다.

    - pdf_uri 있음(Gemini 체인 모드): store=True. 체인 첫 호출(previous_interaction_id
      None)만 PDF 문서를 input에 포함하고, 이후 스테이지는 지시문만 보내 서버 상태를
      신뢰한다. 단, 중간 스테이지 캐시 히트/스킵으로 previous_interaction_id가 유실된
      체인 재시작 케이스에는 restart_context(이전 스테이지 결과 텍스트)를 PDF와 함께
      프롬프트에 실어 서버 상태 단절로 잃은 이전 분석 컨텍스트를 복원한다. figure_parts는
      이 경로에서 쓰지 않는다(Gemini는 PDF에서 직접 그림을 본다).
    - doc_text 있음(OpenAI 체인 모드, 스펙 R1): store=True. OpenAI는 document 파트를
      지원하지 않아 PDF 업로드 대신 로컬 추출 텍스트를 체인 첫 호출에 1회 주입하고,
      이후 스테이지는 pdf_uri 체인과 동일하게 지시문만 보내 서버 상태를 신뢰한다.
      restart_context 복원 경로도 pdf_uri 체인과 동일하게 적용된다. 주입 라벨은 실제
      절단 여부를 그대로 알린다 — doc_text 길이가 _OPENAI_DOC_TEXT_CHAR_LIMIT 이상이면
      "절단" 라벨, 아니면 "전문" 라벨(호출측이 이미 그 상한으로 잘라 넘긴다). 체인 첫
      호출(previous_interaction_id None)에 figure_parts가 있으면 이미지 파트들을
      텍스트 파트 앞에 붙여 contents를 리스트로 조립한다(스펙 R1 — visual 스테이지가
      추출된 그림을 별도 첨부). 이미지가 없으면(빈 리스트/None) 기존처럼 문자열
      그대로 보낸다. 후속 스테이지(previous_interaction_id 있음)는 figure_parts를
      받아도 무시한다 — 서버가 이미 첫 호출에서 본 이미지를 기억한다.
    - 둘 다 없음(폴백): stateless(store=False). 기존 phase_inputs 텍스트를 프롬프트에
      삽입한다.

    pdf_uri와 doc_text는 상호 배타다(Gemini는 PDF 파트, OpenAI는 텍스트 주입만 쓴다).

    결과 텍스트가 JSON 파싱 불가이거나, 파싱은 되지만 필드 값이 반복 루프
    (degenerate repetition)에 오염됐으면 1회 재시도한다(재시도도 실패하면
    그대로 반환 — 기존 `_raw`/`_parse_error` 경로가 처리).
    """
    if pdf_uri and doc_text:
        raise ValueError("pdf_uri(Gemini 체인)와 doc_text(OpenAI 체인)는 동시 사용 불가")

    async def _invoke() -> dict:
        if pdf_uri or doc_text:
            if previous_interaction_id is None:
                chain_text = prompt_chain
                if restart_context:
                    chain_text = (
                        f"{prompt_chain}\n\n"
                        f"이전 분석 단계 결과(체인 재시작으로 복원):\n{restart_context}"
                    )
                if pdf_uri:
                    contents = [
                        {"type": "document", "uri": pdf_uri, "mime_type": "application/pdf"},
                        {"type": "text", "text": chain_text},
                    ]
                else:
                    if len(doc_text) >= _OPENAI_DOC_TEXT_CHAR_LIMIT:
                        doc_label = f"[논문 본문({_OPENAI_DOC_TEXT_CHAR_LIMIT:,}자 절단)]"
                    else:
                        doc_label = "[논문 전문]"
                    text_content = f"{doc_label}\n{doc_text}\n\n{chain_text}"
                    if figure_parts:
                        contents = [*figure_parts, {"type": "text", "text": text_content}]
                    else:
                        contents = text_content
            else:
                contents = prompt_chain
            choice = _stage_choice(phase, provider)
            return await call_interaction(
                contents,
                lane="pipeline",
                model=choice.model,
                system_instruction=system_instruction,
                thinking_level=choice.effort,
                previous_interaction_id=previous_interaction_id,
                response_schema=response_schema,
                store=True,
            )
        choice = _stage_choice(phase, provider)
        return await call_interaction(
            prompt_fallback,
            lane="pipeline",
            model=choice.model,
            system_instruction=system_instruction,
            thinking_level=choice.effort,
            response_schema=response_schema,
            store=False,
        )

    result = await _invoke()
    defect = _stage_result_defect(result.get("text") or "")
    if defect:
        logger.warning(
            "chain stage %s %s (tokens_out=%s); retrying once",
            phase, defect, result.get("tokens_out"),
        )
        retry = await _invoke()
        # 재시도 사용량은 attempt별로 비용을 계산해 합산한다(R7-3) — 토큰을
        # 합쳐 한 번에 계산하면 장문 임계값이 잘못 적용되거나(단가 구간 있는
        # 모델) 이후 tokens_in/out 합산과 겹쳐 비용이 이중 계산된다.
        retry["cost_usd_prior_attempts"] = calc_cost(
            result["model"], result.get("tokens_in") or 0, result.get("tokens_out") or 0,
        ) + calc_cost(
            retry["model"], retry.get("tokens_in") or 0, retry.get("tokens_out") or 0,
        )
        # 사용량 표시(tokens_in/out)는 실사용 총량이 맞으므로 토큰 합산은 유지한다.
        retry["tokens_in"] = (result.get("tokens_in") or 0) + (retry.get("tokens_in") or 0)
        retry["tokens_out"] = (result.get("tokens_out") or 0) + (retry.get("tokens_out") or 0)
        result = retry
    return result


async def _run_visual(
    paper_id: int,
    visual_input: str,
    folder_name: str,
    status: AnalysisStatus,
    *,
    system_instruction: str = "",
    previous_interaction_id: Optional[str] = None,
    pdf_uri: Optional[str] = None,
    doc_text: str = "",
    figure_parts: Optional[list[dict]] = None,
    provider: str = "gemini",
) -> dict:
    """Phase 3: Visual verification - analyze figures, assess quality.

    figure_parts는 OpenAI 체인 첫 호출(이 phase)에서만 쓰인다(스펙 R1) — Gemini는
    PDF에서 직접 그림을 보므로 무시된다. _run_chain_stage로 그대로 전달한다.
    """
    phase_status = PhaseStatus(
        phase=AnalysisPhase.VISUAL,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.VISUAL
    choice = _stage_choice("visual", provider)
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
            quality_summary = "이 논문에서는 그림과 표를 추출하지 못해 텍스트 분석만으로 진행했어요."
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
        cached = await _get_cached_phase_result(
            paper_id, "visual", partial_hash_source, provider=provider, model=choice.model, effort=choice.effort,
        )
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
                provider=provider,
                model=choice.model,
                effort=choice.effort,
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

    instruction = _VISUAL_INSTRUCTION

    prompt_chain = f"{instruction}\n\n{_doc_reference_phrase(provider)}를 직접 보고 시각 요소를 분석해줘.{figure_desc}"
    prompt_fallback = f"논문 관련 텍스트:\n{visual_input}\n{figure_desc}\n\n{instruction}"
    cache_key = prompt_fallback

    cached = await _get_cached_phase_result(
        paper_id, "visual", cache_key, provider=provider, model=choice.model, effort=choice.effort,
    )
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

    result = await _run_chain_stage(
        phase="visual",
        prompt_chain=prompt_chain,
        prompt_fallback=prompt_fallback,
        system_instruction=system_instruction,
        previous_interaction_id=previous_interaction_id,
        pdf_uri=pdf_uri,
        doc_text=doc_text,
        figure_parts=figure_parts,
        response_schema=_VISUAL_SCHEMA,
        provider=provider,
    )
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

    cost = _result_cost(result)

    await _insert_analysis_result(
        paper_id,
        "visual",
        result["text"],
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        cache_key,
        interaction_id=result.get("interaction_id"),
        provider=provider,
        model=choice.model,
        effort=choice.effort,
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
    previous_results: Optional[list[str]] = None,
    *,
    system_instruction: str = "",
    previous_interaction_id: Optional[str] = None,
    pdf_uri: Optional[str] = None,
    doc_text: str = "",
    provider: str = "gemini",
) -> dict:
    """Phase 3: Recipe extraction - extract structured experimental procedure."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.RECIPE,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.RECIPE
    choice = _stage_choice("recipe", provider)

    should_skip, skip_reason = _screening_gate_decision(screening_result_text, phase="recipe")
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
            elif domain in ("ee", "circuit", "electrical"):
                domain_hint = """
DOMAIN-SPECIFIC PARAMETERS (Electrical/Electronics) — extract ALL of these if mentioned:
technology_node (nm), supply_voltage (V), threshold_voltage (V), bias_current (uA/mA),
power_consumption (mW/uW), clock_frequency (Hz/MHz/GHz), gain (dB), bandwidth (Hz),
transistor_count, channel_length/width (nm/um), load_capacitance (fF/pF),
input_impedance (ohm), output_impedance (ohm), noise_figure (dB), SNR/SNDR (dB),
ENOB (bits), sampling_rate (S/s), slew_rate (V/us), phase_margin (deg),
figure_of_merit (FoM), die_area (mm2), efficiency (%)"""
            else:
                domain_hint = """
Look for ALL quantitative parameters: temperatures, pressures, durations, concentrations,
voltages, currents, frequencies, distances, speeds, sizes, ratios, percentages, etc."""
        except (json.JSONDecodeError, TypeError):
            pass

    instruction = f"""이 연구 논문에서 재현 가능한 실험 레시피를 추출해줘.

핵심 지시사항:
1. 재현에 필요한 정량 파라미터를 논문 전체(Methods뿐 아니라 Results·Discussion·그림 캡션·표·부록)에서 빠짐없이 찾아.
2. 각 파라미터마다 name, value, unit, notes(출처 섹션/문맥), source_tag를 포함해.
3. source_tag 규칙:
   - "explicit": 논문에 값이 직접 명시됨.
   - "inferred": 논문에 명시된 다른 값에서 계산·추론 가능 — notes에 근거와 계산을 적어.
4. 개수 목표는 없어. 논문에 실제로 있는 항목만 추출하고, 통상 기본값·상식·장비 기본 설정을 논문 값처럼 보충하지 마.
5. 재현에 필요한데 논문에 없는 항목은 parameters에 넣지 말고 missing_info에 기록해.
6. reproducibility_score는 explicit 핵심 파라미터의 충족도와 missing_info를 근거로 매기고, 그 근거를 score_rationale에 한 문장으로 적어.
{domain_hint}

출력 필드: title(레시피 제목, 한국어), objective(실험 목적), materials(재료 리스트, 규격 포함),
equipment(장비 리스트, 모델번호 포함), parameters(각 항목 name/value/unit/notes/source_tag),
steps(단계별 상세 설명, 온도·시간·속도 등 포함), critical_notes(재현 중요 참고사항),
expected_results(예상 결과), safety_notes(안전 주의사항), confidence(0.0~1.0),
missing_info(논문에 없어 재현에 걸림돌이 되는 항목), reproducibility_score(0.0~1.0), score_rationale(점수 근거)."""

    prompt_chain = f"{instruction}\n\n{_doc_reference_phrase(provider)}와 이전 분석을 바탕으로 실험 레시피를 추출해줘."
    prompt_fallback = f"논문 텍스트:\n{recipe_input}\n\n{instruction}"
    cache_key = prompt_fallback

    cached = await _get_cached_phase_result(
        paper_id, "recipe", cache_key, provider=provider, model=choice.model, effort=choice.effort,
    )
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

    result = await _run_chain_stage(
        phase="recipe",
        prompt_chain=prompt_chain,
        prompt_fallback=prompt_fallback,
        system_instruction=system_instruction,
        previous_interaction_id=previous_interaction_id,
        pdf_uri=pdf_uri,
        doc_text=doc_text,
        response_schema=_RECIPE_SCHEMA,
        restart_context=_build_chain_restart_context(previous_results),
        provider=provider,
    )

    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 3 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = _result_cost(result)

    await _insert_analysis_result(
        paper_id,
        "recipe",
        result["text"],
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        cache_key,
        interaction_id=result.get("interaction_id"),
        provider=provider,
        model=choice.model,
        effort=choice.effort,
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
    citation_result_text: Optional[str] = None,
    *,
    system_instruction: str = "",
    previous_interaction_id: Optional[str] = None,
    pdf_uri: Optional[str] = None,
    doc_text: str = "",
    provider: str = "gemini",
) -> dict:
    """Phase 4: Deep dive - comprehensive analysis over the stateful chain."""
    phase_status = PhaseStatus(
        phase=AnalysisPhase.DEEP_DIVE,
        status="running",
        started_at=_utcnow_iso(),
    )
    status.phases.append(phase_status)
    status.current_phase = AnalysisPhase.DEEP_DIVE
    choice = _stage_choice("deep_dive", provider)

    should_skip, skip_reason = _screening_gate_decision(screening_result_text, phase="deep_dive")
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

    instruction = _DEEP_DIVE_INSTRUCTION

    # 스크리닝(r1)·인용(r_cit)은 stateless라 서버측 체인 상태에 없다. 체인 모드에서도
    # 프롬프트가 약속하는 "스크리닝·인용" 컨텍스트를 제공하되, raw JSON 절단 대신
    # 핵심 필드 digest로 주입한다.
    stateless_context = _stateless_digest(screening_result_text or "", citation_result_text or "")

    prompt_chain = (
        f"{instruction}\n\n{_doc_reference_phrase(provider)}와 앞선 체인 단계(시각·레시피) 결과, 그리고 아래 "
        "스크리닝·인용 분석 digest를 바탕으로 포괄적인 심층 분석을 제공해줘."
    )
    if stateless_context:
        prompt_chain += f"\n\n--- 스크리닝·인용 분석 digest ---\n{stateless_context}"
    prompt_fallback = (
        f"논문 텍스트:\n{deep_dive_input}\n\n"
        f"이전 분석 단계의 결과:\n{prev_context[:4000]}\n\n"
        f"{instruction}\n\n위 정보를 바탕으로 포괄적인 심층 분석을 제공해줘."
    )
    cache_key = prompt_fallback

    # 체인 재시작 복원용 컨텍스트는 체인 스테이지(시각·레시피)만 담는다. 스크리닝·인용은
    # 위 prompt_chain에 이미 삽입돼 있으므로 중복 방지를 위해 제외한다.
    chain_stage_results = [
        r
        for r in (previous_results or [])
        if r not in (screening_result_text, citation_result_text)
    ]

    cached = await _get_cached_phase_result(
        paper_id, "deep_dive", cache_key, provider=provider, model=choice.model, effort=choice.effort,
    )
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

    result = await _run_chain_stage(
        phase="deep_dive",
        prompt_chain=prompt_chain,
        prompt_fallback=prompt_fallback,
        system_instruction=system_instruction,
        previous_interaction_id=previous_interaction_id,
        pdf_uri=pdf_uri,
        doc_text=doc_text,
        response_schema=_DEEP_DIVE_SCHEMA,
        restart_context=_build_chain_restart_context(chain_stage_results),
        provider=provider,
    )

    cleaned_text = _clean_llm_json(result["text"])

    # Validate JSON before storing
    try:
        json.loads(cleaned_text)
        result["text"] = cleaned_text
    except json.JSONDecodeError as exc:
        logger.warning("Phase 4 JSON validation failed: %s", exc)
        result["text"] = json.dumps({"_raw": cleaned_text, "_parse_error": str(exc)})

    cost = _result_cost(result)

    await _insert_analysis_result(
        paper_id,
        "deep_dive",
        result["text"],
        result["model"],
        result["tokens_in"],
        result["tokens_out"],
        cost,
        cache_key,
        interaction_id=result.get("interaction_id"),
        provider=provider,
        model=choice.model,
        effort=choice.effort,
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
    *,
    system_instruction: str = "",
    previous_interaction_id: Optional[str] = None,
    pdf_uri: Optional[str] = None,
    doc_text: str = "",
    provider: str = "gemini",
) -> list[dict]:
    """
    Decide which visualizations (6-10) best help understand the paper's
    methodology. Final stage of the stateful chain. Returns a plan as a list of dicts.
    """
    phase_status = PhaseStatus(
        phase=AnalysisPhase.DEEP_DIVE,  # piggyback on deep_dive phase for status
        status="running",
        started_at=_utcnow_iso(),
    )
    # Don't append a new phase — we update the existing deep_dive phase's progress
    choice = _stage_choice("visualization", provider)  # role: viz_planning

    prev_context = "\n---\n".join(previous_results[:4])

    instruction = """너는 연구 논문 분석 시스템의 시각화 기획자야.

반드시 6~10개의 시각화 항목을 반환해. 가장 임팩트 있는 것을 선택해.
논문의 핵심 개념과 작동 원리를 시각적으로 설명하는 일러스트(paperbanana 개념도)를
충분히 포함해 — 방법론 다이어그램만으로 채우지 마.

각 시각화를 두 가지 도구 중 하나로 분류해:
- "mermaid": 구조적/논리적 다이어그램 (플로우차트, 시퀀스, 마인드맵)
- "paperbanana": 물리적/시각적 일러스트 (장비 셋업, 광학 레이아웃, 세포/분자 도식, 개념도)

각 항목 필드: title(짧은 제목, 한국어), tool(mermaid|paperbanana),
diagram_type(flowchart|sequence|mindmap),
description(왜 필요한지·무엇을 보여주는지 2-3문장, 한국어),
category(experimental_protocol|algorithm_flow|signal_flow|system_architecture|component_relationships|timeline|comparison|equipment_appearance|optical_table_layout|cell_molecule_schematic|physical_setup|conceptual_illustration).

실험 방법을 최대한 이해할 수 있는 시각화를 우선시해.
고려할 것: 프로세스 흐름, 파라미터 관계, 장비 구성, 신호 경로, 비교표."""

    prompt_chain = f"{instruction}\n\n{_doc_reference_phrase(provider)}와 이전 분석 단계 결과를 바탕으로 시각화 계획을 세워줘."
    prompt_fallback = (
        f"{instruction}\n\n--- 분석 결과 (Phase 1-4) ---\n{prev_context[:9000]}\n\n"
        f"--- 관련 텍스트 요약 ---\n{visualization_input}"
    )
    cache_key = prompt_fallback

    cached = await _get_cached_phase_result(
        paper_id, "viz_plan", cache_key, provider=provider, model=choice.model, effort=choice.effort,
    )
    if cached is not None:
        try:
            return json.loads(cached["text"]).get("visualizations", [])
        except (json.JSONDecodeError, TypeError, AttributeError):
            return []

    result = await _run_chain_stage(
        phase="visualization",
        prompt_chain=prompt_chain,
        prompt_fallback=prompt_fallback,
        system_instruction=system_instruction,
        previous_interaction_id=previous_interaction_id,
        pdf_uri=pdf_uri,
        doc_text=doc_text,
        response_schema=_VIZ_PLAN_SCHEMA,
        restart_context=_build_chain_restart_context(previous_results),
        provider=provider,
    )
    cost = _result_cost(result)

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
        cache_key,
        interaction_id=result.get("interaction_id"),
        provider=provider,
        model=choice.model,
        effort=choice.effort,
    )

    return items


# Diagram types the render pipeline (prompt rules, sanitize, repair) is built
# for. LLMs sometimes plan/emit timeline, gantt, journey, etc. despite the
# planner prompt no longer listing them — coerce anything outside this set to
# flowchart so generation stays on a structurally supported type.
_MERMAID_RENDERABLE_TYPES = {"flowchart", "sequence", "mindmap"}


async def _generate_single_mermaid(
    paper_id: int,
    viz_item: dict,
    visualization_input: str,
    previous_results: list[str],
    *,
    provider: str = "gemini",
) -> str:
    """Generate Mermaid code for a single visualization item using Gemini Pro 3."""
    title = viz_item.get("title", "Diagram")
    diagram_type = viz_item.get("diagram_type", "flowchart")
    if diagram_type not in _MERMAID_RENDERABLE_TYPES:
        diagram_type = "flowchart"
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

    choice = resolve_model("mermaid", provider)
    result = await call_interaction(
        prompt, lane="pipeline", model=choice.model, thinking_level=choice.effort, store=False,
    )

    return _sanitize_mermaid_code(result["text"])


async def _generate_single_paperbanana(
    paper_id: int,
    viz_item: dict,
    visualization_input: str,
    folder_name: str,
    recipe_result: str,
    deep_dive_result: str,
    *,
    llm_provider: str = "gemini",
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
        llm_provider=llm_provider,
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
    paper_id: int, items: list[dict], cache_input: str, done: bool, *, provider: str = "gemini",
) -> None:
    """항목이 하나 끝날 때마다 visualization 행을 갱신한다 (중간 사망 시 유실 방지).

    UPDATE 대상 SELECT는 input_hash까지 걸어 같은 실행(run)의 행만 찾는다. paper_id+phase
    최신 1건만 보면, 재분석(다른 input_hash로 재실행)이 이전 실행의 완료된 행을 이어달리기로
    착각하고 덮어써버린다 — 새 실행은 반드시 새 행을 INSERT해야 한다.

    model_used는 provider에 맞는 레지스트리 모델명이어야 한다 — 이 메타데이터는
    plan(viz_planning role)이 실제로 어떤 모델로 계획됐는지를 남기는 것이지, 개별
    항목(mermaid/paperbanana)의 모델이 아니다.
    """
    input_hash = compute_input_hash(cache_input)
    total_cost_usd = sum(it.get("cost_usd") or 0 for it in items)
    model_used = resolve_model("viz_planning", provider).model
    payload = json.dumps(
        {
            "items": sorted(items, key=lambda x: x.get("id", 0)),
            "total_count": len(items),
            "model_used": model_used,
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
            paper_id, "visualization", payload, model_used, 0, 0, total_cost_usd, cache_input,
        )


async def _run_visualizations(
    paper_id: int,
    visualization_input: str,
    folder_name: str,
    previous_results: list[str],
    recipe_result: str,
    deep_dive_result: str,
    status: AnalysisStatus,
    *,
    system_instruction: str = "",
    previous_interaction_id: Optional[str] = None,
    pdf_uri: Optional[str] = None,
    doc_text: str = "",
    provider: str = "gemini",
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

    # Step 1: Plan (final stage of the stateful chain)
    viz_plan = await _plan_visualizations(
        paper_id,
        visualization_input,
        previous_results,
        status,
        system_instruction=system_instruction,
        previous_interaction_id=previous_interaction_id,
        pdf_uri=pdf_uri,
        doc_text=doc_text,
        provider=provider,
    )

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
                    provider=provider,
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
                    llm_provider=provider,
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
        await _store_visualization_progress(
            paper_id, accumulated, visualization_cache_input, done=False, provider=provider,
        )

    # Run paperbanana generations sequentially to avoid API rate limits
    paperbanana_results = []
    for idx, (i, item) in enumerate(paperbanana_items):
        result = await generate_one(i, item)
        paperbanana_results.append(result)
        accumulated.append(result)
        await _store_visualization_progress(
            paper_id, accumulated, visualization_cache_input, done=False, provider=provider,
        )
        # Small delay between PaperBanana calls to avoid rate limiting
        if idx < len(paperbanana_items) - 1:
            await asyncio.sleep(2.0)

    # Run other tool types in parallel
    other_tasks = [generate_one(i, item) for i, item in other_items]
    other_results = await asyncio.gather(*other_tasks, return_exceptions=False) if other_tasks else []
    if other_results:
        accumulated.extend(other_results)
        await _store_visualization_progress(
            paper_id, accumulated, visualization_cache_input, done=False, provider=provider,
        )

    # Combine and sort by original index
    all_results = list(mermaid_results) + paperbanana_results + list(other_results)
    generated_items = sorted(all_results, key=lambda x: x.get("id", 0))

    # Step 3: Store all visualization results in DB (final, complete=True)
    await _store_visualization_progress(
        paper_id, generated_items, visualization_cache_input, done=True, provider=provider,
    )

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

        # 이 실행 전체에 걸쳐 provider를 한 번만 결정한다 — 분석 도중 설정 화면에서
        # provider를 바꿔도 이미 진행 중인 실행은 처음 값으로 일관되게 끝까지 간다.
        provider = await active_provider()

        folder_name = paper["folder_name"]
        paper_dir = get_paper_dir(folder_name)

        document_context = await run_pipeline_blocking(load_or_build_document_context, paper_dir)
        phase_inputs = document_context.get("phase_inputs", {})
        sections = document_context.get("sections", {})
        # 스크리닝 전용 5,000자 절단본 — screening 호출에만 쓴다.
        paper_text = str(phase_inputs.get("screening", ""))
        # 비절단 원문 — OpenAI 체인의 doc_text 주입은 이 값을 쓴다(리뷰 Critical 수정:
        # paper_text의 5,000자 절단본을 그대로 재사용하면 recipe(기존 폴백 14,000자) 등
        # 후속 스테이지가 구조적으로 열화된다). document_context가 이미 메모리에 올려둔
        # 값을 노출한 것뿐이라 새 파일 IO는 없다.
        full_text = str(document_context.get("full_text", ""))
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
            paper_text,
            status,
            provider=provider,
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # --- 본 분석 체인 준비 (스크리닝 결과 기반 도메인/페르소나 자동 선택) ---
        import json as _json
        from api.analysis_context import build_chain_system_instruction, build_reader_profile_block
        from services.llm.interactions_client import upload_pdf_for_paper
        from services.agents import get_agent_for_domain
        from api.settings import get_raw_settings, parse_research_areas

        try:
            screening_data = _json.loads(_clean_llm_json(r1.get("text") or "{}"))
        except (_json.JSONDecodeError, TypeError):
            screening_data = {}
        domain = screening_data.get("domain") or paper.get("domain") or "general"
        agent = get_agent_for_domain(domain)
        await execute_update(
            "UPDATE papers SET domain = ?, agent_used = ? WHERE id = ?",
            (domain, agent.name, paper_id),
        )

        try:
            settings_raw = await get_raw_settings()
        except Exception as exc:
            logger.warning("Settings load failed for paper %s, using defaults: %s", paper_id, exc)
            settings_raw = {}
        try:
            focus = _json.loads(paper["analysis_focus"]) if paper.get("analysis_focus") else None
        except (_json.JSONDecodeError, TypeError):
            focus = None
        level_key = paper.get("explanation_level") or settings_raw.get("default_explanation_level", "masters")
        # 오버라이드 없이 프로필 기본값으로 분석한 논문도, 실제 적용된 설명 수준을
        # 논문에 남겨 라이브러리에서 진실되게 표시되도록 한다.
        if not paper.get("explanation_level"):
            await execute_update(
                "UPDATE papers SET explanation_level = ? WHERE id = ?",
                (level_key, paper_id),
            )
        _areas = parse_research_areas(settings_raw.get("research_areas") or "[]")

        reader_profile = build_reader_profile_block(
            _areas,
            settings_raw.get("field_expertise") or "major",
            settings_raw.get("reading_experience") or "regular",
            settings_raw.get("research_role") or "grad_student",
            level_key=level_key,
        )

        def _stage_system_instruction(stage: Optional[str]) -> str:
            return build_chain_system_instruction(
                persona_prompt=_build_persona_prompt(agent, stage),
                research_context=settings_raw.get("research_context", ""),
                focus=focus,
                level_key=level_key,
                reader_profile=reader_profile,
            )

        visual_system_instruction = _stage_system_instruction("visual")
        recipe_system_instruction = _stage_system_instruction("recipe")
        deep_dive_system_instruction = _stage_system_instruction("deep_dive")
        viz_system_instruction = _stage_system_instruction(None)

        # PDF 직접 입력용 업로드. 실패/부재 시 pdf_uri=None → 각 스테이지는 텍스트 폴백 경로.
        #
        # gemini에서만 업로드한다. openai_client._translate_parts는 document 파트를
        # 지원하지 않는다(스펙 R1 — OpenAI 체인은 파일이 아니라 텍스트 주입을 쓴다).
        # 게이트 없이 업로드하면 pdf_uri가 채워진 채로 _run_chain_stage가 openai로
        # 라우팅되어 document 파트를 만들고, openai_client가 그 자리에서 ValueError로
        # 터진다 — provider=openai + GEMINI_API_KEY 보유(양쪽 키)인 흔한 조합에서
        # 첫 체인 스테이지가 매번 100% 실패했다(리뷰 Critical 1). openai는 아래 elif
        # 분기에서 doc_text로 텍스트 체인을 탄다(Task 10, 스펙 R1).
        chain_prev_id: Optional[str] = None
        pdf_uri: Optional[str] = None
        doc_text: str = ""
        figure_parts: list[dict] = []
        if provider == "gemini":
            pdf_file = _find_paper_pdf(paper_dir)
            if pdf_file is not None:
                try:
                    pdf_uri = await upload_pdf_for_paper(paper_id, str(pdf_file))
                except Exception as exc:
                    logger.warning(
                        "PDF upload failed for paper %s, falling back to text context: %s", paper_id, exc
                    )
            else:
                logger.warning(
                    "No PDF found in %s for paper %s; using text-context fallback.", paper_dir, paper_id
                )
        elif provider == "openai":
            # 비절단 원문(full_text)을 체인 첫 호출에 1회 주입한다 — screening용
            # paper_text(5,000자 절단본)가 아니다. _OPENAI_DOC_TEXT_CHAR_LIMIT 상한만
            # 적용하고, 그 안이면 절단 없이 그대로 넣는다.
            doc_text = full_text[:_OPENAI_DOC_TEXT_CHAR_LIMIT]
            # PDF를 못 보는 대신(스펙 R1) 추출된 그림을 이미지 파트로 최대 8장 직접
            # 첨부한다 — visual 스테이지(체인 첫 호출)에만 실린다(리뷰 Important I3).
            figure_parts = await _load_openai_figure_parts(paper_id, paper_dir)

        # Phase 2: Citation Analysis (after screening, before visual)
        # TODO(parser-hybrid): visual 단계가 gemini로 승격되면 sections/references는 gemini 텍스트라
        # 저자명·grant번호가 산발 변조될 수 있다. 축자 검증용 ODL 원문은
        # services.odl_parser.get_odl_reference_text(paper_dir)로 얻어(승격 시 존재) 참조 파싱
        # 교차검증에 쓸 수 있다. 현재는 analyze_citations 로컬 파서 의미가 바뀌고 오프라인 검증이
        # 불가해 배선하지 않는다 — 인용 정확도 개선 작업 시 여기서 물린다.
        paper_authors = paper.get("authors", "") or ""
        r_cit = await _run_citation(
            paper_id,
            sections=sections,
            citation_body=str(phase_inputs.get("citation_body", "")),
            citation_references=str(phase_inputs.get("citation_references", "")),
            paper_authors=paper_authors,
            status=status,
            provider=provider,
        )

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        # Phase 3: Visual Verification (첫 체인 호출 — PDF 직접 입력)
        r2 = await _run_visual(
            paper_id,
            str(phase_inputs.get("visual", "")),
            folder_name,
            status,
            system_instruction=visual_system_instruction,
            previous_interaction_id=chain_prev_id,
            pdf_uri=pdf_uri,
            doc_text=doc_text,
            figure_parts=figure_parts,
            provider=provider,
        )
        if pdf_uri or doc_text:
            chain_prev_id = r2.get("interaction_id")

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

        # Phase 4: Recipe Extraction (체인 2번째 스테이지)
        r3 = await _run_recipe(
            paper_id,
            str(phase_inputs.get("recipe", "")),
            status,
            screening_result_text=r1.get("text", ""),
            previous_results=previous,
            system_instruction=recipe_system_instruction,
            previous_interaction_id=chain_prev_id,
            pdf_uri=pdf_uri,
            doc_text=doc_text,
            provider=provider,
        )
        if pdf_uri or doc_text:
            chain_prev_id = r3.get("interaction_id")

        # Check for cancellation
        if cancel_event.is_set():
            status.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return

        if r3.get("text") and not _is_error_result(r3["text"]):
            previous.append(r3["text"])

        # Phase 4: Deep Dive (체인 3번째 스테이지)
        r4 = await _run_deep_dive(
            paper_id,
            str(phase_inputs.get("deep_dive", "")),
            previous,
            status,
            screening_result_text=r1.get("text", ""),
            citation_result_text=r_cit.get("text", ""),
            system_instruction=deep_dive_system_instruction,
            previous_interaction_id=chain_prev_id,
            pdf_uri=pdf_uri,
            doc_text=doc_text,
            provider=provider,
        )
        if pdf_uri or doc_text:
            chain_prev_id = r4.get("interaction_id")

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
                    system_instruction=viz_system_instruction,
                    previous_interaction_id=chain_prev_id,
                    pdf_uri=pdf_uri,
                    doc_text=doc_text,
                    provider=provider,
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

def _subprocess_mode() -> bool:
    """실런타임(Electron/서버)에서만 켜지는 디태치 워커 모드 플래그. 테스트/직접 실행 기본 off."""
    return os.environ.get("SASOO_ANALYSIS_SUBPROCESS", "") == "1"


def _overlay_run_status(base: dict, run: Optional[dict]) -> dict:
    """analysis_runs 라이브 값을 기존 status builder 결과에 overlay. queued→running 매핑."""
    if not run:
        return base
    st = run.get("status")
    if st in ("queued", "running"):
        merged = dict(base)
        merged["overall_status"] = "running"          # 프론트 isRunning union + 폴링 지속
        # raw phase 문자열은 AnalysisPhase enum으로 클램프(미지의 값이면 None 유지 — 응답 검증 500 방지)
        phase_raw = run.get("current_phase")
        try:
            phase = AnalysisPhase(phase_raw) if phase_raw else None
        except ValueError:
            phase = None
        if phase is not None:
            merged["current_phase"] = phase
        pct = run.get("progress_pct")
        if pct is not None and pct > merged.get("progress_pct", 0.0):
            merged["progress_pct"] = pct
        return merged
    return base


@router.post("/{paper_id}/run", status_code=202)
async def run_analysis(paper_id: int, background_tasks: BackgroundTasks):
    """
    Start the 4-phase analysis pipeline for a paper.
    Runs in background. Poll /status for progress.
    """
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found.")

    # provider-aware 키 사전 점검: 분석 파이프라인 전체가 필요로 하는 키가
    # 없으면 백그라운드 태스크를 큐에 올리기 전에 즉시 400으로 거절한다 —
    # 큐에 올린 뒤 매 단계 LLM 호출에서 산발적으로 실패하는 것보다 낫다.
    provider = await active_provider()
    key_env = key_env_for(provider)
    if not os.getenv(key_env):
        provider_label = "OpenAI" if provider == "openai" else "Gemini"
        raise HTTPException(
            status_code=400,
            detail=f"논문 분석에 {provider_label} API 키가 필요해요. 설정에서 키를 등록해 주세요.",
        )

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

    if _subprocess_mode():
        # I3/결함2 빠른 경로: 분석이 디태치 워커로 옮겨간 뒤엔 위 인메모리 _running_analyses
        # 가드가 항상 비어 있어 무조건 통과한다 — DB(analysis_runs) 스냅샷으로 빠르게
        # 막는다. 단, 이 체크와 아래 upsert_queued 사이에 budget 조회 등 DB I/O await가
        # 여럿 끼어 있어 동시 이중 /run이 둘 다 이 스냅샷을 통과할 수 있다(TOCTOU) — 진짜
        # 방어선은 upsert_queued의 DB 레벨 원자 가드(아래)이고, 이 블록은 그 전에 빠르게
        # 실패시키는 최적화일 뿐 중복 코드가 아니다.
        from models.database import get_db
        from models.analysis_runs import get_run
        existing_run = await get_run(await get_db(), paper_id)
        if existing_run and existing_run["status"] in ("queued", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"Analysis for paper {paper_id} is already running.",
            )

    # Check budget before starting — 결함2: read_budget_state()가 단일 소스(/run과 리컨실러가
    # 공유). 월 경계 계산·cost_rows 쿼리·phase 필터를 여기서 다시 복제하지 않는다.
    from services.analysis_supervisor import read_budget_state
    current_spending, monthly_limit = await read_budget_state()

    if current_spending >= monthly_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget limit exceeded (${current_spending:.2f} / ${monthly_limit:.2f}). "
                   f"Increase your budget in Settings to continue.",
        )

    # Launch analysis: subprocess mode(실런타임)면 디태치 워커, 아니면 기존 in-process 경로 유지
    if _subprocess_mode():
        from models.database import get_db
        from models.analysis_runs import upsert_queued, utcnow_iso
        from services.analysis_supervisor import reconcile_once, read_max_concurrent
        conn = await get_db()
        # I1: 이미 completed인 논문을 재분석할 때 papers.status를 안 건드리고 claim+spawn하면,
        # 워커가 _run_full_analysis의 첫 UPDATE papers SET status='analyzing'에 도달하기 전에
        # 죽어도 papers는 여전히 completed로 남아 reconcile_stale ①이 조용히 완료로 확정한다.
        # upsert_queued 직전에 세워 그 창을 없앤다.
        await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("analyzing", paper_id))
        # 결함2: 위 빠른 경로 가드를 동시 요청이 함께 통과했더라도, upsert_queued의 DO UPDATE는
        # WHERE status NOT IN ('queued','running') 원자 가드를 걸고 있어 이미 진행 중인 run
        # 위에 리셋이 덮어써지지 않는다 — False면 진짜로 이미 진행 중이란 뜻이므로 409.
        queued_ok = await upsert_queued(conn, paper_id, utcnow_iso())
        if not queued_ok:
            raise HTTPException(
                status_code=409,
                detail=f"Analysis for paper {paper_id} is already running.",
            )
        # 즉시 드레인 시도(cap 내면 이번 요청이 스폰, 초과면 queued로 남아 리컨실러가 픽업)
        await reconcile_once(conn, cap=await read_max_concurrent())
    else:
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
    # subprocess mode: DB flag를 세우면 워커 사이드카가 phase 경계에서 취소를 존중한다
    if _subprocess_mode():
        try:
            from models.database import get_db
            from models.analysis_runs import request_cancel, get_run, cancel_queued_now
            conn = await get_db()
            # C1: cap 초과로 queued에 머문 run은 request_cancel(플래그만 세움)로는 소비되지 않아
            # 영구 좀비가 된다 — 아직 워커가 안 떴다면 원자적으로 즉시 cancelled 확정한다.
            rowcount = await cancel_queued_now(conn, paper_id, _utcnow_iso())
            if rowcount > 0:
                await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
                return {"paper_id": paper_id, "status": "cancelled"}
            run = await get_run(conn, paper_id)
            if run and run.get("status") in ("queued", "running"):
                await request_cancel(conn, paper_id)
                return {"paper_id": paper_id, "status": "cancelling"}
        except Exception as exc:  # noqa: BLE001 — 마이그레이션 전 DB 등: 레거시 인메모리 경로로 폴스루
            logger.warning("cancel: analysis_runs 접근 실패 — 레거시 취소 경로로 폴스루: %s", exc)

    # in-process(레거시/테스트) 경로 — 기존 동작 보존
    if paper_id in _cancel_events:
        _cancel_events[paper_id].set()
        return {"paper_id": paper_id, "status": "cancelling"}
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

    # Task 11(스펙 §D): stale_model 배지용 현재 provider. 조회 실패해도(설정
    # DB 미초기화 등) 상태 응답 자체는 죽으면 안 되므로 관대하게 폴백한다 —
    # provider가 None이면 아래 루프에서 배지 계산을 그냥 건너뛴다. 완료된 phase가
    # 하나도 없으면(배지를 매길 대상 자체가 없음) 애초에 호출하지 않는다 — /status는
    # 분석 진행 중 2초 간격으로 폴리되므로(리뷰 Important I2) 불필요한 settings
    # 조회(_get_all_settings, fetch_one 20회+commit)를 아낀다.
    stale_provider: Optional[str] = None
    if completed_phases:
        try:
            stale_provider = await active_provider()
        except Exception:
            logger.debug("stale_model 조회용 provider 확인 실패 — 배지 없이 진행", exc_info=True)

    for phase_name in phase_order:
        r = latest_results.get(phase_name)
        if r:
            cost = r.get("cost_usd") or 0.0
            tin = r.get("tokens_in") or 0
            tout = r.get("tokens_out") or 0
            stale_model: Optional[str] = None
            # 스크리닝 게이트로 스킵된 phase("system")는 provider/model/effort 없이
            # 저장돼(_store_skipped_phase_result) config_hash가 고정 상수 해시라
            # 어떤 현재 설정과도 절대 일치하지 않는다 — 가드가 없으면 provider가
            # 안 바뀌어도, 심지어 같은 스킵 결정으로 재분석해도 매번 "system로
            # 분석됨" 배지가 뜬다(리뷰 Important). 스킵은 "다른 모델로 분석됨"이
            # 아니므로 애초에 stale 판정 대상에서 제외한다.
            if stale_provider and r.get("model_used") != "system":
                try:
                    choice = resolve_model(phase_name, stale_provider)
                    current_hash = _config_hash(stale_provider, choice.model, choice.effort)
                    # latest_row=r: get_latest_completed_phase_rows가 이미 SELECT *로
                    # 가져온 이 phase의 최신 행을 그대로 넘긴다 — _lookup_phase_result_
                    # with_staleness가 같은 행을 또 fetch_one 2회로 재조회하지 않게
                    # 한다(리뷰 Important I2, /status 2초 폴링 부하).
                    staleness = await _lookup_phase_result_with_staleness(
                        paper_id, phase_name, current_hash, choice.model, latest_row=r,
                    )
                    if staleness:
                        stale_model = staleness.get("stale_model")
                except Exception:
                    logger.debug(
                        "phase %s stale_model 조회 실패 — 배지 없이 진행", phase_name, exc_info=True,
                    )
            phases.append(PhaseStatus(
                phase=AnalysisPhase(phase_name),
                status="completed",
                model_used=r.get("model_used"),
                tokens_in=tin,
                tokens_out=tout,
                cost_usd=cost,
                completed_at=r.get("created_at"),
                stale_model=stale_model,
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

    base = {"overall_status": paper["status"], "progress_pct": progress, "current_phase": None}
    if _subprocess_mode():
        try:
            from models.database import get_db
            from models.analysis_runs import get_run
            run = await get_run(await get_db(), paper_id)
            base = _overlay_run_status(base, run)
        except Exception:
            pass

    return AnalysisStatus(
        paper_id=paper_id,
        overall_status=base["overall_status"],
        phases=phases,
        progress_pct=base["progress_pct"],
        current_phase=base["current_phase"],
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

    provider = await active_provider()
    choice = resolve_model("mermaid", provider)
    result = await call_interaction(
        prompt, lane="chat", model=choice.model, thinking_level=choice.effort, store=False,
    )

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

    provider = await active_provider()
    choice = resolve_model("mermaid", provider)
    result = await call_interaction(
        prompt, lane="chat", model=choice.model, thinking_level=choice.effort, store=False,
    )
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

    provider = await active_provider()
    code = await _generate_single_mermaid(
        paper_id, stored_item, visualization_input, previous_results, provider=provider,
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

    # 등록된 레지스트리 role이 없는 일회성 생성이라 "chat" role을 재사용한다 —
    # lane도 "chat"이고 effort 특성(gemini=None, openai=low)이 그대로 맞는다.
    provider = await active_provider()
    choice = resolve_model("chat", provider)
    result = await call_interaction(
        prompt, lane="chat", model=choice.model, thinking_level=choice.effort, store=False,
    )
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

    # 5. 히스토리를 요청 텍스트로 조립 (stateless, store=False).
    #    Interactions는 단일 input 텍스트를 받으므로 최근 대화를 전사(transcript)로 붙인다.
    #    TODO(stateful): 후속 개선으로 paper 체인의 마지막 interaction_id를
    #    previous_interaction_id로 이어 서버 상태를 재사용하는 stateful 모드가 가능하다.
    #    다만 프론트가 매 요청 history 전체를 보내는 현재 계약을 바꿔야 하므로 이번 범위 밖이다.
    transcript_parts: list[str] = []
    for msg in history[-20:]:  # limit history to last 20 messages
        speaker = "사용자" if msg.get("role") == "user" else "사수"
        transcript_parts.append(f"{speaker}: {msg.get('content', '')}")
    transcript_parts.append(f"사용자: {message}")
    chat_input = "\n".join(transcript_parts)

    # 5b. provider는 이 요청 안에서 한 번만 결정한다 — 스트림 재시도 도중 설정이
    #     바뀌어도 같은 요청 안에서는 일관된 모델을 쓴다.
    provider = await active_provider()
    chat_choice = resolve_model("chat", provider)

    # 6. Stream via SSE — stream_interaction(lane="chat")이 전용 풀에서 브릿지를 담당한다.
    #
    # 파이프라인과 같은 쿼터를 때리는 순간이 곧 채팅이 실패하기 쉬운 순간이라,
    # 분석 경로처럼 재시도한다. 단 토큰이 이미 나간 뒤의 실패는 답변을 되감을 수
    # 없으므로 terminal이다. 클라이언트가 끊으면 즉시 소비를 멈춘다.
    async def event_generator():
        last_error: Exception | None = None
        streamed_any = False

        for attempt in range(_CHAT_MAX_ATTEMPTS):
            try:
                async for ev in stream_interaction(
                    chat_input,
                    lane="chat",
                    model=chat_choice.model,
                    thinking_level=chat_choice.effort,
                    system_instruction=system_prompt,
                    store=False,
                ):
                    if await request.is_disconnected():
                        logger.info(
                            "Chat client disconnected for paper %s; abandoning stream", paper_id
                        )
                        return
                    if ev["type"] == "token":
                        streamed_any = True
                        yield f"data: {json.dumps({'type': 'token', 'content': ev['text']}, ensure_ascii=False)}\n\n"
                    elif ev["type"] == "done":
                        cost = calc_cost(chat_choice.model, ev["tokens_in"], ev["tokens_out"])
                        yield f"data: {json.dumps({'type': 'done', 'tokens_in': ev['tokens_in'], 'tokens_out': ev['tokens_out'], 'cost_usd': cost}, ensure_ascii=False)}\n\n"
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Chat stream failed for paper %s (attempt %d/%d): %s",
                    paper_id, attempt + 1, _CHAT_MAX_ATTEMPTS, exc,
                )
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

