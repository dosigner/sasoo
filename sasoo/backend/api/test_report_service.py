"""리포트 마크다운 변환이 deep_dive 신구 스키마를 모두 렌더하는지 묶는다.

deep_dive 스키마 분해(test_deep_dive_schema.py) 이후에도 DB에는
detailed_analysis 시절의 캐시 결과가 남아 있다. 리포트는 두 형태를 모두
읽어야 한다: 신 필드는 라벨을 달아 렌더하고, 구 필드는 기존처럼 본문으로
살린다.
"""

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
