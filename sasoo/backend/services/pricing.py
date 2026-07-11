"""
Sasoo - Unified Pricing Module

Single source of truth for LLM pricing across all services.
All prices are in USD per 1 million tokens.
"""

# Pricing table (USD per 1M tokens)
PRICING: dict[str, dict[str, float]] = {
    # Gemini 3.x models
    "gemini-3-flash-preview": {"input": 0.25, "output": 1.50},
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3-pro-image-preview": {"input": 2.00, "output": 12.00},
    "gemini-3.1-flash-lite-preview": {"input": 0.02, "output": 0.30},
    "gemini-3.1-flash-image-preview": {"input": 0.10, "output": 0.40},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
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
    pricing = PRICING.get(model, PRICING["gemini-3.5-flash"])
    cost = (input_tokens / 1_000_000) * pricing["input"] + \
           (output_tokens / 1_000_000) * pricing["output"]
    return round(cost, 8)
