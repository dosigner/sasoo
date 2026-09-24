"""리포트 마크다운 변환이 deep_dive 신구 스키마를 모두 렌더하는지 묶는다.

deep_dive 스키마 분해(test_deep_dive_schema.py) 이후에도 DB에는
detailed_analysis 시절의 캐시 결과가 남아 있다. 리포트는 두 형태를 모두
읽어야 한다: 신 필드는 라벨을 달아 렌더하고, 구 필드는 기존처럼 본문으로
살린다.
"""

from copy import deepcopy

import pytest

from api.report_service import _format_phase_data


def test_deep_dive_report_renders_structured_fields():
    data = {
        "problem_definition": "수차 보정이 느리다",
        "as_is": "기존 SPGD는 수렴이 느리다",
        "to_be": "단일 샷 보정",
        "solution": "회절 신경망으로 위상을 직접 추정",
        "method_summary": "D2NN 5층을 시뮬레이션으로 학습",
        "key_results": "Strehl ratio 0.91 달성",
        "strengths": ["빠르다"],
        "weaknesses": ["대역폭 제한"],
    }
    out = _format_phase_data("deep_dive", data)
    for text in data.values():
        if isinstance(text, str):
            assert text in out
    assert "빠르다" in out and "대역폭 제한" in out


def test_deep_dive_report_still_renders_legacy_cached_results():
    """구 캐시 행(detailed_analysis만 있음)이 빈 리포트가 되면 안 된다."""
    data = {
        "detailed_analysis": "옛 형식의 긴 분석 본문",
        "strengths": ["강점 하나"],
        "weaknesses": [],
    }
    out = _format_phase_data("deep_dive", data)
    assert "옛 형식의 긴 분석 본문" in out
    assert "강점 하나" in out


def test_deep_dive_report_skips_empty_optional_fields():
    """빈 문자열 필드(as_is 없음 등)에 빈 라벨 줄을 만들지 않는다."""
    data = {
        "problem_definition": "문제",
        "as_is": "",
        "to_be": "",
        "solution": "해법",
        "method_summary": "방법",
        "key_results": "결과",
        "strengths": [],
        "weaknesses": [],
    }
    out = _format_phase_data("deep_dive", data)
    assert "As-Is" not in out and "To-Be" not in out


def test_report_preserves_section_answers_in_paper_order():
    answers = [
        {
            "section_title": "2. Methods",
            "question": "왜 두 측정 조건을 비교했나요?",
            "answer": "측정 조건이 결과에 미치는 영향을 분리하기 위해 비교했습니다.",
            "explanation": "두 조건에 동일한 분석을 적용했습니다.\n\n```python\ncompare(a, b)\n```",
            "source_refs": ["2. Methods", "Figure 1"],
        },
        {
            "section_title": "3. Results",
            "question": "결과의 해석 범위는 무엇인가요?",
            "answer": "보고된 측정 조건에서 얻은 결과로 한정합니다.",
            "explanation": "",
            "source_refs": ["3. Results", "Table 1"],
        },
    ]
    data = {"section_answers": answers, "transfer_checks": []}
    original = deepcopy(data)

    out = _format_phase_data("deep_dive", data)

    assert "### 섹션별 핵심 답변" in out
    for answer in answers:
        for field in ("section_title", "question", "answer", "explanation"):
            assert answer[field] in out
        for reference in answer["source_refs"]:
            assert reference in out
    assert out.index("2. Methods") < out.index("3. Results")
    assert out.count("**설명:**") == 1
    assert data == original


@pytest.mark.parametrize("basis,label,references", [
    ("reported", "원문에 명시", ["2. Methods", "Table 2"]),
    ("inferred", "원문에서 추론", ["3. Results"]),
    ("not_reported", "제공 자료에서 확인 못함", []),
])
def test_report_labels_condition_basis_and_transfer_proposals(basis, label, references):
    data = {
        "section_answers": [],
        "transfer_checks": [{
            "item": "시간 조건",
            "paper_condition": "측정 시점의 조건을 검토했습니다.",
            "condition_basis": basis,
            "check_before_transfer": "사용할 환경의 시간 조건을 먼저 확인합니다.",
            "source_refs": references,
        }],
    }

    out = _format_phase_data("deep_dive", data)

    assert "### 옮겨 쓸 때 확인할 조건" in out
    assert "시간 조건" in out
    assert label in out
    assert data["transfer_checks"][0]["paper_condition"] in out
    assert "**적용 전 확인 제안:**" in out
    assert data["transfer_checks"][0]["check_before_transfer"] in out
    assert "저자가 검증한 사실이나 적용 가능 판정이 아닙니다" in out
    for reference in references:
        assert reference in out
    if not references:
        assert "**근거:**" not in out


