#!/usr/bin/env python3
"""GPT-5.6 Luna vs 프로덕션 Gemini(model_registry가 고르는 모델) 출력·품질·비용 성향 비교 (R9).

sasoo의 실제 프롬프트·스키마·모델 레지스트리를 그대로 써서 같은 논문을 두
공급사의 5단계 전체(screening·citation·visual·recipe·deep_dive)에 넣고,
출력과 품질·비용 신호를 나란히 저장한다. 판단은 하지 않는다 — 원자료만
만든다. 승격 판단은 이 도구의 기록으로만 한다 — 앱 내 A/B는 없다.

    cd sasoo/backend && .venv/bin/python tools/provider_compare.py
    cd sasoo/backend && .venv/bin/python tools/provider_compare.py --role deep_dive --efforts high,xhigh

키는 sasoo 설정 DB에서 읽는다(암호화 저장분을 복호화). 환경변수가 이미
있으면 그쪽을 우선한다.

설계 메모(직전 태스크 컨텍스트 + 실측):
- 모델/effort는 항상 services.model_registry.resolve(role, provider)로
  조회한다 — 레지스트리가 단일 소스다(하드코딩된 STAGES 표를 여기서 다시
  만들지 않는다).
- LLM 호출은 services.llm.interactions_client.call_interaction을 그대로
  쓴다(gpt-* 접두는 openai_client로, 그 외는 gemini_client로 자동 라우팅).
  Gemini는 client.interactions.create(신형 Interactions API)를 쓰고
  reasoning/cached 토큰도 이 경로에서 나온다 — 원래 이 파일이 쓰던
  client.models.generate_content()는 이미 프로덕션이 쓰지 않는 경로였다.
- provider별 문서 입력 방식은 실제 배선(스펙 R1)을 그대로 따른다: Gemini는
  PDF Files API 업로드 URI를 document 파트로, OpenAI는 로컬 추출
  전문(doc_text, _OPENAI_DOC_TEXT_CHAR_LIMIT 상한)을 텍스트로 주입한다.
  둘 다 파일 업로드하던 옛 버전은 OpenAI 쪽 실동작과 달랐다.
- 이 도구는 완전히 독립적인 스테이지 비교다 — 프로덕션의 스크리닝→체인
  (previous_interaction_id, persona/reader-profile 시스템 지시문, recipe의
  도메인 힌트)은 재현하지 않는다. store=False로 모든 호출을 stateless로
  보낸다. DB에는 쓰지 않는다(analysis_results/papers 테이블 무변경) —
  Gemini PDF 업로드도 papers.pdf_file_uri 캐시를 쓰는 프로덕션 헬퍼
  (upload_pdf_for_paper) 대신 이 파일 안의 독립 업로드 함수를 쓴다.
- defect_final은 api.analysis_helpers._stage_result_defect(JSON 파싱 실패·
  반복 루프 오염 감지 — PR #44)를 그대로 써서 최종 결과가 결함인지 기록한다.
  재시도 횟수(defect_retries)는 프로덕션의 "JSON 파싱 실패 시 1회 재시도"
  정책(_run_screening, _run_chain_stage)을 이 파일 안에서 그대로 재현해
  센다 — citation은 프로덕션도 재시도하지 않으므로 이 도구도 재시도하지
  않는다.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_PAPER_ID = 43  # Saliency Optimization — 그림 33개·표 13개로 vision 비교에 적합
OUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "provider_compare"

# 이 도구가 다루는 5단계. model_registry.ROLES의 부분집합(viz_planning 등
# 나머지 role은 R9 범위 밖).
STAGE_ROLES: tuple[str, ...] = ("screening", "citation", "visual", "recipe", "deep_dive")

PROVIDERS: tuple[str, ...] = ("gemini", "openai")


def load_keys() -> dict[str, str]:
    """환경변수 우선, 없으면 sasoo 설정 DB에서 복호화해 읽는다."""
    keys = {
        "openai": os.environ.get("OPENAI_API_KEY", ""),
        "gemini": os.environ.get("GEMINI_API_KEY", ""),
    }
    if keys["openai"] and keys["gemini"]:
        return keys

    import sqlite3

    from services.crypto import decrypt_value

    db_path = Path(__file__).resolve().parents[1] / "library" / "sasoo.db"
    conn = sqlite3.connect(db_path)
    try:
        rows = dict(
            conn.execute(
                "SELECT key, value FROM settings WHERE key IN "
                "('openai_api_key', 'gemini_api_key')"
            ).fetchall()
        )
    finally:
        conn.close()

    for provider, setting in (("openai", "openai_api_key"), ("gemini", "gemini_api_key")):
        if keys[provider]:
            continue
        stored = rows.get(setting) or ""
        keys[provider] = decrypt_value(stored) if stored else ""
    return keys


def load_paper(paper_id: int) -> tuple[Path, dict]:
    """논문 PDF 경로와 추출 메타데이터(figure/table 상세 포함)를 가져온다."""
    import sqlite3

    from models.database import get_paper_dir

    db_path = Path(__file__).resolve().parents[1] / "library" / "sasoo.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        paper = conn.execute(
            "SELECT id, title, folder_name, authors FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if paper is None:
            raise SystemExit(f"paper {paper_id} not found")
        figures = [
            dict(r)
            for r in conn.execute(
                """
                SELECT figure_num, quality, confidence, resolver_version FROM figures
                WHERE paper_id = ? AND COALESCE(extraction_status, 'resolved') != 'rejected'
                """,
                (paper_id,),
            ).fetchall()
        ]
        tables = [
            dict(r)
            for r in conn.execute(
                """
                SELECT table_num, confidence, parse_method, resolver_version FROM tables
                WHERE paper_id = ? AND COALESCE(extraction_status, 'resolved') != 'rejected'
                """,
                (paper_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    folder = get_paper_dir(paper["folder_name"])
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"no pdf under {folder}")

    meta = {
        "paper_id": paper["id"],
        "title": paper["title"],
        "authors": paper["authors"] or "",
        "folder": str(folder),
        "figures": figures,
        "tables": tables,
    }
    return pdfs[0], meta


def build_visual_figure_desc(meta: dict) -> str:
    """_run_visual의 figure_desc 문자열 구성과 동일 포맷(api/analysis_routes.py)."""
    figures, tables = meta["figures"], meta["tables"]
    if not figures and not tables:
        return ""
    desc = f"\n\nExtracted {len(figures)} resolved figures and {len(tables)} resolved tables from the paper."
    for fig in figures:
        desc += (
            f"\n- {fig['figure_num']}: quality={fig.get('quality')}, "
            f"confidence={fig.get('confidence')}, resolver={fig.get('resolver_version')}"
        )
    for table in tables[:10]:
        desc += (
            f"\n- {table['table_num']}: confidence={table.get('confidence')}, "
            f"method={table.get('parse_method')}, resolver={table.get('resolver_version')}"
        )
    return desc


# ---------------------------------------------------------------------------
# 스테이지별 프롬프트/스키마 — 스키마는 전부 api.analysis_routes에서 실물을
# 그대로 가져온다(단일 소스). 인스트럭션은 static 상수(_VISUAL_INSTRUCTION,
# _DEEP_DIVE_INSTRUCTION)는 그대로 임포트하고, 동적으로 조립되는 것
# (screening/recipe/citation)은 이 도구가 독립 실행(체이닝 없음)이라는
# 전제로 원문을 옮겨 적었다 — screening은 스크리닝 결과 의존이 없어
# 완전 동형, recipe는 도메인 힌트(스크리닝 결과 의존)를 생략한다.
# ---------------------------------------------------------------------------

def screening_prompt(screening_input: str):
    from api import analysis_routes as ar

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
    return prompt, ar._SCREENING_SCHEMA


def citation_prompt(phase_inputs: dict, sections: dict, paper_authors: str):
    """analyze_citations로 로컬 파싱 후 _run_citation과 동형인 LLM 프롬프트를 만든다.

    top_cited가 비면(참고문헌 파싱 실패 등) 프로덕션도 LLM을 호출하지 않는다 —
    이 도구도 None을 돌려줘 상위 루프가 스킵하게 한다.
    """
    from api import analysis_routes as ar
    from services.citation_analyzer import analyze_citations

    citation_body = str(phase_inputs.get("citation_body", ""))
    citation_references = str(phase_inputs.get("citation_references", ""))
    analysis = analyze_citations(
        references_text=citation_references,
        body_text=citation_body,
        sections=sections,
        paper_authors=paper_authors,
    )
    local_result = analysis.to_dict()
    top_refs = local_result.get("top_cited", [])[:10]
    if not top_refs:
        return None, None, local_result

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

    prompt = f"""아래는 로컬 파서가 이 논문에서 추출한 참고문헌 통계와 상위 인용 맥락이야.

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
    return prompt, ar._CITATION_SCHEMA, local_result


