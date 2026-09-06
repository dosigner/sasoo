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
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
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
    table_row_to_api_dict,
)
from services.analysis_results import (
    get_latest_completed_phase_row,
    get_latest_completed_phase_rows,
)
from services.concurrency import run_chat_blocking, run_pipeline_blocking
from services.document_context import load_or_build_document_context
from services.evidence_repo import build_evidence_payload
from services.pricing import calc_cost
from services.llm.interactions_client import call_interaction, stream_interaction

from api.analysis_state import _running_analyses, _cancel_events, _analyses_lock
from api.analysis_helpers import _clean_llm_json, _SYSTEM_INSTRUCTION_KO
from services.model_registry import active_provider, resolve as resolve_model
from services.provider_state import key_env_for
from api.report_service import (
    _format_phase_data,
    _generate_paperbanana_image,
)
from api.figure_service import explain_figure_handler
from services.analysis_execution import (
    _MERMAID_STYLE_RULES,
    _MERMAID_SYNTAX_RULES,
    _config_hash,
    _generate_single_mermaid,
    _get_visual_contract,
    _lookup_phase_result_with_staleness,
    _phase_result_snippet,
    _sanitize_mermaid_code,
    _utcnow_iso,
    run_full_analysis,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


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
        # 워커가 run_full_analysis의 첫 UPDATE papers SET status='analyzing'에 도달하기 전에
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
        background_tasks.add_task(run_full_analysis, paper_id)

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

    return await _build_analysis_status(paper_id, paper, latest_results)


async def _build_analysis_status(paper_id: int, paper: dict, latest_results: dict) -> AnalysisStatus:
    """Build status from loaded rows while retaining live worker progress."""
    if paper_id in _running_analyses:
        return _running_analyses[paper_id]

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
        phases=["screening", "citation", "visual", "recipe", "deep_dive", "visualization", "viz_plan"],
    )

    # Build status
    status = await _build_analysis_status(paper_id, paper, latest_results)

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

    # LLM 원본 blob은 무수정 유지하고 검증 결과를 형제 필드로 붙인다.
    # evidence=None은 "검증 기록 없음"이지 "검증됨"이 아니다 — UI는 전 행을 미검증으로 표시한다.
    try:
        evidence = await build_evidence_payload(result.get("id"))
    except Exception as exc:
        logger.warning("evidence payload build failed for paper %s: %s", paper_id, exc)
        evidence = None

    return {
        "paper_id": paper_id,
        "recipe": result.get("parsed_result"),
        "model_used": result.get("model_used"),
        "created_at": result.get("created_at"),
        "evidence": evidence,
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

