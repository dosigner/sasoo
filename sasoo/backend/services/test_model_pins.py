"""단계별 모델 선택이 근거 없이 흔들리지 않게 잠근다.

이 파일은 원래 recipe를 이전 세대(3.6)에 묶은 핀을 지키던 자리였다.
2026-08-17 실측으로 그 핀의 전제가 사실이 아님이 드러나 핀을 풀었고, 지금은
"왜 풀었는지"와 "폭주가 재발해도 손해가 유한한 이유"를 잠근다.

## 핀을 풀게 만든 근거

핀의 근거는 "3.7 Flash가 recipe에서 폭주 반복에 빠진다"였다. 참이지만 불완전했다.
**3.6도 같은 자리에서 같은 방식으로 폭주한다.**

  analysis_results 233행 전수 검사 결과 결함 행 4개 중 3개가 recipe이고 전부 3.6이었다.
    id=362 paper 48   70,290 tok  $0.5662  score_rationale 3,059자 오염된 채 저장
    id=322 paper 41   67,832 tok  $0.5248  첫 시도 폭주, 재시도가 회복
    id=355 paper 45   19,145 tok  $0.1729  score_rationale 3,713자 오염, 프로덕션 행이었다
    id=346            6,172 tok   $0.0798  parameters[0].unit 17,554자 오염
  3.6의 recipe 행 6개 중 4개다. id=362가 태운 금액은 3.7 실패 행($0.5062)보다 크다.

원인은 모델이 아니라 스키마였다. 구조화 출력은 JSON 문법을 강제하지만 문자열 값
안에서는 어떤 토큰도 합법이라, 마지막 자유서술 문자열이 유일한 탈출구였다.
그 자리에 있던 score_rationale은 프론트·CSV·리포트 어디서도 읽지 않는 필드였다.

## 격리 실측 (paper 45, thinking=medium, 상한 24,000, 각 5회)

  군            모델   스키마   회당 params  회당 VERIFIED  검증률   회당 비용
  A             3.7    구        27.8        18.8          67.6%   $0.0307
  B             3.7    신        26.4        19.4          73.5%   $0.0318
  C             3.6    구        17.8        14.0          78.7%   $0.0386

VERIFIED는 인용이 PDF 텍스트층과 일치하고 값이 인용에 있고 페이지가 확인된 것만 센다.
3.7이 검증된 근거를 39% 많이 내면서 21% 싸다. B의 최솟값(17)이 C의 최댓값(16)보다 크다.

전문: .superpowers/sdd/2026-08-17-recipe-runaway/measurement-report.md
"""

import api.analysis_routes as analysis_routes
import services.models as models
from services.pricing import PRICING


def test_flash_hq_is_the_38_flash_id():
    """FLASH_HQ의 문자열 값 자체를 잠근다.

    3.8로 올린 판단(2026-09-05, DEC-021): 단가가 3.7과 동일한데 PDF 문서 이해
    GDP.pdf 34.0 -> 35.0%, 도표 추론 CharXiv 84.5 -> 86.2%로 앱이 기대는 축이
    내려간 곳 없이 오르고, thinking_level 계약(minimal 400)이 실호출로 같았다.
    긴 문맥 검색 GDM-MRCR v2는 3.8 카드에 없어 미확인이다. 3.7로 올린 판단의
    근거(3.6 대비 MRCR 91.8 -> 97.0%, GDP.pdf 22.0 -> 34.0%)는 main #51에 있다.
    되돌리려면 새 실측이 먼저다 — 3.7이 이 축들에서 낫다는 증거를 가져와라.

    이 단정이 없으면 값을 조용히 되돌려도 전 스위트가 통과한다. 다른 방어선은
    모두 상수 대 상수이거나(test_recipe_uses_flash_hq) 단가표 존재 여부만
    보므로(services/test_pricing.py::test_every_model_constant_is_priced),
    이미 단가가 있는 Gemini ID로 바꾸면 아무것도 걸리지 않는다.
    services/test_model_registry.py는 이 상수와 레지스트리가 일치하는지만 보고
    값은 여기에 위임한다.
    """
    assert models.MODEL_FLASH_HQ == "gemini-3.8-flash"


def test_recipe_uses_flash_hq():
    """recipe는 다른 단계와 같은 모델을 쓴다.

    되묶으려면 실측이 먼저다. 3.6이 3.7보다 나은 결과를 낸다는 증거를 가져와라 —
    2026-08-17 실측은 반대를 말한다(검증된 파라미터 14.0 대 19.4).
    """
    assert models.MODEL_RECIPE == models.MODEL_FLASH_HQ


def test_flash_prev_stays_priced_for_historical_rows():
    """DB에 3.6과 3.7이 만든 행이 남아 있다. 단가표에서 빼면 그 행들의 비용이 조용히 틀린다."""
    assert models.MODEL_FLASH_PREV in PRICING
    assert "gemini-3.6-flash" in PRICING


def test_recipe_keeps_an_output_cap():
    """폭주가 재발해도 손해가 유한해야 한다.

    핀을 푼 이상 이 상한이 유일한 비용 방어선이다. 실측에서 상한이 실제로 걸리는 것을
    확인했다(상한 2,000 -> tokens_out 1,986, thinking 포함해서 센다).
    """
    assert analysis_routes._STAGE_MAX_OUTPUT_TOKENS.get("recipe") is not None


def test_recipe_schema_keeps_no_trailing_free_text_field():
    """폭주가 갈 자리를 다시 만들지 마라.

    상세 계약과 회귀 테스트는 api/test_recipe_output_bounds.py에 있다.
    여기서는 핀 해제의 전제가 깨지지 않았는지만 확인한다.
    """
    props = analysis_routes._RECIPE_SCHEMA["properties"]
    last = props[list(props)[-1]]
    assert last.get("type") != "string"
