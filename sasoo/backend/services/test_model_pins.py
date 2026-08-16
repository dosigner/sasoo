"""단계별 모델 고정(핀)이 근거 없이 풀리지 않게 잠근다.

recipe는 실측 근거로 이전 세대에 묶어 둔 단계다. 상수 하나만 고치면 조용히
풀리는 자리라, 왜 묶었는지와 함께 테스트로 남긴다.
"""

import services.models as models
from services.pricing import PRICING


def test_recipe_is_pinned_off_flash_hq():
    """recipe는 MODEL_FLASH_HQ를 따라가면 안 된다.

    Gemini 3.7 Flash가 이 단계에서 폭주 반복에 빠진다. 2026-08-16 실측(paper 45):
    정상 JSON으로 시작해 중간부터 "(End). (Fin). Done!"을 64K 출력 상한까지
    반복하고 잘렸다. 첫 시도와 재시도가 둘 다 그랬고(65522 x 2 = 131044 토큰),
    실패한 phase 하나에 $0.51이 나갔다. 깨진 결과가 하류 프롬프트로 흘러
    deep_dive와 viz_plan 입력까지 4.4배, 3.6배로 부풀렸다.

    recipe는 파라미터와 근거 인용을 만드는 핵심 단계다. 여기가 깨지면 근거 검증
    커버리지가 통째로 빠진다(실측에서 검증 26 -> 15).

    3.6과 3.7은 단가가 같으므로 이 핀에 비용 손해는 없다.
    재승격은 같은 코퍼스로 재실측해 폭주가 사라진 것을 확인한 뒤에 하라.
    """
    assert models.MODEL_RECIPE != models.MODEL_FLASH_HQ, (
        "recipe를 MODEL_FLASH_HQ로 되돌리려면 폭주 반복이 사라졌다는 실측이 먼저다"
    )
    assert models.MODEL_RECIPE == models.MODEL_FLASH_PREV


def test_pinned_model_is_priced():
    # 핀으로 쓰는 모델도 단가표에 있어야 한다. 없으면 폴백 단가로 조용히 틀린다.
    assert models.MODEL_FLASH_PREV in PRICING


def test_pin_costs_the_same_as_flash_hq():
    """핀의 근거는 품질이지 비용이 아니다. 단가가 갈리면 그 전제가 깨진다."""
    assert PRICING[models.MODEL_FLASH_PREV] == PRICING[models.MODEL_FLASH_HQ]
