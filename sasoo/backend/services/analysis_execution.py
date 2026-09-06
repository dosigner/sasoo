"""Analysis execution, phase prompts, cache contracts, and result persistence."""

import asyncio
import base64
import json
import logging
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)

from models.database import execute_insert, execute_update, fetch_all, fetch_one, get_paper_dir
from models.schemas import AnalysisPhase, AnalysisStatus, PhaseStatus
from services.odl_parser import schedule_paper_artifacts_refresh
from services.analysis_results import parse_phase_row
from services.artifact_status import resolve_artifact_status_contract, get_visual_row_counts
from services.concurrency import run_pipeline_blocking
from services.document_context import (
    build_visual_partial_cache_input,
    compute_input_hash,
    find_cached_phase_result,
    load_or_build_document_context,
)
from services.evidence_repo import ensure_recipe_anchors
# 종합 스테이지의 핵심 수치 검증은 값 가드(#48)와 같은 수치 동치 판정을 쓴다 —
# 리터럴 대조를 새로 짜면 "1,550"과 "1550"이 다른 값이 된다.
from services.evidence_verifier import _numeric_tokens, normalize_text
from services.pricing import calc_cost
from services.llm.interactions_client import call_interaction

from api.analysis_state import _running_analyses, _cancel_events, _analyses_lock
from api.analysis_helpers import (
    _clean_llm_json,
    _is_error_result,
    _stage_result_defect,
    drop_degenerate_fields,
    salvage_truncated_json,
)
# 이 세 상수는 캐시 키 빌더(_citation_cache_key, _visualization_cache_key)에만
# 남는다. 스테이지의 모델/effort는 model_registry가 정하지만, 그 두 키는
# _phase_cache_key를 거치지 않는 바깥 캐시라서 "Gemini 모델을 갈면 무효화"를
# 스스로 담아야 한다. 공급사 격리는 compute_input_hash(provider/model/effort)가
# 따로 하므로 역할이 겹치지 않는다. 테스트가 patch.object로 이 이름을 덮는다.
from services.models import MODEL_CITATION, MODEL_MERMAID, MODEL_VIZ_PLANNING
from services.model_registry import (
    ModelChoice,
    active_provider,
    provider_for_role,
    resolve as resolve_model,
)
# 함수 안에서 import하면 모듈 스텁이 깔린 테스트 구성에서 api.settings를 부분 import 상태로
# 오염시킨다(이 파일 상단 주석의 격리 사고와 같은 계열). 상단에서 한 번만 묶는다.
from api.settings import _get_all_settings

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().isoformat()


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
        "result_id": cached.result_id,
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


# Phase 0(2026-08-06): 캐시 키에 프로필·에이전트 지침(system_instruction)·모델·thinking을
# 포함한다. 값을 올리면 모든 체인 phase 캐시가 무효화된다.
# Phase 1(2026-08-06, Evidence Anchoring): 스펙 §결정 4에 따라 롤아웃 시 1회 bump한다.
# recipe 파라미터에 evidence_quote/evidence_page가 생겨 구 스키마 결과를 재사용하면
# 근거 없는 파라미터가 영구히 남는다. 체인 phase 전체가 1회 재과금되는 것을 알고 하는 선택이다.
_CHAIN_CACHE_VERSION = "2026-08-06-ev1"


def _phase_cache_key(*, model: str, thinking: str, system_instruction: str, prompt: str) -> str:
    return "\n\x1f\n".join((_CHAIN_CACHE_VERSION, model, thinking, system_instruction or "", prompt))


