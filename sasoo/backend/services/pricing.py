"""
Sasoo - Unified Pricing Module

Single source of truth for LLM pricing across all services.
All prices are in USD per 1 million tokens.

Verified against ai.google.dev/gemini-api/docs/pricing on 2026-08-16 (paid tier);
3.8 Flash 항목은 2026-09-05에 같은 페이지로 확인했다.
Image models bill their image output separately from text output; IMAGE_PRICING
below holds the per-image price, since calc_cost's token model cannot express it.

일부 모델은 단가가 날짜로 갈린다. Google이 "$0.75 through December 31, 2026.
$1.50 starting January 1, 2027." 꼴로 고시하기 때문이다. 스칼라 하나로는 두 기간을
같이 담을 수 없어서 어느 값을 넣든 반대쪽 기간에서 조용히 틀린다. 표준가는
PRICING에 두고, 한시 도입가는 만료일과 함께 INTRO_PRICING에 둔다. calc_cost가
기준일로 고른다.
"""

from datetime import date, datetime, timezone
from typing import NamedTuple

# Pricing table (USD per 1M tokens). 한시 할인이 끝난 뒤의 표준가.
PRICING: dict[str, dict[str, float]] = {
    # --- Gemini 3.x text ---
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    # NOTE: >200K-token prompts are billed at $4.00 / $18.00. calc_cost applies
    # the flat rate, so long-context calls under-report. See PRO_LONG_CONTEXT.
    "gemini-3.8-flash": {"input": 1.50, "output": 7.50},  # 2026-09-02 발표(GA), 공식 pricing 확인함 (ai.google.dev, 2026-09-05); 3.7과 고시 동일, output은 thinking 토큰 포함. 2026-12-31까지는 INTRO_PRICING이 우선
    "gemini-3.7-flash": {"input": 1.50, "output": 7.50},  # 2026-08-13 발표(GA), 공식 pricing 확인함 (ai.google.dev, 2026-08-16); output은 thinking 토큰 포함. 2026-12-31까지는 INTRO_PRICING이 우선
    "gemini-3.6-flash": {"input": 1.50, "output": 7.50},  # 2026-07-21 발표, 공식 pricing 확인함 (ai.google.dev, 2026-08-16); output은 thinking 토큰 포함. 2026-12-31까지는 INTRO_PRICING이 우선
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},  # 2026-07-21 발표, 공식 pricing 확인함 (ai.google.dev, 2026-07-24); output은 thinking 토큰 포함
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},

    # --- Gemini 3.x image (text-token side; per-image cost in IMAGE_PRICING) ---
    "gemini-3-pro-image": {"input": 2.00, "output": 12.00},
    "gemini-3.1-flash-image": {"input": 0.50, "output": 3.00},

    # --- Legacy IDs kept so historical rows in the DB still price correctly ---
    "gemini-3.1-flash-lite-preview": {"input": 0.25, "output": 1.50},
    "gemini-3-pro-image-preview": {"input": 2.00, "output": 12.00},
    "gemini-3.1-flash-image-preview": {"input": 0.50, "output": 3.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},

    # --- OpenAI 텍스트 (provider 중립화 — 단가는 2026-08-05 공식 페이지 확인값) ---
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
}


class IntroPrice(NamedTuple):
    """만료일이 있는 한시 도입가. through 당일까지 유효하다."""

    input: float
    output: float
    through: date


# 한시 도입가. 만료일이 지나면 PRICING의 표준가로 자동 복귀한다.
# 확인: ai.google.dev/gemini-api/docs/pricing, 2026-08-16 (paid tier, standard); 3.8은 2026-09-05.
INTRO_PRICING: dict[str, IntroPrice] = {
    "gemini-3.8-flash": IntroPrice(0.75, 3.75, date(2026, 12, 31)),
    "gemini-3.7-flash": IntroPrice(0.75, 3.75, date(2026, 12, 31)),
    "gemini-3.6-flash": IntroPrice(0.75, 3.75, date(2026, 12, 31)),
}

