"""
Sasoo - Model IDs

Single source of truth for every LLM model string used across the backend.
Pair with services/pricing.py: every ID here must have a PRICING entry.

Model choice rationale (2026-07, Gemini-only stack):
  FLASH_LITE  - cheapest triage tier; screening only.
  FLASH       - workhorse for text-only comparison work.
  FLASH_HQ    - Gemini 3.5 Flash. MRCR@128k 77.3% (vs 67.2% on FLASH) and
                MMMU-Pro 83.6% / CharXiv 84.2%, which beats PRO on vision.
                Used wherever we search a full paper or read a figure.
  PRO         - deepest reasoning (GPQA 94.3%); recipe, deep dive, planning.
  IMAGE       - Nano Banana Pro. Only image model with a published
                text-rendering error rate (<10% single-line), which is what
                decides whether axis labels and equations survive.
"""

# Text models
MODEL_FLASH_LITE = "gemini-3.1-flash-lite"
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_FLASH_HQ = "gemini-3.5-flash"
MODEL_PRO = "gemini-3.1-pro-preview"

# Image generation (PaperBanana)
MODEL_IMAGE = "gemini-3-pro-image"

# ---------------------------------------------------------------------------
# Phase -> model mapping (the analysis pipeline)
# ---------------------------------------------------------------------------

MODEL_SCREENING = MODEL_FLASH_LITE
MODEL_CITATION = MODEL_FLASH_HQ      # searches the full paper -> needs MRCR
MODEL_VISUAL = MODEL_FLASH_HQ        # reads figures -> needs vision
MODEL_RECIPE = MODEL_PRO
MODEL_DEEP_DIVE = MODEL_PRO
MODEL_VIZ_PLANNING = MODEL_PRO
MODEL_MERMAID = MODEL_PRO
MODEL_CHAT = MODEL_FLASH_HQ          # the only path the user watches live
MODEL_FIGURE_EXPLAIN = MODEL_FLASH_HQ

# Resolver / detector utilities (short, mechanical judgements)
MODEL_RESOLVER = MODEL_FLASH
