"""Run shipped Python stage functions with canned provider responses and record
the wire requests and the analysis_results row each stage would store.

No network and no DB writes: both SDK transports are intercepted, and the DB
helpers the stages call are replaced by recorders.

Usage: backend/.venv/bin/python -I tests/stage_oracle.py <backend_dir> <out_json>
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ["GEMINI_API_KEY"] = "fixture-gemini-key"
os.environ["OPENAI_API_KEY"] = "fixture-openai-key"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
time.sleep = lambda _s: None

import httpx  # noqa: E402

KEPT = {"content-type"}
SECRET = {"authorization", "x-goog-api-key"}
seen: list[dict] = []
queue: list[dict] = []


def _record(request) -> dict:
    body = request.read()
    headers = {k.lower(): ("<redacted>" if k.lower() in SECRET else v)
               for k, v in request.headers.items() if k.lower() in KEPT | SECRET}
    seen.append({"method": request.method, "url": str(request.url), "headers": headers,
                 "body_json": json.loads(body) if body else None})
    if not queue:
        raise AssertionError("unexpected provider request")
    return queue.pop(0)


def _handler(self, request):
    r = _record(request)
    return httpx.Response(r["status"], content=r["body"].encode(), headers={"content-type": "application/json"}, request=request)


httpx.HTTPTransport.handle_request = _handler
try:
    import httpx2

    def _handler2(self, request):
        r = _record(request)
        return httpx2.Response(r["status"], content=r["body"].encode(), headers={"content-type": "application/json"}, request=request)

    httpx2.HTTPTransport.handle_request = _handler2
except ImportError:
    pass


def openai_body(text, *, status="completed", usage=True):
    body = {"id": "resp_stage", "object": "response", "created_at": 1, "status": status, "model": "gpt-6-luna",
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "output": [{"type": "message", "id": "m", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}]}
    if usage:
        body["usage"] = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
                         "input_tokens_details": {"cached_tokens": 100, "cache_write_tokens": 0},
                         "output_tokens_details": {"reasoning_tokens": 50}}
    return json.dumps(body, ensure_ascii=False)


def gemini_body(text, *, status="completed", usage=True):
    body = {"id": "int_stage", "status": status, "model": "gemini",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]}
    if usage:
        body["usage"] = {"total_input_tokens": 1000, "total_output_tokens": 150, "total_thought_tokens": 50}
    return json.dumps(body, ensure_ascii=False)


SCREEN_OK = json.dumps({"domain": "optics", "agent_recommended": "photon", "relevance_score": 0.9,
                        "recipe_applicable": True, "deep_dive_applicable": True, "applicability_reason": "근거",
                        "key_topics": ["FSO", "AO"], "methodology_type": "experimental", "paper_type": "article",
                        "summary": "요약입니다.", "is_experimental": True, "has_figures": True,
                        "estimated_complexity": "medium", "confidence": 0.8}, ensure_ascii=False)
SCREEN_TRUNC = SCREEN_OK[: SCREEN_OK.index('"has_figures"') + 5]
SCREEN_TRUNC_REQUIRED = SCREEN_OK[: SCREEN_OK.index('"summary"') + 14]
SCREENING_INPUT = "Title: Adaptive optics for FSO\n\nAbstract\nWe correct turbulence with a 97-actuator mirror. 한국어 문장도 있다."


def screening_cases():
    out = []
    for provider, body in (("gemini", gemini_body), ("openai", openai_body)):
        out += [
            {"name": f"screening_{provider}_ok", "responses": [body(SCREEN_OK)]},
            {"name": f"screening_{provider}_fenced", "responses": [body("```json\n" + SCREEN_OK + "\n```")]},
            {"name": f"screening_{provider}_truncated_salvaged", "responses": [body(SCREEN_TRUNC)]},
            {"name": f"screening_{provider}_truncated_required_then_ok", "responses": [body(SCREEN_TRUNC_REQUIRED), body(SCREEN_OK)]},
            {"name": f"screening_{provider}_invalid_then_ok", "responses": [body("not json"), body(SCREEN_OK)]},
            {"name": f"screening_{provider}_incomplete", "responses": [body(SCREEN_OK, status="incomplete")]},
            {"name": f"screening_{provider}_usage_missing", "responses": [body(SCREEN_OK, usage=False)]},
            {"name": f"screening_{provider}_invalid_then_incomplete", "responses": [body("{bad"), body("{bad", status="incomplete")]},
        ]
        for c in out[-8:]:
            c["provider"] = provider
            c["screening_input"] = SCREENING_INPUT
    return out


FIGURES = [{"figure_num": "Fig. 1", "quality": "high", "confidence": 0.95, "resolver_version": "r3"},
           {"figure_num": "Fig. 2", "quality": "low", "confidence": None, "resolver_version": "r3"}]
TABLES = [{"table_num": "Table 1", "confidence": 1.0, "parse_method": "vlm", "resolver_version": "t2"}]
READY = {"visual_state": "ready", "visual_ready": True, "visual_error": None, "artifacts_ready": True, "artifacts_error": None}
NOT_READY = {"visual_state": "pending", "visual_ready": False, "visual_error": "추출 대기", "artifacts_ready": False, "artifacts_error": None}
VISUAL_OK = json.dumps({"figure_count": 3, "tables_found": 1, "equations_found": 2, "diagram_types": ["graph"],
                        "quality_summary": "양호", "key_findings_from_visuals": ["Fig. 1: 수렴"]}, ensure_ascii=False)
VISUAL_INPUT = "Figure 1 shows convergence. Table 1 lists parameters."


def visual_cases(fixture_dir):
    out = []
    for provider, body in (("gemini", gemini_body), ("openai", openai_body)):
        source = ({"pdf_uri": "https://generativelanguage.googleapis.com/v1beta/files/abc", "pdf_sha256": "ab" * 32}
                  if provider == "gemini" else {"openai_pdf": "tiny.pdf"})
        out += [
            {"name": f"visual_{provider}_not_ready_partial", "snapshot": [NOT_READY, FIGURES, TABLES], "source": source, "responses": [] if provider == "gemini" else [body(VISUAL_OK)]},
            {"name": f"visual_{provider}_ready_but_empty", "snapshot": [READY, [], []], "source": {}, "responses": []},
            {"name": f"visual_{provider}_pdf_chain_start", "snapshot": [READY, FIGURES, TABLES], "source": source, "responses": [body(VISUAL_OK)],
             "system_instruction": "페르소나 지시"},
            {"name": f"visual_{provider}_fallback_no_source", "snapshot": [READY, FIGURES, TABLES], "source": {}, "responses": [body(VISUAL_OK)]},
            {"name": f"visual_{provider}_invalid_then_ok", "snapshot": [READY, FIGURES, TABLES], "source": source, "responses": [body("oops"), body(VISUAL_OK)]},
            {"name": f"visual_{provider}_truncated_salvaged", "snapshot": [READY, FIGURES, TABLES], "source": source, "responses": [body(VISUAL_OK[:-30]), body(VISUAL_OK)]},
        ]
        for c in out[-6:]:
            c["provider"] = provider
            c["visual_input"] = VISUAL_INPUT
    out.append({"name": "visual_openai_doc_text", "provider": "openai", "snapshot": [READY, FIGURES, TABLES],
                "source": {"doc_text": "본문 전문 " * 10}, "responses": [openai_body(VISUAL_OK)], "visual_input": VISUAL_INPUT})
    return out


RECIPE_OK = json.dumps({"title": "레시피", "objective": "목적", "materials": [], "equipment": [],
                        "parameters": [{"name": "wavelength", "value": "1550", "unit": "nm", "notes": "Methods",
                                        "source_tag": "explicit", "evidence_quote": "1550 nm", "evidence_page": 2}],
                        "steps": ["정렬"], "critical_notes": [], "expected_results": "결과", "safety_notes": [],
                        "confidence": 0.7, "missing_info": [], "reproducibility_score": 0.6}, ensure_ascii=False)


def screening_text(**over):
    base = json.loads(SCREEN_OK)
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


def recipe_cases():
    out = []
    for provider, body in (("gemini", gemini_body), ("openai", openai_body)):
        source = ({"pdf_uri": "https://generativelanguage.googleapis.com/v1beta/files/abc", "pdf_sha256": "ab" * 32}
                  if provider == "gemini" else {"openai_pdf": "tiny.pdf"})
        base = {"provider": provider, "recipe_input": "Methods: 1550 nm laser, 10 mW.", "source": source,
                "citation_text": '{"total_references": 3}', "visual_text": VISUAL_OK, "previous_id": None}
        out += [
            {**base, "name": f"recipe_{provider}_skip_low_relevance", "screening": screening_text(relevance_score=0.2), "responses": []},
            {**base, "name": f"recipe_{provider}_skip_review", "screening": screening_text(paper_type="review", recipe_applicable=False, confidence=0.9), "responses": []},
            {**base, "name": f"recipe_{provider}_skip_not_applicable", "screening": screening_text(recipe_applicable=False, confidence=0.9), "responses": []},
            {**base, "name": f"recipe_{provider}_chain_restart_optics", "screening": screening_text(), "responses": [body(RECIPE_OK)]},
            {**base, "name": f"recipe_{provider}_chain_continue", "screening": screening_text(domain="bio"), "previous_id": "prev_visual", "responses": [body(RECIPE_OK)]},
            {**base, "name": f"recipe_{provider}_fallback_ai", "screening": screening_text(domain="ai_ml"), "source": {}, "responses": [body(RECIPE_OK)]},
            {**base, "name": f"recipe_{provider}_ee_error_visual", "screening": screening_text(domain="ee"), "visual_text": '{"_raw": "x", "_parse_error": "y"}', "responses": [body(RECIPE_OK)]},
            {**base, "name": f"recipe_{provider}_general_retry", "screening": screening_text(domain="general"), "responses": [body("nope"), body(RECIPE_OK)]},
            {**base, "name": f"recipe_{provider}_invalid_screening", "screening": "not json", "responses": [body(RECIPE_OK)]},
        ]
    return out


async def run_recipe_case(ae, models, case, fixture_dir) -> dict:
    from services.llm.openai_client import load_pdf_part
    from services.model_registry import resolve
    rows: list[dict] = []
    install_recorders(ae, rows)

    async def no_evidence(**_k):
        return None

    ae._ensure_recipe_evidence = no_evidence
    seen.clear()
    queue[:] = [{"status": 200, "body": b} for b in case["responses"]]
    src = case["source"]
    previous = [t for t in (case["screening"], case["citation_text"], case["visual_text"]) if t and not ae._is_error_result(t)]
    kwargs = {"provider": case["provider"], "screening_result_text": case["screening"], "previous_results": previous,
              "previous_interaction_id": case["previous_id"], "folder_name": "fixture"}
    if "pdf_uri" in src:
        kwargs.update(pdf_uri=src["pdf_uri"], pdf_sha256=src["pdf_sha256"])
    if "openai_pdf" in src:
        kwargs["openai_pdf_part"] = load_pdf_part(fixture_dir / src["openai_pdf"])
    error = None
    try:
        await ae._run_recipe(1, case["recipe_input"], models.AnalysisStatus(paper_id=1), **kwargs)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    choice = resolve("recipe", case["provider"])
    return {**case, "choice": {"model": choice.model, "effort": choice.effort},
            "requests": list(seen), "unused_responses": len(queue), "rows": rows, "error": error}


SECTION = {"section_title": "Method", "question": "무엇을?", "answer": "보정", "explanation": "설명", "source_refs": ["Fig. 1"]}
TRANSFER = {"item": "파장", "paper_condition": "1550 nm", "condition_basis": "reported", "check_before_transfer": "확인", "source_refs": ["Sec. 2"]}
DEEP_OK = json.dumps({"problem_definition": "문제", "method_summary": "방법", "key_results": "결과",
                      "section_answers": [SECTION], "transfer_checks": [TRANSFER]}, ensure_ascii=False)
DEEP_MISSING = json.dumps({"problem_definition": "문제", "method_summary": "방법", "key_results": "결과"}, ensure_ascii=False)
DEEP_DUP = '{"problem_definition": "a", "problem_definition": "b", "section_answers": [], "transfer_checks": []}'
REVIEW_OK = json.dumps({"field_overview": "개관", "parts": [{"title": "1부", "summary": "요약"}],
                        "future_directions": ["방향"], "reading_paths": []}, ensure_ascii=False)
REVIEW_EMPTY = json.dumps({"field_overview": "개관", "parts": [], "future_directions": [], "reading_paths": []}, ensure_ascii=False)
CITATION_OK = json.dumps({"total_references": 42, "citation_balance": "균형", "key_influences": ["Kolmogorov", 1941],
                          "summary": "인용 요약"}, ensure_ascii=False)


def deep_cases():
    out = []
    for provider, body in (("gemini", gemini_body), ("openai", openai_body)):
        source = ({"pdf_uri": "https://generativelanguage.googleapis.com/v1beta/files/abc", "pdf_sha256": "ab" * 32}
                  if provider == "gemini" else {"openai_pdf": "tiny.pdf"})
        base = {"provider": provider, "deep_dive_input": "Results: BER 1e-9 at 10 Gbps.", "source": source,
                "screening": screening_text(), "citation_text": CITATION_OK, "visual_text": VISUAL_OK,
                "recipe_text": RECIPE_OK, "previous_id": None}
        review = screening_text(paper_type="review")
        out += [
            {**base, "name": f"deep_{provider}_ok_restart", "responses": [body(DEEP_OK)]},
            {**base, "name": f"deep_{provider}_continue", "previous_id": "prev_recipe", "responses": [body(DEEP_OK)]},
            {**base, "name": f"deep_{provider}_fallback", "source": {}, "citation_text": "plain citation text", "responses": [body(DEEP_OK)]},
            {**base, "name": f"deep_{provider}_missing_fields", "responses": [body(DEEP_MISSING)]},
            {**base, "name": f"deep_{provider}_duplicate_key", "responses": [body(DEEP_DUP)]},
            {**base, "name": f"deep_{provider}_incomplete", "responses": [body(DEEP_OK, status="incomplete")]},
            {**base, "name": f"deep_{provider}_skip_low", "screening": screening_text(relevance_score=0.1), "responses": []},
            {**base, "name": f"deep_{provider}_review_map_ok", "screening": review, "previous_id": "prev_recipe", "responses": [body(REVIEW_OK)]},
            {**base, "name": f"deep_{provider}_review_map_empty", "screening": review, "responses": [body(REVIEW_EMPTY)]},
            {**base, "name": f"deep_{provider}_review_map_http_400", "screening": review,
             "responses": [{"status": 400, "body": json.dumps({"error": {"code": 400, "message": "bad"}})}]},
        ]
    return out


async def run_deep_case(ae, models, case, fixture_dir) -> dict:
    from services.llm.openai_client import load_pdf_part
    from services.model_registry import resolve
    rows: list[dict] = []
    install_recorders(ae, rows)
    seen.clear()
    queue[:] = [r if isinstance(r, dict) else {"status": 200, "body": r} for r in case["responses"]]
    src = case["source"]
    previous = [t for t in (case["screening"], case["citation_text"], case["visual_text"], case["recipe_text"])
                if t and not ae._is_error_result(t)]
    kwargs = {"provider": case["provider"], "screening_result_text": case["screening"],
              "citation_result_text": case["citation_text"], "previous_interaction_id": case["previous_id"]}
    if "pdf_uri" in src:
        kwargs.update(pdf_uri=src["pdf_uri"], pdf_sha256=src["pdf_sha256"])
    if "openai_pdf" in src:
        kwargs["openai_pdf_part"] = load_pdf_part(fixture_dir / src["openai_pdf"])
    error = None
    try:
        await ae._run_deep_dive(1, case["deep_dive_input"], previous, models.AnalysisStatus(paper_id=1), **kwargs)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    choice = resolve("deep_dive", case["provider"])
    return {**case, "choice": {"model": choice.model, "effort": choice.effort},
            "requests": list(seen), "unused_responses": len(queue), "rows": rows, "error": error}


def install_recorders(ae, rows):
    async def fake_insert(paper_id, phase, result_text, model_used, tokens_in, tokens_out, cost_usd, input_text,
                          interaction_id=None, *, provider=None, model=None, effort=None):
        rows.append({"phase": phase, "result": result_text, "model_used": model_used, "tokens_in": tokens_in,
                     "tokens_out": tokens_out, "cost_usd": cost_usd,
                     "input_hash": ae.compute_input_hash(input_text, provider=provider, model=model, effort=effort),
                     "interaction_id": interaction_id, "config_hash": ae._config_hash(provider, model, effort)})
        return len(rows)

    async def no_cache(*_a, **_k):
        return None

    ae._insert_analysis_result = fake_insert
    ae._get_cached_phase_result = no_cache


async def run_visual_case(ae, models, case, fixture_dir) -> dict:
    from services.llm.openai_client import load_pdf_part
    from services.model_registry import resolve
    rows: list[dict] = []
    install_recorders(ae, rows)
    ae.get_paper_dir = lambda _folder: fixture_dir
    seen.clear()
    queue[:] = [{"status": 200, "body": b} for b in case["responses"]]
    src = case["source"]
    kwargs = {"system_instruction": case.get("system_instruction", ""), "provider": case["provider"],
              "visual_snapshot": tuple(case["snapshot"])}
    if "pdf_uri" in src:
        kwargs.update(pdf_uri=src["pdf_uri"], pdf_sha256=src["pdf_sha256"])
    if "openai_pdf" in src:
        kwargs["openai_pdf_part"] = load_pdf_part(fixture_dir / src["openai_pdf"])
    if "doc_text" in src:
        kwargs["doc_text"] = src["doc_text"]
    error = None
    try:
        await ae._run_visual(1, case["visual_input"], "fixture", models.AnalysisStatus(paper_id=1), **kwargs)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    choice = resolve("visual", case["provider"])
    return {**case, "choice": {"model": choice.model, "effort": choice.effort},
            "requests": list(seen), "unused_responses": len(queue), "rows": rows, "error": error}


async def run_screening_case(ae, models, case) -> dict:
    from services.model_registry import resolve
    rows: list[dict] = []

    async def fake_insert(paper_id, phase, result_text, model_used, tokens_in, tokens_out, cost_usd, input_text,
                          interaction_id=None, *, provider=None, model=None, effort=None):
        rows.append({"phase": phase, "result": result_text, "model_used": model_used, "tokens_in": tokens_in,
                     "tokens_out": tokens_out, "cost_usd": cost_usd,
                     "input_hash": ae.compute_input_hash(input_text, provider=provider, model=model, effort=effort),
                     "interaction_id": interaction_id, "config_hash": ae._config_hash(provider, model, effort)})
        return len(rows)

    async def no_cache(*_a, **_k):
        return None

    ae._insert_analysis_result = fake_insert
    ae._get_cached_phase_result = no_cache
    seen.clear()
    queue[:] = [{"status": 200, "body": b} for b in case["responses"]]
    status = models.AnalysisStatus(paper_id=1)
    error = None
    try:
        await ae._run_screening(1, case["screening_input"], status, provider=case["provider"])
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    choice = resolve("screening", case["provider"])
    return {**case, "choice": {"model": choice.model, "effort": choice.effort},
            "requests": list(seen), "unused_responses": len(queue), "rows": rows, "error": error}


async def main():
    backend, out_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    sys.path.insert(0, str(backend))
    from models import schemas as models
    from services import analysis_execution as ae
    from services.llm import gemini_client, openai_client
    gemini_client._RETRY_DELAYS = [0, 0]
    openai_client._RETRY_DELAYS = [0, 0]
    cases = [await run_screening_case(ae, models, c) for c in screening_cases()]
    fixture_dir = out_path.parent.parent / "provider"
    visual = [await run_visual_case(ae, models, c, fixture_dir) for c in visual_cases(fixture_dir)]
    recipe = [await run_recipe_case(ae, models, c, fixture_dir) for c in recipe_cases()]
    deep = [await run_deep_case(ae, models, c, fixture_dir) for c in deep_cases()]
    out_path.write_text(json.dumps({"generator": "tests/stage_oracle.py", "screening": cases, "visual": visual, "recipe": recipe,
                                    "deep_dive": deep},
                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


asyncio.run(main())
