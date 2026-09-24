from datetime import date
from contextlib import contextmanager
from collections.abc import Iterator

import pytest

import services.pricing as pricing
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


def test_luna_is_registered():
    assert "gpt-5.6-luna" in PRICING
    entry = PRICING["gpt-5.6-luna"]
    assert entry["input"] > 0
    assert entry["output"] > 0


def test_unknown_openai_model_does_not_use_gemini_fallback():
    """미지의 gpt-* 모델을 Gemini 단가로 조용히 계산하면 비용이 오산된다(스펙 R7-1)."""
    cost_unknown_gpt = calc_cost("gpt-99-future", 1_000_000, 1_000_000)
    cost_luna = calc_cost("gpt-5.6-luna", 1_000_000, 1_000_000)
    assert cost_unknown_gpt == cost_luna  # OpenAI 폴백은 Luna 단가


def test_unknown_gemini_model_keeps_existing_fallback():
    from services.pricing import _FALLBACK
    cost = calc_cost("gemini-99-future", 1_000_000, 0)
    assert cost == calc_cost(_FALLBACK, 1_000_000, 0)
# ---------------------------------------------------------------------------
# 날짜 조건부 단가
#
# Google은 flash 계열 단가를 날짜로 나눠 고시한다(예: "$0.75 through
# December 31, 2026. $1.50 starting January 1, 2027."). 스칼라 하나로는
# 표현할 수 없어서, 어느 값을 넣든 한쪽 기간에서 조용히 틀린다.
# calc_cost가 기준일을 받아 스스로 고르게 한다.
# ---------------------------------------------------------------------------

def test_gemini_37_flash_uses_intro_price_through_2026():
    # 도입가 $0.75 in / $3.75 out
    assert calc_cost(
        "gemini-3.7-flash", 1_000_000, 1_000_000, as_of=date(2026, 12, 31)
    ) == pytest.approx(4.50)


def test_gemini_37_flash_uses_standard_price_from_2027():
    # 2027-01-01부터 $1.50 in / $7.50 out
    assert calc_cost(
        "gemini-3.7-flash", 1_000_000, 1_000_000, as_of=date(2027, 1, 1)
    ) == pytest.approx(9.00)


def test_gemini_36_flash_shares_the_same_intro_schedule():
    # 3.7과 동일한 고시. 표준가만 넣어두면 도입가 기간 내내 2배로 과대 계상된다.
    assert calc_cost(
        "gemini-3.6-flash", 1_000_000, 1_000_000, as_of=date(2026, 12, 31)
    ) == pytest.approx(4.50)
    assert calc_cost(
        "gemini-3.6-flash", 1_000_000, 1_000_000, as_of=date(2027, 1, 1)
    ) == pytest.approx(9.00)


def test_gemini_38_flash_shares_the_same_intro_schedule():
    # 3.7과 동일한 고시(ai.google.dev, 2026-09-05 확인). 도입가 없이 표준가만 넣으면
    # 도입가 기간 내내 2배로 과대 계상된다 — 3.6이 실제로 그랬다(#51).
    assert calc_cost(
        "gemini-3.8-flash", 1_000_000, 1_000_000, as_of=date(2026, 12, 31)
    ) == pytest.approx(4.50)
    assert calc_cost(
        "gemini-3.8-flash", 1_000_000, 1_000_000, as_of=date(2027, 1, 1)
    ) == pytest.approx(9.00)


def test_intro_price_does_not_leak_into_models_without_a_schedule():
    # 스케줄이 없는 모델은 기준일과 무관하게 표준가다.
    for day in (date(2026, 12, 31), date(2027, 1, 1)):
        assert calc_cost("gemini-3.5-flash", 1_000_000, 1_000_000, as_of=day) == pytest.approx(10.50)


def test_long_context_override_still_wins_for_pro():
    # >200K 프롬프트는 PRO_LONG_CONTEXT 단가. 날짜 스케줄 도입이 이 경로를 가리면 안 된다.
    assert calc_cost(
        "gemini-3.1-pro-preview", 1_000_000, 0, as_of=date(2026, 12, 31)
    ) == pytest.approx(4.00)


