"""
Sasoo - Model IDs

Single source of truth for every LLM model string used across the backend.
Pair with services/pricing.py: every ID here must have a PRICING entry.

Model choice rationale (2026-08, Gemini-only stack):
  FLASH_LITE  - cheapest triage tier; screening + 파일명 생성.
  FLASH_HQ    - Gemini 3.7 Flash (GA, 2026-08-13). 이 앱이 기대는 두 축은 논문
                전체를 훑는 긴 문맥 검색과 PDF 이해다. 3.6 대비 GDM-MRCR v2
                8-needle @128k 91.8→97.0%, GDP.pdf(전문 PDF 문서 이해)
                22.0→34.0%로 오르면서 단가는 같다. 도표 추론(CharXiv, 도구
                없이)만 85.2→84.5%로 소폭 내려갔다. 그림을 읽는 단계에서는
                품질을 지켜볼 것. 수치는 DeepMind 모델 카드(2026-08-16 확인),
                MMMU-Pro는 3.7 카드에 미공개라 근거에서 뺐다.
                Used wherever we search a full paper or read a figure.
  PRO         - deepest reasoning (GPQA 94.3%); 5단계 텍스트 분석에는 미사용
                (A/B 후 승격 후보). 이미지 설명 플래너(viz/figure_gen.py)는 사용 중.
  IMAGE       - Nano Banana 2 as the Gemini-side renderer; gpt-image-2
                (Arena text-to-image #1) is the default. Provider choice and
                fallback live in services/viz/figure_gen.py.

thinking_level은 low|medium|high만 쓴다. 3.7 Flash는 minimal을 지원하지 않고,
명시하면 API가 검증 에러를 낸다(ai.google.dev, 2026-08-16 확인).
"""

# Text models
MODEL_FLASH_LITE = "gemini-3.5-flash-lite"
MODEL_FLASH_HQ = "gemini-3.7-flash"
MODEL_PRO = "gemini-3.1-pro-preview"

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
