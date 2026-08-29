"""deep_dive 출력 구조를 묶는 계약.

배경: 사용자가 논문 분석에서 문제정의, as-is→to-be, 솔루션, method, result를
바로 찾을 수 있어야 한다. 기존에는 detailed_analysis 하나에 전부 뭉쳐 있었고,
그 형태는 DEC-014에서 recipe 폭주의 근원으로 확인된 "긴 자유서술 필드"와
같은 유형이었다. 그래서 추가가 아니라 분해로 간다: detailed_analysis를 없애고
경계가 있는 구조화 필드로 나눈다.

recipe 쪽 잠금(test_recipe_output_bounds.py)과 같은 원칙을 공유한다:
마지막 속성은 자유서술 문자열로 두지 않는다.
"""

import api.analysis_routes as analysis_routes

_PROPS = analysis_routes._DEEP_DIVE_SCHEMA["properties"]

# 분해로 새로 생긴 서술 필드들. 이름을 바꾸면 렌더러 3곳(report_service,
# AnalysisPanel, workbenchSummaries)도 같이 바꿔야 한다.
_STRUCTURED_FIELDS = [
    "problem_definition",
    "as_is",
    "to_be",
    "solution",
    "method_summary",
    "key_results",
]


def _free_text_string(prop: dict) -> bool:
    return prop.get("type") == "string" and not prop.get("enum") and not prop.get("format")


def test_deep_dive_schema_exposes_structured_fields():
    for field in _STRUCTURED_FIELDS:
        assert field in _PROPS, f"{field} 필드가 스키마에 없다"


def test_deep_dive_schema_dropped_the_monolithic_narrative():
    """detailed_analysis("여러 문단")는 DEC-014가 지목한 폭주 유형의 자유서술이다.

    분해 필드가 그 내용을 전부 인수했으므로 되살리면 안 된다. 구 캐시 결과의
    detailed_analysis는 렌더러 폴백으로만 살아 있다.
    """
    assert "detailed_analysis" not in _PROPS


def test_deep_dive_schema_does_not_end_with_a_free_text_string():
    """마지막 속성이 자유서술 문자열이면 종료 토큰 실패가 갈 곳이 생긴다."""
    last_key = list(_PROPS)[-1]
    assert not _free_text_string(_PROPS[last_key]), (
        f"마지막 속성 {last_key!r}이 자유서술 문자열이다. "
        "리스트·숫자·열거형 필드를 마지막에 둬라"
    )


def test_deep_dive_required_excludes_only_as_is_to_be():
    """as_is·to_be만 required에서 빠지고 나머지 12필드는 전부 required다(DEC-020).

    as-is→to-be는 공학 논문의 프레이밍이라 이론·리뷰 논문에는 없는 경우가
    많고, 없는 필드를 강제하면 모델이 지어낸다. 그 둘만 예외다.

    나머지를 전부 required로 두는 이유는 실측이다(2026-08-29): Gemini는
    required가 아닌 5필드(novelty_assessment, comparison_to_prior_work,
    suggested_improvements, follow_up_questions, practical_applications)를
    폭주 없이 정상 완료한 실행에서도 4/4로 통째 생략해 9/14만 냈다. Luna는
    같은 조건에서 14/14였다. 프롬프트 요청은 provider별 준수율이 갈리고
    required는 양쪽 다 지킨다 — 이 목록을 줄이면 Gemini 경로에서 그 필드가
    조용히 사라진다.
    """
    schema = analysis_routes._DEEP_DIVE_SCHEMA
    required = set(schema["required"])
    optional = set(schema["properties"]) - required
    assert optional == {"as_is", "to_be"}


def test_instruction_names_every_schema_property():
    """프롬프트가 설명하지 않는 필드는 모델이 빈약하게 채우거나 생략한다.

    스키마와 프롬프트가 어긋난 채 각자 진화하는 것을 막는다.
    """
    instruction = analysis_routes._DEEP_DIVE_INSTRUCTION
    for key in _PROPS:
        assert key in instruction, f"프롬프트가 {key} 필드를 설명하지 않는다"


def test_instruction_allows_empty_string_for_absent_content():
    """없는 내용을 지어내지 않게 하는 탈출구가 프롬프트에 있어야 한다."""
    assert "빈 문자열" in analysis_routes._DEEP_DIVE_INSTRUCTION


def test_deep_dive_has_an_output_cap():
    """폭주 손해의 2차 방어. 2026-08-29 VLA 6편 실측에서 high thinking으로도
    4/6이 폭주했고, 이 상한이 폭주당 $0.26을 $0.06으로 막는 것을 실증했다.
    정상 최대 출력은 8,734(luna xhigh)라 16,000이면 여유 1.8배다."""
    cap = analysis_routes._STAGE_MAX_OUTPUT_TOKENS.get("deep_dive")
    assert cap is not None
    assert 12_000 <= cap <= 24_000
    assert cap < 65_536


def test_comparison_scope_is_an_enum_not_free_text():
    """'논문 자체 비교 범위 기준'이라는 한정은 enum 필드가 나른다.

    2026-08-29 실측: 이 한정을 본문에 "명시해"라고 요구했더니 모델이 그 문구를
    무한 반복하며 폭주했다(VLA 4/6). 정형 문구를 자유서술 필드에 반복시키는
    지시는 폭주의 씨앗이다."""
    prop = _PROPS["comparison_scope"]
    assert prop.get("enum") == ["in_paper_only"]


def test_instruction_does_not_demand_phrase_echo():
    """폭주 씨앗 지시("평가임을 명시해")가 되살아나지 못하게 잠근다."""
    instruction = analysis_routes._DEEP_DIVE_INSTRUCTION
    assert "평가임을 명시해" not in instruction
    assert "반복해 적지 마" in instruction