def test_every_model_constant_is_priced():
    """models.py의 모든 모델 ID는 단가표에 있어야 한다.

    빠지면 calc_cost가 _FALLBACK 단가로 조용히 잘못 계산한다. 사용자에게
    보이는 비용이 틀리는데 아무도 모른다. 이 저장소에서 가장 싫어하는 버그다.
    """
    import services.models as _m
    from services.pricing import IMAGE_PRICING

    ids = sorted({v for k, v in vars(_m).items() if k.startswith("MODEL_") and isinstance(v, str)})
    assert ids, "models.py에서 MODEL_* 상수를 하나도 못 찾았다"

    unpriced = [
        mid for mid in ids
        if mid not in PRICING
        and mid not in IMAGE_PRICING
        and not any(k.split(":", 1)[0] == mid for k in IMAGE_PRICING)
    ]
    assert unpriced == [], f"단가표에 없는 모델 ID: {unpriced}"


@pytest.mark.parametrize("model,expected", [("gpt-5.6-luna", 0.0299), ("gpt-6-luna", 0.01395)])
def test_cache_categories_are_disjoint(model: str, expected: float):
    # Given separate cache read and write counts, when pricing one request:
    cost = calc_cost(model, 100_000, 10_000, cached_input_tokens=20_000, cache_write_tokens=30_000)
    # Then no input token is charged twice.
    assert cost == expected


@pytest.mark.parametrize("model,input_tokens,expected", [
    ("gpt-5.6-luna", 272_000, 0.0664), ("gpt-5.6-luna", 272_001, 0.1268004),
    ("gpt-6-luna", 272_000, 0.0322), ("gpt-6-luna", 272_001, 0.0619002),
])
def test_long_context_prices_the_whole_request(model: str, input_tokens: int, expected: float):
    # Given a request at the threshold, when pricing all input and output:
    cost = calc_cost(model, input_tokens, 10_000)
    # Then only requests above the threshold use the higher rates.
    assert cost == expected


@pytest.mark.parametrize("model,expected", [("gpt-5.6-luna", 0.0620005), ("gpt-6-luna", 0.02950025)])
def test_long_context_scales_both_cache_rates(model: str, expected: float):
    # Given an entirely cached long request, when pricing read and write tokens:
    cost = calc_cost(model, 272_001, 10_000, cached_input_tokens=200_000, cache_write_tokens=72_001)
    # Then both cache rates double and output costs 1.5 times the normal rate.
    assert cost == expected


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens"])
@pytest.mark.parametrize("invalid", [-1, True, 1.5, "1", None])
def test_invalid_token_counts_are_rejected(field: str, invalid: int | float | str | None):
    # Given invalid usage at the boundary, when pricing a request:
    counts = {"input_tokens": 100, "output_tokens": 10, field: invalid}
    # Then malformed usage cannot produce a price.
    with pytest.raises(ValueError):
        calc_cost("gpt-6-luna", **counts)


def test_cache_counts_cannot_exceed_total_input():
    # Given overlapping counts, when pricing them, then reject the invalid usage.
    with pytest.raises(ValueError):
        calc_cost("gpt-6-luna", 100, 10, cached_input_tokens=60, cache_write_tokens=41)


def test_result_prices_reported_output_without_adding_reasoning():
    # Given output that already includes reasoning, when pricing the result:
    cost = pricing.calc_result_cost({"model": "gpt-6-luna", "tokens_in": 100_000,
        "tokens_out": 10_000, "tokens_thinking": 8_000, "tokens_cached": 20_000,
        "tokens_cache_write": 30_000})
    # Then reasoning is not billed a second time.
    assert cost == 0.01395


def test_prior_attempt_total_is_not_repriced_as_one_long_request():
    # Given two 200K-input/10K-output attempts, when reading their existing total:
    cost = pricing.calc_result_cost({"model": "gpt-6-luna", "tokens_in": 400_000,
        "tokens_out": 20_000, "cost_usd_prior_attempts": 0.05})
    # Then the total keeps the per-request rate and already includes the last attempt.
    assert cost == 0.05


