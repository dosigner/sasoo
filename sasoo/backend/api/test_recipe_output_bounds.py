"""recipe 출력이 폭주로 새지 않게 묶는 계약.

2026-08-16~17 실측에서 나온 자리다. 구조화 출력은 JSON 문법을 강제하지만
**문자열 값 안에서는 어떤 토큰도 합법**이다. 그래서 모델이 "끝났다"고 판단한
뒤 종료 토큰을 못 내면 마지막 자유서술 문자열 안에 갇혀 출력 상한까지 필러를
뱉는다. row-368(gemini-3.7-flash) 실측: 162,704자 중 92.4%가
`(Fin). (End). Done!` 필러였고 닫는 따옴표가 끝내 나오지 않았다.

같은 실패가 gemini-3.6-flash에서도 났다. DB의 3.6 recipe 행 6개 중 4개에
흔적이 있다(3개는 오염된 채 저장, 1개는 재시도로 회복). 즉 모델 문제가 아니라
스키마 설계 문제다.

두 겹으로 막는다.
  1. 마지막 속성을 자유서술 문자열로 두지 않는다 — 문법이 종료를 강제한다.
  2. max_output_tokens로 폭주 비용에 상한을 건다 — 1이 뚫려도 손해가 유한하다.
"""

import api.analysis_routes as analysis_routes


def _free_text_string(prop: dict) -> bool:
    """열거형이나 형식 제약이 없는 자유서술 문자열인지."""
    return prop.get("type") == "string" and not prop.get("enum") and not prop.get("format")


def test_recipe_schema_has_no_score_rationale():
    """폭주의 트리거였고 읽는 곳이 하나도 없던 필드다.

    프론트(RecipeCard, AnalysisPanel), CSV 내보내기(recipeCsv), 리포트
    (report_service) 전부 reproducibility_score(숫자)만 쓴다. 2026-08-17 확인.
    """
    assert "score_rationale" not in analysis_routes._RECIPE_SCHEMA["properties"]


def test_recipe_schema_does_not_end_with_a_free_text_string():
    """마지막 속성이 자유서술 문자열이면 종료 토큰 실패가 갈 곳이 생긴다.

    이 자리를 숫자나 열거형으로 두면 구조화 출력 문법이 종료를 강제한다.
    새 필드를 뒤에 붙일 때 이 테스트가 막아 준다.
    """
    props = analysis_routes._RECIPE_SCHEMA["properties"]
    last_key = list(props)[-1]
    assert not _free_text_string(props[last_key]), (
        f"마지막 속성 {last_key!r}이 자유서술 문자열이다. "
        "폭주가 갈 자리를 만들지 마라 — 숫자·열거형 필드를 마지막에 둬라"
    )


def test_recipe_stage_has_an_output_cap():
    """recipe에 출력 상한이 걸려 있어야 한다."""
    assert analysis_routes._STAGE_MAX_OUTPUT_TOKENS.get("recipe") is not None


def test_recipe_output_cap_leaves_room_for_the_largest_real_recipe():
    """상한이 정상 출력을 자르면 안 된다.

    실측 최대 정상 recipe 본문은 row-368의 12,416자(파라미터 26개 완성)였다.
    thinking 토큰이 상한에 포함되는지는 문서에 없어(2026-08-17 확인) 넉넉히 둔다.
    동시에 모델 상한(65,536)보다는 확실히 낮아야 절감 효과가 있다.
    """
    cap = analysis_routes._STAGE_MAX_OUTPUT_TOKENS["recipe"]
    assert 16_000 <= cap <= 32_000, "정상 출력에는 여유를, 폭주에는 상한을"
    assert cap < 65_536


def test_chain_stage_sends_the_cap_for_recipe():
    """상수만 있고 호출에 안 실리면 아무 일도 안 일어난다."""
    import asyncio
    from unittest.mock import patch

    captured = {}

    async def _fake_call(prompt, **kwargs):
        captured.update(kwargs)
        return {"text": "{}", "model": "m", "tokens_in": 1, "tokens_out": 2, "interaction_id": None}

    with patch("api.analysis_routes.call_interaction", new=_fake_call):
        asyncio.run(analysis_routes._run_chain_stage(
            phase="recipe",
            prompt_chain="지시",
            prompt_fallback="폴백",
            system_instruction="si",
            previous_interaction_id=None,
            pdf_uri=None,
            response_schema={"type": "object"},
        ))
    assert captured["max_output_tokens"] == analysis_routes._STAGE_MAX_OUTPUT_TOKENS["recipe"]


def test_chain_stage_sends_no_cap_for_stages_without_one():
    """상한이 없는 단계에는 키를 보내지 않는다 — 기본값을 우리가 정하지 않는다."""
    import asyncio
    from unittest.mock import patch

    captured = {}

    async def _fake_call(prompt, **kwargs):
        captured.update(kwargs)
        return {"text": "{}", "model": "m", "tokens_in": 1, "tokens_out": 2, "interaction_id": None}

    with patch("api.analysis_routes.call_interaction", new=_fake_call):
        asyncio.run(analysis_routes._run_chain_stage(
            # deep_dive는 2026-08-29 실측(VLA 4/6 폭주) 이후 상한이 생겨
            # 상한 없는 단계의 대표가 visual로 바뀌었다.
            phase="visual",
            prompt_chain="지시",
            prompt_fallback="폴백",
            system_instruction="si",
            previous_interaction_id=None,
            pdf_uri=None,
            response_schema={"type": "object"},
        ))
    assert captured.get("max_output_tokens") is None
