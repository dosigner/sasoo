"""
Sasoo - Unified Pricing Module

Single source of truth for LLM pricing across all services.
All prices are in USD per 1 million tokens.
"""

# Pricing table (USD per 1M tokens)
PRICING: dict[str, dict[str, float]] = {
    # Gemini 3.0 models
    "gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    "gemini-3-pro-preview": {"input": 1.25, "output": 5.00},
    "gemini-3-pro-image-preview": {"input": 1.25, "output": 5.00},

    # Gemini 2.0 models
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},

    # Claude models
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Calculate USD cost for a single LLM call.

    Args:
        model: Model identifier (e.g., "gemini-3-flash-preview")
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Total cost in USD, rounded to 8 decimal places
    """
    pricing = PRICING.get(model, PRICING["gemini-3-flash-preview"])
    cost = (input_tokens / 1_000_000) * pricing["input"] + \
           (output_tokens / 1_000_000) * pricing["output"]
    return round(cost, 8)
