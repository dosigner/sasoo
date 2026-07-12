from services.pricing import PRICING, calc_cost


def test_gemini_35_flash_pricing():
    # $1.50 in / $9.00 out per 1M tokens
    assert calc_cost("gemini-3.5-flash", 1_000_000, 1_000_000) == 10.50


def test_gemini_31_flash_lite_pricing():
    # $0.25 in / $1.50 out per 1M tokens
    assert calc_cost("gemini-3.1-flash-lite", 1_000_000, 1_000_000) == 1.75


def test_claude_models_removed():
    assert not any(k.startswith("claude") for k in PRICING)