def visual_prompt(meta: dict):
    from api import analysis_routes as ar

    figure_desc = build_visual_figure_desc(meta)
    text = f"{ar._VISUAL_INSTRUCTION}\n\n위 논문 PDF를 직접 보고 시각 요소를 분석해줘.{figure_desc}"
    return text, ar._VISUAL_SCHEMA


def recipe_prompt():
    from api import analysis_routes as ar

    # 도메인 힌트(domain_hint)는 스크리닝 결과에 의존하는데 이 도구는 스테이지를
    # 독립 실행하므로 생략한다 — 나머지 지시문은 _run_recipe와 동일.
    instruction = """이 연구 논문에서 재현 가능한 실험 레시피를 추출해줘.

핵심 지시사항:
1. 재현에 필요한 정량 파라미터를 논문 전체(Methods뿐 아니라 Results·Discussion·그림 캡션·표·부록)에서 빠짐없이 찾아.
2. 각 파라미터마다 name, value, unit, notes(출처 섹션/문맥), source_tag를 포함해.
3. source_tag 규칙:
   - "explicit": 논문에 값이 직접 명시됨.
   - "inferred": 논문에 명시된 다른 값에서 계산·추론 가능 — notes에 근거와 계산을 적어.
4. 개수 목표는 없어. 논문에 실제로 있는 항목만 추출하고, 통상 기본값·상식·장비 기본 설정을 논문 값처럼 보충하지 마.
5. 재현에 필요한데 논문에 없는 항목은 parameters에 넣지 말고 missing_info에 기록해.
6. reproducibility_score는 explicit 핵심 파라미터의 충족도와 missing_info를 근거로 매기고, 그 근거를 score_rationale에 한 문장으로 적어.

출력 필드: title(레시피 제목, 한국어), objective(실험 목적), materials(재료 리스트, 규격 포함),
equipment(장비 리스트, 모델번호 포함), parameters(각 항목 name/value/unit/notes/source_tag),
steps(단계별 상세 설명, 온도·시간·속도 등 포함), critical_notes(재현 중요 참고사항),
expected_results(예상 결과), safety_notes(안전 주의사항), confidence(0.0~1.0),
missing_info(논문에 없어 재현에 걸림돌이 되는 항목), reproducibility_score(0.0~1.0), score_rationale(점수 근거)."""
    text = f"{instruction}\n\n위 논문 PDF와 이전 분석을 바탕으로 실험 레시피를 추출해줘."
    return text, ar._RECIPE_SCHEMA