def test_report_preserves_comparison_and_its_scope():
    out = _format_phase_data("deep_dive", {
        "novelty_assessment": "논문에 보고된 범위에서 새로운 접근입니다.",
        "comparison_to_prior_work": "원문이 비교한 기준 방법의 차이를 설명합니다.",
        "comparison_scope": "in_paper_only",
    })

    assert "논문에 보고된 범위에서 새로운 접근입니다." in out
    assert "원문이 비교한 기준 방법의 차이를 설명합니다." in out
    assert "외부 문헌 검증은 하지 않았습니다" in out


@pytest.mark.parametrize("extensions", [
    {"section_answers": []},
    {"transfer_checks": []},
    {"section_answers": "invalid", "transfer_checks": []},
    {"section_answers": [{}], "transfer_checks": []},
    {"section_answers": [], "transfer_checks": [None]},
    {"section_answers": [], "transfer_checks": [{
        "item": "숨겨야 할 손상된 조건", "paper_condition": "조건",
        "condition_basis": "verified", "check_before_transfer": "확인",
        "source_refs": [],
    }]},
])
def test_report_marks_invalid_extensions_and_keeps_existing_body(extensions):
    out = _format_phase_data("deep_dive", {
        "problem_definition": "기존 구조화 문제 설명",
        "detailed_analysis": "기존 장문 분석",
        "weaknesses": ["기존 해석의 한계"],
        **extensions,
    })

    assert "새 요약 항목의 구조를 확인하지 못했습니다" in out
    assert "기존 구조화 문제 설명" in out
    assert "기존 장문 분석" in out
    assert "기존 해석의 한계" in out
    assert "숨겨야 할 손상된 조건" not in out
    assert "이번 분석에서 작성된 항목이 없어요" not in out


def test_report_distinguishes_empty_current_extensions_from_legacy_results():
    current = _format_phase_data("deep_dive", {
        "section_answers": [], "transfer_checks": [],
    })
    legacy = _format_phase_data("deep_dive", {"detailed_analysis": "기존 분석"})

    assert "이번 분석에서 작성된 항목이 없어요" in current
    assert "### 섹션별 핵심 답변" not in current
    assert "### 옮겨 쓸 때 확인할 조건" not in current
    assert "이번 분석에서 작성된 항목이 없어요" not in legacy
    assert "새 요약 항목의 구조를 확인하지 못했습니다" not in legacy


@pytest.mark.parametrize("phase", ["visual", "recipe", "deep_dive"])
def test_report_exports_partial_input_notice(phase):
    data = {"_input_coverage": {
        "mode": "text", "status": "partial", "missing": ["Appendix was not supplied"], "pdf_sha256": None,
    }}
    output = _format_phase_data(phase, data)
    assert "부분 분석" in output
    assert "Appendix was not supplied" in output


def test_report_pdf_scope_is_not_an_accuracy_claim():
    output = _format_phase_data("deep_dive", {"_input_coverage": {
        "mode": "pdf", "status": "provided_pdf", "missing": [], "pdf_sha256": "a" * 64,
    }})
    assert "원본 PDF 제공" in output
    assert "모든 내용을 정확히 판독했다는 뜻은 아닙니다" in output
    assert "부분 분석" not in output


def test_legacy_and_malformed_report_scope_remain_unknown():
    for data in ({}, {"_input_coverage": {"status": "provided_pdf"}}):
        assert "입력 범위 미확인" in _format_phase_data("deep_dive", data)


@pytest.mark.parametrize("coverage", [
    {"mode": "pdf", "status": "provided_pdf", "missing": [""], "pdf_sha256": "a" * 64},
    {"mode": "pdf", "status": "partial", "missing": ["  "], "pdf_sha256": "a" * 64},
    {"mode": "text", "status": "partial", "missing": [], "pdf_sha256": "a" * 64},
    {"mode": "pdf", "status": "partial", "missing": [], "pdf_sha256": "invalid"},
    {"mode": "pdf", "status": "partial", "missing": [], "pdf_sha256": None},
    {"mode": [], "status": "partial", "missing": [], "pdf_sha256": None},
])
def test_report_rejects_malformed_coverage_consistently_with_ui(coverage):
    output = _format_phase_data("deep_dive", {"_input_coverage": coverage})
    assert "입력 범위 미확인" in output
    assert "부분 분석" not in output
    assert "원본 PDF 제공" not in output