@pytest.mark.parametrize("cache", [{}, {"tokens_cached": None, "tokens_cache_write": None},
    {"tokens_cached": 20_000}, {"tokens_cache_write": 30_000}])
def test_missing_cache_details_use_full_input_write_upper_bound(cache):
    # Given incomplete cache metadata, when pricing known total usage:
    cost = pricing.calc_result_cost({"model": "gpt-6-luna", "tokens_in": 100_000,
        "tokens_out": 16_000, **cache})
    # Then all input uses the conservative cache-write rate.
    assert cost == 0.0205


@pytest.mark.parametrize("usage", [{}, {"tokens_in": None, "tokens_out": None},
    {"tokens_in": 0}, {"tokens_out": 0},
    {"tokens_in": 0, "tokens_out": 0, "usage_complete": False}])
def test_missing_usage_is_not_zero_cost(usage):
    # Given missing usage, when pricing an outcome, then keep it unresolved.
    with pytest.raises(ValueError):
        pricing.calc_result_cost({"model": "gpt-6-luna", **usage})


@pytest.mark.parametrize("result_model,expected", [(None, 0.015), ("gpt-5.6-luna", 0.032)])
def test_explicit_model_is_only_a_stream_fallback(result_model: str | None, expected: float):
    # Given optional stream model metadata, when an explicit fallback is supplied:
    result = {"tokens_in": 100_000, "tokens_out": 10_000, "tokens_cached": 0, "tokens_cache_write": 0}
    if result_model is not None:
        result["model"] = result_model
    cost = pricing.calc_result_cost(result, model="gpt-6-luna")
    # Then a reported model takes precedence.
    assert cost == expected


def test_gemini_result_preserves_historic_cache_pricing():
    # Given Gemini usage, when cache metadata is absent or present:
    cost = pricing.calc_result_cost({"model": "gemini-3.5-flash", "tokens_in": 100_000,
        "tokens_out": 10_000, "tokens_cached": 20_000, "tokens_cache_write": 30_000})
    # Then the existing Gemini rates remain unchanged.
    assert cost == 0.24


@pytest.mark.parametrize("invalid", [
    {"tokens_cached": -1}, {"tokens_cache_write": True},
    {"tokens_cached": 101}, {"tokens_cached": 60, "tokens_cache_write": 41},
    {"tokens_in": "100"}, {"tokens_out": False}, {"model": None},
    {"cost_usd_prior_attempts": float("nan")}, {"cost_usd_prior_attempts": float("inf")},
    {"cost_usd_prior_attempts": -1}, {"cost_usd_prior_attempts": True},
    {"cost_usd_prior_attempts": "0.1"},
])
def test_malformed_result_metadata_is_rejected(invalid):
    # Given malformed metadata, when pricing known usage, then reject it.
    with pytest.raises(ValueError):
        pricing.calc_result_cost({"model": "gpt-6-luna", "tokens_in": 100,
            "tokens_out": 10, **invalid})


def test_reported_zero_usage_is_zero_cost():
    # Given explicitly reported zero totals, when pricing them:
    cost = pricing.calc_result_cost({"model": "gpt-6-luna", "tokens_in": 0,
        "tokens_out": 0, "usage_complete": True})
    # Then genuine zero usage remains valid.
    assert cost == 0


def test_decimal_tie_rounds_half_even_at_eight_places():
    # Given exact cost 0.017033325, when rounding to eight places:
    cost = calc_cost("gpt-6-luna", 100_000, 16_000,
        cached_input_tokens=20_000, cache_write_tokens=33_333)
    # Then the lower even last digit wins without binary-float drift.
    assert cost == 0.01703332


def test_pricing_error_survives_contextmanager_traceback_assignment():
    # Given a contextmanager that rethrows the same exception:
    @contextmanager
    def wrapper() -> Iterator[None]:
        yield

    # When pricing missing usage, then the original error reaches the caller.
    with pytest.raises(pricing.PricingUsageError, match="tokens_in"):
        with wrapper():
            pricing.calc_result_cost({"model": "gpt-6-luna"})
