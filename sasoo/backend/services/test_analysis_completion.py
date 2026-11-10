"""Frozen output fixtures. No provider calls, source changes, or paid retries."""

import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from services.analysis_completion import build_completion_checks, check_stage_output, completion_progress


def complete_rows():
    outputs = {
        "screening": {"domain": "ai_ml", "summary": "분류 요약", "key_topics": [],
                      "relevance_score": 0.5, "is_experimental": False, "methodology_type": "theoretical",
                      "recipe_applicable": True, "deep_dive_applicable": True},
        "citation": {"total_references": 0, "top_cited": [], "citation_distribution": {}},
        "visual": {"quality_summary": "시각 자료 검토", "key_findings_from_visuals": [], "visual_ready": True},
        "recipe": {"title": "절차", "objective": "목표", "steps": [], "parameters": []},
        "deep_dive": {"problem_definition": "문제", "method_summary": "방법", "key_results": "결과",
                      "solution": "해결", "strengths": [], "weaknesses": [], "comparison_scope": "in_paper_only",
                      "novelty_assessment": "평가", "comparison_to_prior_work": "비교",
                      "suggested_improvements": [], "follow_up_questions": [], "practical_applications": [],
                      "section_answers": [], "transfer_checks": []},
        "synthesis": {"problem_sentence": "문제", "method_sentence": "방법", "key_metrics": [],
                      "equations": [], "result_figures": [], "key_parameters": [], "equation_count": 0},
        "visualization": {"complete": True, "items": [], "planned_empty": True, "planned_items": []},
    }
    return {stage: {"id": index, "phase": stage, "model_used": "fixture", "result": json.dumps(data)}
            for index, (stage, data) in enumerate(outputs.items(), 1)}


def test_all_deliverables_and_intentionally_empty_outputs_complete():
    rows = complete_rows()
    original = deepcopy(rows)
    checks = build_completion_checks(rows)
    assert len(checks) == 7 and all(check["status"] == "completed" for check in checks)
    assert completion_progress(checks) == 100
    assert rows == original


@pytest.mark.parametrize("raw", ['{', '[]', 'null', '"text"', '{"a":1,"a":2}', ''])
def test_malformed_output_is_not_complete(raw):
    assert check_stage_output("recipe", {"result": raw})["status"] == "error"


@pytest.mark.parametrize("stage,patch_data,expected", [
    ("recipe", {"objective": None}, "partial"),
    ("recipe", {"_partial": "복구한 일부 결과"}, "partial"),
    ("recipe", {"response_status": "incomplete"}, "partial"),
    ("recipe", {"response_status": []}, "partial"),
    ("recipe", {"_input_coverage": {"status": "partial"}}, "partial"),
    ("recipe", {"_parse_error": "truncated", "_raw": "preserved"}, "error"),
    ("visual", {"artifacts_partial": True, "visual_ready": False}, "partial"),
    ("deep_dive", {"section_answers": [{"answer": "missing refs"}]}, "partial"),
    ("visualization", {"complete": False}, "partial"),
    ("visualization", {"planned_empty": False}, "partial"),
    ("visualization", {"items": [{"status": "error"}]}, "partial"),
    ("visualization", {"items": [{"status": "completed", "tool": ["html"]}]}, "partial"),
    ("visualization", {"items": [{"status": "completed", "tool": "html", "html_code": "<p>result</p>",
                                     "execution_check": {"status": "failed"}}]}, "partial"),
])
def test_partial_and_failed_fixtures_keep_their_data(stage, patch_data, expected):
    row = complete_rows()[stage]
    row["result"] = json.dumps({**json.loads(row["result"]), **patch_data})
    original = deepcopy(row)
    assert check_stage_output(stage, row)["status"] == expected
    assert row == original


def test_missing_image_and_failed_newest_row_never_fall_back_to_success():
    row = {"result": json.dumps({"complete": True, "items": [
        {"id": 1, "tool": "paperbanana", "status": "completed", "image_path": "/missing.png"},
    ]})}
    assert check_stage_output("visualization", row, item_available=lambda _: False)["status"] == "partial"
    rows = complete_rows()
    rows["recipe"] = {"id": 99, "result": '{"error":"new failure"}'}
    assert build_completion_checks(rows)[3]["status"] == "error"
    assert completion_progress(build_completion_checks(rows)) < 100


