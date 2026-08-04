"""
Sasoo - Model IDs

Single source of truth for every LLM model string used across the backend.
Pair with services/pricing.py: every ID here must have a PRICING entry.

Model choice rationale (2026-07, Gemini-only stack):
  FLASH_LITE  - cheapest triage tier; screening + 파일명 생성.
  FLASH_HQ    - Gemini 3.6 Flash. MRCR@128k 77.3% and MMMU-Pro 83.6% /
                CharXiv 84.2%, which beats PRO on vision.
                Used wherever we search a full paper or read a figure.
  PRO         - deepest reasoning (GPQA 94.3%); 5단계 텍스트 분석에는 미사용
                (A/B 후 승격 후보). 이미지 설명 플래너(viz/figure_gen.py)는 사용 중.
  IMAGE       - Nano Banana 2 as the Gemini-side renderer; gpt-image-2
                (Arena text-to-image #1) is the default. Provider choice and
                fallback live in services/viz/figure_gen.py.
"""

# Text models
MODEL_FLASH_LITE = "gemini-3.5-flash-lite"
MODEL_FLASH_HQ = "gemini-3.6-flash"
MODEL_PRO = "gemini-3.1-pro-preview"

# OpenAI 텍스트 모델 — provider 중립화(스펙 2026-07-31 + 개정 1)
MODEL_LUNA = "gpt-5.6-luna"

# Image generation
MODEL_IMAGE = "gemini-3.1-flash-image"   # Nano Banana 2 ($0.067/장)
MODEL_IMAGE_OPENAI = "gpt-image-2"

# ---------------------------------------------------------------------------
# Phase -> model mapping (the analysis pipeline)
# ---------------------------------------------------------------------------

MODEL_SCREENING = MODEL_FLASH_LITE
MODEL_CITATION = MODEL_FLASH_HQ      # searches the full paper -> needs MRCR
MODEL_VISUAL = MODEL_FLASH_HQ        # reads figures -> needs vision
MODEL_RECIPE = MODEL_FLASH_HQ        # 실효 운영값. PRO 승격은 품질/비용 A/B 후 결정
MODEL_DEEP_DIVE = MODEL_FLASH_HQ     # 실효 운영값. PRO 승격은 품질/비용 A/B 후 결정
MODEL_VIZ_PLANNING = MODEL_FLASH_HQ  # 실효 운영값
MODEL_MERMAID = MODEL_FLASH_HQ       # 실효 운영값
MODEL_CHAT = MODEL_FLASH_HQ          # the only path the user watches live
MODEL_FIGURE_EXPLAIN = MODEL_FLASH_HQ