def deep_dive_prompt():
    from api import analysis_routes as ar

    text = f"{ar._DEEP_DIVE_INSTRUCTION}\n\n위 논문 PDF를 바탕으로 포괄적인 심층 분석을 제공해줘."
    return text, ar._DEEP_DIVE_SCHEMA


def build_prompt(stage: str, meta: dict, phase_inputs: dict, sections: dict):
    """스테이지별 (prompt, schema) 또는 citation의 (prompt, schema, local_result)."""
    if stage == "screening":
        prompt, schema = screening_prompt(phase_inputs.get("screening", ""))
        return prompt, schema, None
    if stage == "citation":
        prompt, schema, local_result = citation_prompt(phase_inputs, sections, meta["authors"])
        return prompt, schema, local_result
    if stage == "visual":
        prompt, schema = visual_prompt(meta)
        return prompt, schema, None
    if stage == "recipe":
        prompt, schema = recipe_prompt()
        return prompt, schema, None
    if stage == "deep_dive":
        prompt, schema = deep_dive_prompt()
        return prompt, schema, None
    raise ValueError(f"unknown stage: {stage}")


# ---------------------------------------------------------------------------
# Gemini PDF 업로드 — services.llm.gemini_client.upload_pdf_for_paper은
# papers.pdf_file_uri를 DB에 캐시한다(프로덕션 앱 상태 변경). 이 도구는
# 읽기 전용이어야 하므로 독립 업로드 함수를 둔다. 한글 파일명 안전 업로드
# 기법(경로 문자열 대신 열린 파일 핸들 + mime_type)은 그 함수에서 배운
# 교훈을 그대로 적용한다.
# ---------------------------------------------------------------------------