@pytest.mark.parametrize("stage,patch_data", [
    ("recipe", {"parameters": ["invalid"]}),
    ("recipe", {"parameters": [{"name": "temperature", "value": "5", "source_tag": "invalid"}]}),
    ("recipe", {"parameters": [{"name": "temperature", "source_tag": "explicit"}]}),
    ("recipe", {"steps": [42]}),
    ("screening", {"domain": "unknown"}),
    ("screening", {"relevance_score": 2}),
    ("visual", {"key_findings_from_visuals": [42]}),
    ("synthesis", {"key_metrics": [{"label": "accuracy"}]}),
])
def test_nested_values_and_schema_constraints_are_not_complete(stage, patch_data):
    row = complete_rows()[stage]
    row["result"] = json.dumps({**json.loads(row["result"]), **patch_data})
    assert check_stage_output(stage, row)["status"] == "partial"


@pytest.mark.parametrize("stage,field", [
    ("screening", "relevance_score"),
    ("recipe", "steps"),
    ("deep_dive", "solution"),
    ("synthesis", "equation_count"),
])
def test_provider_required_fields_are_not_complete_when_missing(stage, field):
    row = complete_rows()[stage]
    payload = json.loads(row["result"])
    del payload[field]
    row["result"] = json.dumps(payload)
    assert check_stage_output(stage, row)["status"] == "partial"


def test_only_explicit_system_gate_skips_optional_downstream_stages():
    rows = complete_rows()
    for stage in ("recipe", "deep_dive"):
        rows[stage] = {"model_used": "system", "result": '{"skipped":true,"reason":"not applicable"}'}
    checks = build_completion_checks(rows)
    assert [check["status"] for check in checks[3:]] == ["skipped"] * 4
    assert all(check["result_id"] is None for check in checks[5:])
    rows["recipe"]["model_used"] = "llm"
    assert build_completion_checks(rows)[3]["status"] == "partial"


def test_new_failed_plan_does_not_complete_using_an_old_visualization():
    rows = complete_rows()
    rows["viz_plan"] = {"id": 99, "result": '{"_parse_error":"planning failed"}'}
    check = build_completion_checks(rows)[6]
    assert check["status"] == "partial" and check["result_id"] == rows["visualization"]["id"]
    assert "이전에 저장한 결과" in check["reason"]
    rows.pop("visualization")
    assert build_completion_checks(rows)[6]["status"] == "error"


def test_saved_and_live_status_share_completion_and_keep_cancellation():
    asyncio.run(_check_saved_and_live_status())


async def _check_saved_and_live_status():
    from api import analysis_routes as routes
    from models.schemas import AnalysisStatus
    rows = complete_rows()
    del rows["synthesis"]
    with patch.object(routes, "active_provider", new=AsyncMock(return_value=None)), \
         patch.object(routes, "_subprocess_mode", return_value=False), \
         patch.dict(routes._running_analyses, {}, clear=True):
        restored = await routes._build_analysis_status(7, {"status": "completed"}, rows)
        assert restored.overall_status == "error" and restored.progress_pct < 100
        live = AnalysisStatus(paper_id=7, overall_status="completed", progress_pct=100)
        with patch.dict(routes._running_analyses, {7: live}):
            observed = await routes._build_analysis_status(7, {"status": "completed"}, rows)
            assert observed.completion_checks == restored.completion_checks
            assert observed.overall_status == "error"
            live.overall_status = "cancelled"
            assert (await routes._build_analysis_status(7, {"status": "completed"}, rows)).overall_status == "cancelled"


