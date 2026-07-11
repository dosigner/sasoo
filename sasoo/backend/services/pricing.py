"""
Sasoo - Unified Pricing Module

Single source of truth for LLM pricing across all services.
All prices are in USD per 1 million tokens.

Verified against ai.google.dev/gemini-api/docs/pricing on 2026-07-11 (paid tier).
Image models bill their image output separately from text output; IMAGE_PRICING
below holds the per-image price, since calc_cost's token model cannot express it.
"""

# Pricing table (USD per 1M tokens)
PRICING: dict[str, dict[str, float]] = {
    # --- Gemini 3.x text ---
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    # NOTE: >200K-token prompts are billed at $4.00 / $18.00. calc_cost applies
    # the flat rate, so long-context calls under-report. See PRO_LONG_CONTEXT.
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
}

# Prompts above this many tokens are billed at the long-context rate.
PRO_LONG_CONTEXT_THRESHOLD = 200_000
PRO_LONG_CONTEXT: dict[str, dict[str, float]] = {
    "gemini-3.1-pro-preview": {"input": 4.00, "output": 18.00},
}

# USD per generated image (1K-2K resolution).
IMAGE_PRICING: dict[str, float] = {
    "gemini-3-pro-image": 0.134,
    "gemini-3-pro-image-preview": 0.134,
    "gemini-3.1-flash-image": 0.067,
    "gemini-3.1-flash-image-preview": 0.067,
}

_FALLBACK = "gemini-3-flash-preview"


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Calculate USD cost for a single LLM call.

    Args:
        model: Model identifier (e.g., "gemini-3.5-flash")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Total cost in USD, rounded to 8 decimal places
    """
    if (
        input_tokens > PRO_LONG_CONTEXT_THRESHOLD
        and model in PRO_LONG_CONTEXT
    ):
        pricing = PRO_LONG_CONTEXT[model]
    else:
        pricing = PRICING.get(model, PRICING[_FALLBACK])

    cost = (input_tokens / 1_000_000) * pricing["input"] + \
           (output_tokens / 1_000_000) * pricing["output"]
    return round(cost, 8)


def calc_image_cost(model: str, image_count: int = 1) -> float:
    """Calculate USD cost for generated images (billed per image, not per token)."""
    price = IMAGE_PRICING.get(model, IMAGE_PRICING["gemini-3.1-flash-image"])
    return round(price * image_count, 8)