def upload_pdf_gemini(pdf_path: Path, api_key: str) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    with open(pdf_path, "rb") as handle:
        uploaded = client.files.upload(
            file=handle,
            config={"mime_type": "application/pdf", "display_name": pdf_path.name},
        )
    return uploaded.uri


# ---------------------------------------------------------------------------
# 재시도 정책 — _run_screening/_run_chain_stage의 "JSON 파싱 실패 시 1회
# 재시도, 비용은 attempt별로 합산" 정책을 그대로 재현한다. citation은
# 프로덕션도 재시도하지 않으므로 이 함수를 쓰지 않는다.
# ---------------------------------------------------------------------------

async def call_stage_with_retry(contents, *, model: str, effort: str | None, schema: dict) -> tuple[dict, int]:
    from api.analysis_helpers import _clean_llm_json
    from services.llm.interactions_client import call_interaction
    from services.pricing import calc_cost

    async def _invoke() -> dict:
        return await call_interaction(
            contents,
            lane="pipeline",
            model=model,
            thinking_level=effort,
            response_schema=schema,
            store=False,
        )

    result = await _invoke()
    try:
        json.loads(_clean_llm_json(result.get("text") or ""))
    except (json.JSONDecodeError, TypeError):
        retry = await _invoke()
        prior_cost = calc_cost(
            result["model"], result.get("tokens_in") or 0, result.get("tokens_out") or 0,
        ) + calc_cost(
            retry["model"], retry.get("tokens_in") or 0, retry.get("tokens_out") or 0,
        )
        retry["cost_usd_prior_attempts"] = prior_cost
        retry["tokens_in"] = (result.get("tokens_in") or 0) + (retry.get("tokens_in") or 0)
        retry["tokens_out"] = (result.get("tokens_out") or 0) + (retry.get("tokens_out") or 0)
        retry["tokens_thought"] = (result.get("tokens_thought") or 0) + (retry.get("tokens_thought") or 0)
        retry["tokens_cached"] = (result.get("tokens_cached") or 0) + (retry.get("tokens_cached") or 0)
        return retry, 1
    return result, 0


def _result_cost(result: dict) -> float:
    """api.analysis_routes._result_cost와 동형(R7-3: 재시도 비용 이중계산 방지)."""
    from services.pricing import calc_cost

    prior_total = result.get("cost_usd_prior_attempts")
    if prior_total is not None:
        return prior_total
    return calc_cost(result["model"], result["tokens_in"], result["tokens_out"])