def test_salvaged_chain_output_keeps_partial_marker_without_an_extra_call():
    from services import analysis_execution as ae
    payload = {"title": "T", "objective": "O", "parameters": ["p"], "steps": ["s"]}
    raw = json.dumps(payload)[:-1] + ', "tail": "truncated'
    schema = {"type": "object", "required": list(payload), "properties": {
        "title": {"type": "string"}, "objective": {"type": "string"},
        "parameters": {"type": "array"}, "steps": {"type": "array"},
    }}
    call = AsyncMock(return_value={"text": raw, "model": "fixture", "tokens_in": 10, "tokens_out": 20})
    with patch.object(ae, "call_interaction", new=call):
        output = asyncio.run(ae._run_chain_stage(
            phase="recipe", prompt_chain="prompt", prompt_fallback="prompt", system_instruction="",
            previous_interaction_id=None, pdf_uri=None, response_schema=schema, provider="openai",
        ))
    call.assert_awaited_once()
    assert output["raw_text"] == raw
    assert check_stage_output("recipe", {"result": output["text"]})["status"] == "partial"
    assert output["tokens_out"] == 20


@pytest.mark.parametrize("raw", [
    "{broken", '{}',
    json.dumps({"ref_analyses": ["invalid"], "summary": "summary", "citation_balance": "balanced"}),
    json.dumps({"ref_analyses": [{"ref_id": "[1]", "citation_role": "invalid", "why_cited": "reason"}],
                "summary": "summary", "citation_balance": "balanced"}),
    json.dumps({"ref_analyses": [{"ref_id": "[1]", "citation_role": "supporting"}],
                "summary": "summary", "citation_balance": "balanced"}),
])
def test_citation_invalid_llm_json_preserves_local_stats_but_fails(raw):
    from types import SimpleNamespace
    from models.schemas import AnalysisStatus
    from services import analysis_execution as ae, citation_analyzer

    local = {"total_references": 1, "top_cited": [{"ref_id": "[1]"}], "citation_distribution": {"Methods": 1}}
    response = {"text": raw, "model": "fixture", "tokens_in": 2, "tokens_out": 3}
    status = AnalysisStatus(paper_id=1)
    with patch.object(citation_analyzer, "analyze_citations", return_value=SimpleNamespace(to_dict=lambda: deepcopy(local))), \
         patch.object(ae, "_select_citation_top_refs", return_value=local["top_cited"]), \
         patch.object(ae, "_get_cached_phase_result", new=AsyncMock(return_value=None)), \
         patch.object(ae, "_insert_analysis_result", new=AsyncMock()), \
         patch.object(ae, "call_interaction", new=AsyncMock(return_value=response)), \
         patch.object(ae, "calc_result_cost", return_value=0.01):
        output = asyncio.run(ae._run_citation(1, {}, "body", "refs", "", status))
    saved = json.loads(output["text"])
    assert saved["total_references"] == 1 and saved["_raw"] == raw
    assert saved["interpretation_status"] == "failed"
    assert status.phases[-1].status == "error"
    assert check_stage_output("citation", {"result": output["text"]})["status"] == "error"


def test_citation_legacy_interpretation_is_reported_unknown_without_losing_completion():
    row = complete_rows()["citation"]
    check = check_stage_output("citation", row)
    assert check["status"] == "completed"
    assert "요청 여부" in check["reason"]


def test_citation_cache_uses_completion_check_and_keeps_legacy_rows():
    from services.document_context import find_cached_phase_result

    async def lookup(payload):
        row = {"id": 1, "result": json.dumps(payload), "input_hash": "hash"}
        with patch("services.document_context.fetch_one", new=AsyncMock(return_value=row)):
            return await find_cached_phase_result(1, "citation", "input")

    legacy = json.loads(complete_rows()["citation"]["result"])
    assert asyncio.run(lookup(legacy)) is not None
    assert asyncio.run(lookup({**legacy, "interpretation_status": "completed"})) is None
    assert asyncio.run(lookup({**legacy, "interpretation_status": "failed"})) is None