def _visualization_cache_input(
    *,
    visualization_input,
    previous_results,
    recipe_result,
    deep_dive_result,
    image_provider: str,
    image_quality: str,
) -> str:
    """시각화 phase의 캐시 키.

    이 phase는 캐시가 히트하면 계획뿐 아니라 **생성된 이미지까지** 통째로 재사용한다.
    그래서 이미지 공급사와 품질이 키에 들어가야 한다 — 빠지면 사용자가 설정에서 품질을
    바꿔도 예전 이미지가 그대로 나오고, 고른 값이 결과를 바꾸지 않는다(DEC-013이 걷어낸
    거짓 통제와 같은 종류다). 체인 버전도 다른 phase와 같이 담는다.
    """
    return json.dumps(
        {
            "chain_version": _CHAIN_CACHE_VERSION,
            "visualization_input": visualization_input,
            "previous_results": previous_results,
            "recipe_result": recipe_result,
            "deep_dive_result": deep_dive_result,
            "image_provider": image_provider,
            "image_quality": image_quality,
            # 이 바깥 캐시는 _phase_cache_key를 거치지 않으므로 모델을 직접 담아야 한다.
            # 담지 않으면 모델을 갈아도 옛 모델이 만든 계획과 이미지가 그대로 나온다.
            # 이미지 모델 ID는 담지 않는다(공급사와 품질로 대신한다) — 이미지 모델 자체를
            # 바꿀 때는 _CHAIN_CACHE_VERSION을 올려라.
            "plan_model": MODEL_VIZ_PLANNING,
            "mermaid_model": MODEL_MERMAID,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


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
) -> int:
    """analysis_results에 결과를 저장하고 lastrowid를 반환한다.

    반환값은 Evidence 앵커를 이 행에 결속하는 데 쓴다(스펙 §결정 4). 기존 호출부는
    반환값을 쓰지 않으므로 동작이 바뀌지 않는다.
    """
    return await execute_insert(
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


async def _ensure_recipe_evidence(
    *,
    paper_id: int,
    analysis_result_id,
    recipe_text: str,
    folder_name: str,
) -> None:
    """Recipe 파라미터 근거를 결정론적으로 검증해 evidence_anchors에 기록한다.

    예외를 밖으로 내보내지 않는다 — 검증기 실패가 recipe phase를 죽이면 안 된다.
    실패하면 앵커가 남지 않고, 앵커 부재는 UI에서 '검증 미실행'으로 정직하게 보인다
    (부재를 검증됨으로 표시하는 코드 경로는 존재하지 않는다).
    """
    if not analysis_result_id or not folder_name:
        logger.info(
            "evidence anchoring skipped (paper=%s result_id=%r folder=%r)",
            paper_id, analysis_result_id, folder_name,
        )
        return
    try:
        pdf_path = _find_paper_pdf(get_paper_dir(folder_name))
        await ensure_recipe_anchors(
            paper_id=paper_id,
            analysis_result_id=int(analysis_result_id),
            recipe_text=recipe_text,
            pdf_path=pdf_path,
        )
    except Exception as exc:
        logger.warning(
            "evidence anchoring failed (paper=%s result=%s): %s",
            paper_id, analysis_result_id, exc,
        )


async def _get_visual_contract(
    paper_id: int,
    paper_dir: Path,
    *,
    schedule_refresh: bool,
) -> tuple[dict, int, int]:
    figure_count, table_count = await get_visual_row_counts(paper_id)
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
    # 두 메커니즘을 함께 쓴다. _phase_cache_key는 _CHAIN_CACHE_VERSION을 담아
    # 체인 프롬프트를 바꿀 때 전 캐시를 한 번에 무효화하고(main #47),
    # compute_input_hash의 provider/model/effort는 공급사별 결과를 격리한다.
    # model/effort가 양쪽에 이중으로 들어가지만 해시 입력이 늘 뿐 무해하다.
    # 한쪽만 남기면 버전 무효화 또는 공급사 격리가 조용히 사라진다.
    cache_key = _phase_cache_key(
        model=choice.model, thinking=choice.effort or "", system_instruction="", prompt=prompt,
    )
    cached = await _get_cached_phase_result(
        paper_id, "screening", cache_key, provider=provider, model=choice.model, effort=choice.effort,
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
        salvaged = salvage_truncated_json(result.get("text") or "", _SCREENING_SCHEMA)
        if salvaged is not None:
            logger.warning(
                "screening %s (tokens_out=%s); 잘린 앞부분을 살려 재시도를 건너뛴다",
                defect, result.get("tokens_out"),
            )
            result["text"] = salvaged
        else:
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
        cache_key,
        interaction_id=result.get("interaction_id"),
        provider=provider,
        model=choice.model,
        effort=choice.effort,
    )

    # Update status
    if _is_error_result(result["text"]):
        phase_status.status = "error"
        phase_status.error_message = "LLM 응답을 구조화하지 못했습니다 (JSON 파싱 실패, 1회 재시도 포함)"
    else:
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

    문구를 고쳐도 재과금이 없고, 계약이 실제로 바뀔 때 _CITATION_PROMPT_VERSION을 올려 1회 무효화한다.

    이 키는 _phase_cache_key를 거치지 않으므로 모델을 직접 담아야 한다. 담지 않으면
    모델을 갈아도 이 phase만 옛 모델이 만든 인용 분석을 계속 내놓는다. thinking_level은
    호출부에 "low"로 고정돼 있어 담지 않는다. 단계별로 고를 수 있게 바뀌면 같이 담아라."""
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
        "model": MODEL_CITATION,
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
# Stateful chain: Visual -> Recipe -> Deep Dive -> Viz planning (MODEL_FLASH_HQ)
# ---------------------------------------------------------------------------

# 체인 스테이지 이름과 레지스트리 role의 번역표.
# "visualization"(파이프라인 내부 명)만 레지스트리 role "viz_planning"과 다르다.
_PHASE_TO_ROLE = {
    "visual": "visual",
    "recipe": "recipe",
    "deep_dive": "deep_dive",
    "visualization": "viz_planning",
}

# 폭주 반복이 뚫렸을 때의 손해 상한. 스키마 쪽 조치(마지막 속성을 숫자로)가 1차
# 방어고, 이건 그게 뚫려도 비용이 유한하게 끝나도록 하는 2차 방어다.
# 값 근거: 실측 최대 정상 recipe 본문이 12,416자(파라미터 26개 완성)였고, 폭주는
# 모델 상한 65,536까지 갔다. 이 상한은 **thinking 토큰을 포함해서 센다**(문서에 없어
# 실호출로 확인. 상한 2,000 -> tokens_out 1,986, 그중 thinking 1,213). recipe의
# medium thinking이 실측 600~4,000이라 24,000이면 본문에 최소 20,000이 남는다.
# 상한에 걸리면 status가 incomplete로 오고 꼬리가 잘리는데, 그건 이미
# salvage_truncated_json이 값 경계에서 되살린다.
# deep_dive 16,000의 값 근거(2026-08-29 실측, RESEARCH/2026-08-29-provider-chain-token-convergence.md):
# 정상 최대 출력이 8,734(luna xhigh), Gemini 정상은 2,840~6,946이었다. VLA 6편 실측에서
# Gemini deep_dive가 high thinking에서도 4/6 폭주했고, 이 상한이 폭주당 손해를
# $0.26에서 $0.06으로 막는 것을 실증했다.
# 잠금: api/test_recipe_output_bounds.py, api/test_deep_dive_schema.py,
#      services/test_model_pins.py
_STAGE_MAX_OUTPUT_TOKENS = {"recipe": 24_000, "deep_dive": 16_000}

# _STAGE_THINKING과 _STAGE_MODELS는 model_registry가 대체했다(provider x role).
# 스테이지의 모델/effort는 _stage_choice()로만 구한다 — 두 출처를 두면 provider가
# openai일 때 캐시 키와 실제 호출이 어긋난다.


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
                    # Evidence Anchoring(Phase 1): LLM은 후보만 낸다.
                    # verification_status·matched_quote·bbox는 절대 LLM 출력 필드로 두지 않는다.
                    "evidence_quote": {"type": "string"},
                    # 1-based PDF 페이지. Gemini structured output이 minimum을 일관되게
                    # 지원하지 않아 범위 제약은 스키마가 아니라 검증기가 건다(invalid_page).
                    "evidence_page": {"type": "integer"},
                },
                "required": ["name", "value", "source_tag"],
            },
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "critical_notes": {"type": "array", "items": {"type": "string"}},
        "expected_results": {"type": "string"},
        "safety_notes": {"type": "string"},
        "confidence": {"type": "number"},
        "missing_info": {"type": "array", "items": {"type": "string"}},
        # 마지막 속성은 자유서술 문자열로 두지 않는다. 구조화 출력은 JSON 문법을
        # 강제하지만 문자열 값 안에서는 어떤 토큰도 합법이라, 모델이 "끝났다"고
        # 판단하고도 종료 토큰을 못 내면 그 안에 갇혀 상한까지 필러를 뱉는다.
        # 여기 있던 score_rationale이 정확히 그 자리였다(3.6·3.7 공통).
        # 잠금: api/test_recipe_output_bounds.py
        "reproducibility_score": {"type": "number"},
    },
    "required": ["title", "objective", "parameters", "steps"],
}

# detailed_analysis("여러 문단" 자유서술)를 경계 있는 구조화 필드로 분해했다.
# DEC-014가 지목한 폭주 유형(긴 자유서술)을 없애면서 문제정의·as-is/to-be·솔루션·
# method·result가 결과 JSON에서 바로 드러나게 한다. 잠금: api/test_deep_dive_schema.py
_DEEP_DIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "problem_definition": {"type": "string"},
        "as_is": {"type": "string"},
        "to_be": {"type": "string"},
        "solution": {"type": "string"},
        "method_summary": {"type": "string"},
        "key_results": {"type": "string"},
        "novelty_assessment": {"type": "string"},
        "comparison_to_prior_work": {"type": "string"},
        # "논문 자체 비교 범위 안의 평가"라는 한정을 본문 문구가 아니라 이 필드가 나른다.
        # 2026-08-29 VLA 실측에서 그 한정 문구를 본문에 "명시해"라고 요구했더니 모델이
        # 그 문구를 무한 반복하며 폭주했다(4/6). 정형 문구는 enum으로 옮기는 것이 원칙.
        "comparison_scope": {"type": "string", "enum": ["in_paper_only"]},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
        "suggested_improvements": {"type": "array", "items": {"type": "string"}},
        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
        # 마지막 속성을 자유서술 단일 문자열로 두지 않는다(폭주 자리 방지, DEC-014).
        "practical_applications": {"type": "array", "items": {"type": "string"}},
    },
    # as_is·to_be만 required에서 뺀다. 이 둘은 논문에 그 구도가 아예 없을 수 있어
    # (이론·리뷰 논문) 강제하면 모델이 지어낸다. 나머지는 논문 내용을 옮기는 칸이
    # 아니라 모델이 분석해서 쓰는 칸이라 지어내기 위험이 낮다.
    #
    # 아래 5필드는 2026-08-29 실측에서 Gemini가 4/4로 통째 생략했다(폭주 없이
    # 정상 완료한 실행에서도 9/14). Luna는 같은 조건에서 14/14를 냈다. 프롬프트로
    # 요청만 하면 provider별 준수율이 갈리고, required는 양쪽 다 지킨다 —
    # 수렴은 지시문이 아니라 스키마로 만든다(DEC-020).
    # 잠금: api/test_deep_dive_schema.py
    "required": [
        "problem_definition", "solution", "method_summary", "key_results",
        "strengths", "weaknesses", "comparison_scope",
        "novelty_assessment", "comparison_to_prior_work",
        "suggested_improvements", "follow_up_questions", "practical_applications",
    ],
}

_DEEP_DIVE_INSTRUCTION = """이 논문에 대한 심층 분석을 해줘. 전문적이면서도 이해하기 쉽게,
선배 연구자가 후배에게 설명하듯이 써줘.

규칙:
- 논문 PDF(또는 논문 텍스트)가 최우선 근거야. 앞선 단계(시각·레시피·스크리닝·인용) 결과는
  탐색용 힌트일 뿐이니, 논문에서 직접 확인한 내용만 사실로 서술해.
- 강점·약점에는 근거가 된 논문 위치(섹션/그림/표)를 함께 적어.
- novelty_assessment와 comparison_to_prior_work는 논문이 스스로 제시한 비교 범위 안에서만
  평가하고, 외부 문헌과 대조하지 마. 이 한정은 comparison_scope 필드가 표시하니
  본문에 같은 문구를 반복해 적지 마.
- 논문에 없는 반례·실험·선행연구를 만들어내지 마.
- 빈 문자열로 둘 수 있는 필드는 as_is와 to_be 둘뿐이야(그 구도가 없는 논문이 있으니까).
  나머지 필드는 전부 채워. 논문 근거가 얇으면 얇은 대로 짧게 쓰되, 비우지는 마.

출력 필드:
- problem_definition: 논문이 풀려는 문제가 무엇이고 왜 중요한지 (2~4문장)
- as_is: 기존 접근이 어디까지 왔고 무엇이 부족한지. 이런 구도가 없는 논문이면 빈 문자열 (2~3문장)
- to_be: 이 논문이 도달하려는 상태나 목표. 구도가 없으면 빈 문자열 (1~2문장)
- solution: 문제를 푸는 핵심 아이디어와 그 아이디어가 통하는 이유 (2~4문장)
- method_summary: 방법의 서술형 요약. 실험 논문은 절차의 흐름, 이론 논문은 유도의 뼈대,
  시뮬레이션 논문은 모델과 설정, 리뷰 논문은 문헌 선정·분류 기준을 중심으로 (1~2문단)
- key_results: 핵심 결과. 수치와 조건은 논문에 적힌 그대로 옮겨 (1~2문단)
- novelty_assessment: 새로움 평가
- comparison_to_prior_work: 기존 연구 대비 비교
- comparison_scope: 항상 "in_paper_only"로 채워(위 두 평가가 논문 자체 비교 범위 기준이라는 표시)
- strengths: 강점 리스트 / weaknesses: 약점 리스트
- suggested_improvements: 개선 제안 리스트 / follow_up_questions: 후속 질문 리스트 /
  practical_applications: 실용적 응용 리스트"""


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


# 스펙 §5.4. 개념도 1개(PaperBanana)와 Mermaid 다이어그램을 분리하고, 구획(block)과
# 종류(diagram_type)를 enum으로 고정한다. 마지막 속성은 숫자다(DEC-014).
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
                max_output_tokens=_STAGE_MAX_OUTPUT_TOKENS.get(phase),
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
            max_output_tokens=_STAGE_MAX_OUTPUT_TOKENS.get(phase),
        )

    result = await _invoke()
    defect = _stage_result_defect(result.get("text") or "")
    if defect:
        # 상한에 걸려 꼬리만 잘린 경우가 있다. 앞부분이 온전하면 그걸 쓰고 재시도를
        # 건너뛴다. 같은 요청을 그대로 다시 보내면 같은 자리에서 또 잘리므로
        # (실측 2026-08-16: 65522 토큰 x 2) 재시도는 값만 두 배가 된다.
        salvaged = salvage_truncated_json(result.get("text") or "", response_schema or {})
        if salvaged is not None:
            logger.warning(
                "chain stage %s %s (tokens_out=%s); 잘린 앞부분을 살려 재시도를 건너뛴다",
                phase, defect, result.get("tokens_out"),
            )
            result["text"] = salvaged
            return result
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
        # 재시도 결과도 검사한다. 파싱 실패는 _raw/_parse_error 경로가 받아 주지만,
        # 파싱은 되면서 값만 오염된 출력은 받아 줄 경로가 없어 그대로 저장됐다.
        # 실측 2026-08-17: DB에 그렇게 저장된 recipe 행이 3개(전부 3.6-flash) 있었고
        # 그중 하나는 화면에 나가는 프로덕션 행이었다.
        retry_defect = _stage_result_defect(result.get("text") or "")
        if retry_defect == "degenerate repetition detected":
            pruned = drop_degenerate_fields(result.get("text") or "", response_schema or {})
            if pruned is not None:
                logger.warning(
                    "chain stage %s 재시도도 %s; 오염 필드를 떨어내고 나머지를 저장한다",
                    phase, retry_defect,
                )
                result["text"] = pruned
            else:
                # 오염된 값이 required라 떨어내면 빈 껍데기가 된다. 기존 경로에 맡긴다.
                logger.warning(
                    "chain stage %s 재시도도 %s; 필수 필드가 오염돼 떨어낼 수 없다",
                    phase, retry_defect,
                )
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
    cache_key = _phase_cache_key(
        model=choice.model,
        thinking=choice.effort or "",
        system_instruction=system_instruction,
        prompt=prompt_fallback,
    )

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

    if _is_error_result(result["text"]):
        phase_status.status = "error"
        phase_status.error_message = "LLM 응답을 구조화하지 못했습니다 (JSON 파싱 실패, 1회 재시도 포함)"
    else:
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
    folder_name: str = "",
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
6. reproducibility_score는 explicit 핵심 파라미터의 충족도와 missing_info를 근거로 매겨.
7. 각 파라미터마다 그 값의 근거가 되는 논문 원문을 그대로(축자) evidence_quote에 옮겨.
   번역·요약·재작성·말줄임표·떨어져 있는 문장 결합은 금지야. 원문 언어 그대로 써.
8. evidence_quote는 그 파라미터를 뒷받침하는 가장 짧은 연속 스팬 하나로 해(1~2문장, 최대 300자).
   source_tag="explicit"이면 그 value가 인용 안에 실제로 들어 있어야 해.
9. evidence_page는 PDF 파일 기준 1-based 페이지 번호야(표지 포함). 논문에 인쇄된 페이지 번호가 아니야.
   논문 텍스트만 받은 경우에는 "--- Page N ---" 마커의 N을 써.
10. 축자로 옮길 수 없으면 evidence_quote를 빈 문자열로 두고 페이지도 추측하지 마.
    빈 근거가 지어낸 근거보다 나아 — 근거 없음은 화면에 그대로 표시돼.
11. 인용은 논문 PDF(또는 제공된 논문 텍스트)에서만 가져와. 앞선 단계(스크리닝·시각·인용 분석)
    결과는 인용 출처가 아니야.
12. name은 아래 DOMAIN-SPECIFIC PARAMETERS 목록에 있는 항목이면 그 표기를 그대로 쓰고,
    목록에 없으면 축약 없는 소문자 snake_case 전체 명칭으로 써(예: aperture가 아니라
    aperture_diameter). 같은 물리량에 임의의 다른 이름을 만들지 마.
{domain_hint}

출력 필드: title(레시피 제목, 한국어), objective(실험 목적), materials(재료 리스트, 규격 포함),
equipment(장비 리스트, 모델번호 포함), parameters(각 항목 name/value/unit/notes/source_tag/evidence_quote/evidence_page),
steps(단계별 상세 설명, 온도·시간·속도 등 포함), critical_notes(재현 중요 참고사항),
expected_results(예상 결과), safety_notes(안전 주의사항), confidence(0.0~1.0),
missing_info(논문에 없어 재현에 걸림돌이 되는 항목), reproducibility_score(0.0~1.0)."""

    prompt_chain = f"{instruction}\n\n{_doc_reference_phrase(provider)}와 이전 분석을 바탕으로 실험 레시피를 추출해줘."
    prompt_fallback = f"논문 텍스트:\n{recipe_input}\n\n{instruction}"
    cache_key = _phase_cache_key(
        model=choice.model,
        thinking=choice.effort or "",
        system_instruction=system_instruction,
        prompt=prompt_fallback,
    )

    cached = await _get_cached_phase_result(
        paper_id, "recipe", cache_key, provider=provider, model=choice.model, effort=choice.effort,
    )
    if cached is not None:
        # 캐시 히트도 검증을 태운다 — 옛 결과 백필과 검증기 버전업 재검증의 유일한 통로다.
        # completed로 세팅하기 전에 먼저 끝내야 한다 — await 경계 사이에 폴링이
        # completed+evidence=None을 볼 수 있다(리뷰 지적 M-3, 비캐시 경로와 순서를 맞춘다).
        await _ensure_recipe_evidence(
            paper_id=paper_id,
            analysis_result_id=cached.get("result_id"),
            recipe_text=cached["text"],
            folder_name=folder_name,
        )
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

    result_id = await _insert_analysis_result(
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

    # recipe row 저장(lastrowid 확보) 직후, phase completed 노출 전 동기 검증(스펙 §결정 3).
    # 41페이지 논문 실측 ~0.4초의 순수 CPU 작업이라 별도 큐·phase를 만들지 않는다.
    if not _is_error_result(result["text"]):
        await _ensure_recipe_evidence(
            paper_id=paper_id,
            analysis_result_id=result_id,
            recipe_text=result["text"],
            folder_name=folder_name,
        )

    if _is_error_result(result["text"]):
        phase_status.status = "error"
        phase_status.error_message = "LLM 응답을 구조화하지 못했습니다 (JSON 파싱 실패, 1회 재시도 포함)"
    else:
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
    cache_key = _phase_cache_key(
        model=choice.model,
        thinking=choice.effort or "",
        system_instruction=system_instruction,
        prompt=prompt_fallback,
    )

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

    if _is_error_result(result["text"]):
        phase_status.status = "error"
        phase_status.error_message = "LLM 응답을 구조화하지 못했습니다 (JSON 파싱 실패, 1회 재시도 포함)"
    else:
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
    cache_key = _phase_cache_key(
        model=choice.model,
        thinking=choice.effort or "",
        system_instruction=system_instruction,
        prompt=prompt_fallback,
    )

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
# mindmap은 스펙 §5.5로 빠졌다(구획 배정에 쓸 수 없고 스타일 규칙도 안 받는다).
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
    _image_settings = await _get_all_settings()
    visualization_cache_input = _visualization_cache_input(
        visualization_input=visualization_input,
        previous_results=previous_results,
        recipe_result=recipe_result,
        deep_dive_result=deep_dive_result,
        image_provider=_image_settings.get("image_provider", "openai"),
        image_quality=_image_settings.get("image_quality", "high"),
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

async def run_full_analysis(paper_id: int) -> None:
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
            folder_name=folder_name,
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
        # 이 단계만 provider가 갈릴 수 있다(DEC-019 — Gemini deep_dive 폭주 회피).
        # 갈리면 서버측 체인 상태를 공유할 수 없으므로 PDF 대신 텍스트를 주입해
        # 새 체인을 시작한다. 앞선 시각·레시피 결과는 _run_deep_dive가 붙이는
        # restart_context가 복원한다.
        dd_provider = await provider_for_role("deep_dive")
        dd_chained = dd_provider == provider
        r4 = await _run_deep_dive(
            paper_id,
            str(phase_inputs.get("deep_dive", "")),
            previous,
            status,
            screening_result_text=r1.get("text", ""),
            citation_result_text=r_cit.get("text", ""),
            system_instruction=deep_dive_system_instruction,
            previous_interaction_id=chain_prev_id if dd_chained else None,
            pdf_uri=pdf_uri if dd_chained else None,
            doc_text=doc_text if dd_chained else full_text[:_OPENAI_DOC_TEXT_CHAR_LIMIT],
            provider=dd_provider,
        )
        # provider가 갈렸으면 r4의 interaction_id는 다른 서버의 것이라 이어 쓸 수 없다.
        # visualization은 레시피까지의 체인을 그대로 잇는다.
        if dd_chained and (pdf_uri or doc_text):
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


