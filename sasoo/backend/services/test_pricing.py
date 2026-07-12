import pytest
from services.pricing import PRICING, calc_cost


def test_gemini_35_flash_pricing():
    # $1.50 in / $9.00 out per 1M tokens
    assert calc_cost("gemini-3.5-flash", 1_000_000, 1_000_000) == 10.50


def test_gemini_31_flash_lite_pricing():
    # $0.25 in / $1.50 out per 1M tokens
    assert calc_cost("gemini-3.1-flash-lite", 1_000_000, 1_000_000) == 1.75


def test_legacy_claude_rows_still_price():
    # Interactions 전환으로 claude 호출 경로는 사라졌지만, DB의 과거 분석 행이
    # claude 모델명을 달고 있다. 단가 키를 지우면 그 행들이 폴백 단가로 조용히
    # 잘못 계산되므로 레거시 키는 유지한다. 단, 어떤 기본 모델 상수도
    # claude여서는 안 된다.
    assert calc_cost("claude-sonnet-4-20250514", 1_000_000, 0) == pytest.approx(3.00)
    import services.models as _m
    defaults = [v for k, v in vars(_m).items() if k.startswith("MODEL_") and isinstance(v, str)]
    assert not any(v.startswith("claude") for v in defaults)