@pytest.mark.parametrize("stage", ["screening", "visual", "recipe", "deep_dive", "synthesis"])
def test_ordinary_cache_hits_follow_the_saved_completion_contract(stage):
    from types import SimpleNamespace
    from services import analysis_execution as ae

    row = complete_rows()[stage]
    payload = json.loads(row["result"])
    payload["_partial"] = "incomplete"
    cached = SimpleNamespace(result_id=1, result_text=json.dumps(payload), model_used="fixture", input_hash="hash",
                             cost_usd=0, tokens_in=0, tokens_out=0)
    with patch.object(ae, "find_cached_phase_result", new=AsyncMock(return_value=cached)), \
         patch.object(ae, "execute_insert", new=AsyncMock()) as insert:
        assert asyncio.run(ae._get_cached_phase_result(1, stage, "input")) is None
        insert.assert_not_awaited()
        payload.pop("_partial")
        cached.result_text = json.dumps(payload)
        assert asyncio.run(ae._get_cached_phase_result(1, stage, "input")) is not None


def test_unknown_cached_cost_is_not_written_as_zero():
    from types import SimpleNamespace
    from services import analysis_execution as ae

    cached = SimpleNamespace(result_id=1, result_text=complete_rows()["recipe"]["result"], model_used="fixture",
                             input_hash="hash", cost_usd=None, tokens_in=0, tokens_out=0)
    with patch.object(ae, "find_cached_phase_result", new=AsyncMock(return_value=cached)), \
         patch.object(ae, "execute_insert", new=AsyncMock()) as insert:
        result = asyncio.run(ae._get_cached_phase_result(1, "recipe", "input"))
    assert result["cost_usd"] is None
    assert insert.await_args.args[1][4] is None


def test_citation_local_only_records_no_interpretation_request():
    from types import SimpleNamespace
    from models.schemas import AnalysisStatus
    from services import analysis_execution as ae, citation_analyzer

    local = {"total_references": 0, "top_cited": [], "citation_distribution": {}}
    with patch.object(citation_analyzer, "analyze_citations", return_value=SimpleNamespace(to_dict=lambda: deepcopy(local))), \
         patch.object(ae, "_select_citation_top_refs", return_value=[]), \
         patch.object(ae, "_get_cached_phase_result", new=AsyncMock(return_value=None)), \
         patch.object(ae, "_insert_analysis_result", new=AsyncMock()), \
         patch.object(ae, "call_interaction", new=AsyncMock()) as call:
        output = asyncio.run(ae._run_citation(1, {}, "body", "refs", "", AnalysisStatus(paper_id=1)))
    assert json.loads(output["text"])["interpretation_status"] == "local_only"
    call.assert_not_awaited()


def test_visualization_requires_every_planned_id_and_tool():
    payload = {"complete": True, "planned_items": [{"id": 1, "tool": "mermaid"}, {"id": 2, "tool": "html"}],
               "items": [{"id": 1, "tool": "mermaid", "status": "completed", "mermaid_code": "graph TD; A-->B"}]}
    row = {"result": json.dumps(payload)}
    assert check_stage_output("visualization", row)["status"] == "partial"
    payload["items"].append({"id": 2, "tool": "html", "status": "completed", "html_code": "<p>ok</p>"})
    row["result"] = json.dumps(payload)
    assert check_stage_output("visualization", row)["status"] == "completed"
    payload["items"][1]["tool"] = "mermaid"
    row["result"] = json.dumps(payload)
    assert check_stage_output("visualization", row)["status"] == "partial"


@pytest.mark.parametrize("items", [
    [{"id": 1, "tool": "mermaid"}, {"id": 1, "tool": "mermaid"}],
    [{"id": 1, "tool": "html"}],
    [{"id": 1, "tool": "mermaid"}, {"id": 2, "tool": "html"}],
    [],
])
def test_visualization_plan_rejects_duplicate_wrong_extra_or_missing(items):
    from services.analysis_completion import visualization_plan_matches
    assert not visualization_plan_matches({"planned_items": [{"id": 1, "tool": "mermaid"}], "items": items})


def test_legacy_visualization_plan_is_not_invented():
    row = {"result": json.dumps({"items": [{"id": 1, "tool": "mermaid", "status": "completed",
                                            "mermaid_code": "graph TD; A-->B"}]})}
    check = check_stage_output("visualization", row)
    assert check["status"] == "partial"
    assert "계획" in check["reason"] and "확인할 수 없습니다" in check["reason"]
    assert check_stage_output("visualization", row, allow_legacy_plan_reuse=True)["status"] == "completed"