async def run_one(
    stage: str,
    provider: str,
    meta: dict,
    phase_inputs: dict,
    sections: dict,
    *,
    pdf_uri: str | None,
    doc_text: str,
    effort_override: str | None,
) -> dict | None:
    """스테이지 하나를 한 provider로 실행하고 record를 돌려준다.

    citation이 top_cited 없이 로컬 파싱만으로 끝나는 경우(LLM 미호출)는
    None을 돌려준다 — 비교할 LLM 출력이 없기 때문이다(_run_citation과 동형).
    """
    from services.model_registry import resolve as resolve_model

    choice = resolve_model(stage, provider)
    effort = effort_override if effort_override is not None else choice.effort

    built = build_prompt(stage, meta, phase_inputs, sections)
    prompt, schema, _local = built
    if prompt is None:
        print(f"[{stage}/{provider}] SKIP: citation LLM 호출 대상 없음(top_cited=0)")
        return None

    if stage in ("visual", "recipe", "deep_dive"):
        if provider == "gemini":
            if pdf_uri is None:
                print(f"[{stage}/{provider}] SKIP: PDF 업로드 실패로 문서 입력 없음")
                return None
            contents = [
                {"type": "document", "uri": pdf_uri, "mime_type": "application/pdf"},
                {"type": "text", "text": prompt},
            ]
        else:
            from api.analysis_routes import _OPENAI_DOC_TEXT_CHAR_LIMIT

            if len(doc_text) >= _OPENAI_DOC_TEXT_CHAR_LIMIT:
                doc_label = f"[논문 본문({_OPENAI_DOC_TEXT_CHAR_LIMIT:,}자 절단)]"
            else:
                doc_label = "[논문 전문]"
            contents = f"{doc_label}\n{doc_text}\n\n{prompt}"
    else:
        contents = prompt

    print(f"[{stage}/{provider}] model={choice.model} effort={effort} ... ", end="", flush=True)
    started = time.time()
    try:
        if stage == "citation":
            from services.llm.interactions_client import call_interaction

            result = await call_interaction(
                contents, lane="pipeline", model=choice.model, thinking_level=effort,
                response_schema=schema, store=False,
            )
            retries = 0
        else:
            result, retries = await call_stage_with_retry(
                contents, model=choice.model, effort=effort, schema=schema,
            )
    except Exception as exc:  # noqa: BLE001 - 한쪽이 실패해도 다른 쪽은 계속
        elapsed = time.time() - started
        print(f"FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
        return {
            "stage": stage,
            "provider": provider,
            "model": choice.model,
            "effort": effort,
            "error": f"{type(exc).__name__}: {exc}",
            "latency_s": round(elapsed, 1),
        }
    elapsed = time.time() - started

    from api.analysis_helpers import _stage_result_defect

    cost = _result_cost(result)
    record = {
        "stage": stage,
        "provider": provider,
        "model": result["model"],
        "effort": effort,
        "tokens_in": result["tokens_in"],
        "tokens_out": result["tokens_out"],
        "reasoning_tokens": result.get("tokens_thought", 0),
        "cached_tokens": result.get("tokens_cached", 0),
        "defect_retries": retries,
        # 추가 신호(스펙 필드 밖, 정보용): 재시도 후에도 여전히 결함인지.
        # api.analysis_helpers._stage_result_defect — _run_screening/
        # _run_chain_stage가 재시도 게이트로 실제 쓰는 함수(JSON 파싱
        # 실패·반복 루프 오염 감지). None이 아니면 결함이 발화한 것이다.
        "defect_final": _stage_result_defect(result.get("text") or "") is not None,
        "latency_s": round(elapsed, 1),
        "cost_usd": round(cost, 6),
    }
    out = OUT_DIR / f"{stage}__{provider}__{effort}.json"
    out.write_text(
        json.dumps({**record, "text": result.get("text", "")}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"{record['latency_s']}s  in={record['tokens_in']} out={record['tokens_out']} "
        f"reasoning={record['reasoning_tokens']} cached={record['cached_tokens']} "
        f"retries={record['defect_retries']} ${record['cost_usd']}"
    )
    return record


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="GPT-5.6 Luna vs 프로덕션 Gemini 5단계 비교 + 품질·비용 신호 기록(R9).",
    )
    ap.add_argument("--paper-id", type=int, default=DEFAULT_PAPER_ID, help="비교에 쓸 논문 ID")
    ap.add_argument(
        "--stages",
        default=",".join(STAGE_ROLES),
        help=f"비교할 단계(콤마 구분). 선택지: {','.join(STAGE_ROLES)}",
    )
    ap.add_argument(
        "--providers",
        default=",".join(PROVIDERS),
        help=f"비교할 provider(콤마 구분). 선택지: {','.join(PROVIDERS)}",
    )
    ap.add_argument(
        "--role",
        default=None,
        help="effort 비교 모드: 이 단계 하나만 --efforts 목록으로 반복 실행(레지스트리 모델은 유지, effort만 오버라이드)",
    )
    ap.add_argument(
        "--efforts",
        default=None,
        help="effort 비교 모드: 콤마 구분 effort 목록(예: high,xhigh). --role과 함께 써야 한다",
    )
    return ap


def parse_args(argv: list[str] | None = None):
    """CLI 인자를 파싱·검증한다. 순수 로직 — I/O 없음(단위 테스트 대상).

    Returns:
        (args, stages, providers, effort_compare, efforts) 튜플. 잘못된 조합은
        argparse 관례대로 SystemExit(2)로 죽는다.
    """
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if bool(args.role) != bool(args.efforts):
        ap.error("--role과 --efforts는 함께 지정해야 한다")

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    for s in stages:
        if s not in STAGE_ROLES:
            ap.error(f"unknown stage: {s!r} (선택지: {','.join(STAGE_ROLES)})")

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    for p in providers:
        if p not in PROVIDERS:
            ap.error(f"unknown provider: {p!r} (선택지: {','.join(PROVIDERS)})")

    effort_compare = args.role is not None
    if effort_compare:
        if args.role not in STAGE_ROLES:
            ap.error(f"unknown --role: {args.role!r} (선택지: {','.join(STAGE_ROLES)})")
        stages = [args.role]
        efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]
    else:
        efforts = [None]  # 레지스트리 effort를 그대로 쓴다는 표식

    return args, stages, providers, effort_compare, efforts