# Prompts above this many tokens are billed at the long-context rate.
PRO_LONG_CONTEXT_THRESHOLD = 200_000
PRO_LONG_CONTEXT: dict[str, dict[str, float]] = {
    "gemini-3.1-pro-preview": {"input": 4.00, "output": 18.00},
}
# flash 계열(3.6/3.7/3.8)에는 프롬프트 길이별 계층이 없다. 1M 문맥 전체가 같은 단가다
# (ai.google.dev/gemini-api/docs/pricing, 2026-08-16 확인, 3.8은 2026-09-05 확인).

# USD per generated image (1K-2K resolution).
IMAGE_PRICING: dict[str, float] = {
    "gemini-3-pro-image": 0.134,
    "gemini-3-pro-image-preview": 0.134,
    "gemini-3.1-flash-image": 0.067,
    "gemini-3.1-flash-image-preview": 0.067,
    # gpt-image-2, 1536x1024 (quality별 출력 토큰 차이로 장당 가격이 갈린다)
    "gpt-image-2:low": 0.005,
    "gpt-image-2:medium": 0.041,
    "gpt-image-2:high": 0.165,
}

_FALLBACK = "gemini-3-flash-preview"
_FALLBACK_OPENAI = "gpt-5.6-luna"


def _fallback_for(model: str) -> str:
    """미등록 모델의 폴백 단가 — provider를 넘어가는 오산 금지(스펙 R7-1)."""
    return _FALLBACK_OPENAI if model.startswith("gpt-") else _FALLBACK


def _rate(model: str, as_of: date) -> dict[str, float]:
    """기준일에 유효한 (input, output) 단가.

    폴백은 공급사별로 갈린다 — gpt-* 를 Gemini 단가로 계산하면 비용이 조용히
    오산된다(스펙 R7-1, services/test_pricing.py가 잠근다).
    """
    intro = INTRO_PRICING.get(model)
    if intro is not None and as_of <= intro.through:
        return {"input": intro.input, "output": intro.output}
    return PRICING.get(model) or PRICING[_fallback_for(model)]


def calc_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    as_of: date | None = None,
) -> float:
    """
    Calculate USD cost for a single LLM call.

    Args:
        model: Model identifier (e.g., "gemini-3.5-flash")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        as_of: 단가 기준일. 생략하면 오늘(UTC). 호출 시점에 과금되는 값을 계산하는
            함수이므로 기본값이 맞다. 원장에는 이 값을 계산해 그때그때 적재하고,
            지금은 과거 행을 다시 계산하는 경로가 없다. 테스트는 날짜를 고정해서 준다.
            로컬 타임존을 쓰면 같은 호출이 기계 설정에 따라 다른 단가를 받는다.

            과거 행을 재계산하는 경로를 새로 만든다면 반드시 그 행이 기록된 시각을
            as_of로 넘겨라. 기본값(오늘)으로 계산하면 한시 도입가가 만료된 뒤부터
            도입가 기간에 만들어진 행이 2배로 계산된다.

    Returns:
        Total cost in USD, rounded to 8 decimal places
    """
    if (
        input_tokens > PRO_LONG_CONTEXT_THRESHOLD
        and model in PRO_LONG_CONTEXT
    ):
        pricing = PRO_LONG_CONTEXT[model]
    else:
        pricing = _rate(model, as_of or datetime.now(timezone.utc).date())

    cost = (input_tokens / 1_000_000) * pricing["input"] + \
           (output_tokens / 1_000_000) * pricing["output"]
    return round(cost, 8)


def calc_image_cost(model: str, image_count: int = 1) -> float:
    """Calculate USD cost for generated images (billed per image, not per token)."""
    price = IMAGE_PRICING.get(model, IMAGE_PRICING["gemini-3.1-flash-image"])
    return round(price * image_count, 8)