async def main_async() -> None:
    args, stages, providers, effort_compare, efforts = parse_args()

    keys = load_keys()
    needed = {p for p in providers}
    missing = [p for p in needed if not keys.get(p)]
    if missing:
        raise SystemExit(f"missing API keys: {', '.join(missing)}")
    # 아래로는 services.llm.* 클라이언트가 os.environ에서 키를 읽는다(프로덕션과
    # 동일 경로) — load_keys()가 설정 DB에서 복호화한 값도 여기서 프로세스
    # 환경에 반영한다. 파일에는 쓰지 않는다.
    if keys.get("openai"):
        os.environ["OPENAI_API_KEY"] = keys["openai"]
    if keys.get("gemini"):
        os.environ["GEMINI_API_KEY"] = keys["gemini"]

    pdf, meta = load_paper(args.paper_id)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"paper {meta['paper_id']}: {meta['title'][:60]}")
    print(f"  pdf={pdf.name}  figures={len(meta['figures'])} tables={len(meta['tables'])}\n")

    from services.document_context import build_document_context_from_text
    from services.odl_parser import ensure_text_artifacts

    manifest = ensure_text_artifacts(Path(meta["folder"]))
    full_text = str(manifest.get("full_text") or "")
    if not full_text:
        raise SystemExit(f"paper {args.paper_id}: full_text 추출 실패")
    doc_ctx = build_document_context_from_text(full_text)
    phase_inputs = doc_ctx["phase_inputs"]
    sections = doc_ctx["sections"]

    from api.analysis_routes import _OPENAI_DOC_TEXT_CHAR_LIMIT

    doc_text = full_text[:_OPENAI_DOC_TEXT_CHAR_LIMIT]

    pdf_uri: str | None = None
    needs_pdf = any(s in ("visual", "recipe", "deep_dive") for s in stages)
    if needs_pdf and "gemini" in providers:
        try:
            print("gemini PDF 업로드 중...", end=" ", flush=True)
            pdf_uri = upload_pdf_gemini(pdf, keys["gemini"])
            print("done")
        except Exception as exc:  # noqa: BLE001 - visual/recipe/deep_dive의 gemini leg만 스킵
            print(f"FAILED: {exc}")

    summary: list[dict] = []
    for stage in stages:
        for provider in providers:
            for effort_override in efforts:
                record = await run_one(
                    stage, provider, meta, phase_inputs, sections,
                    pdf_uri=pdf_uri, doc_text=doc_text, effort_override=effort_override,
                )
                if record is not None:
                    summary.append(record)

    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "paper": {k: v for k, v in meta.items() if k not in ("figures", "tables")},
                "effort_compare": {"role": args.role, "efforts": efforts} if effort_compare else None,
                "runs": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsaved to {OUT_DIR}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
