"""
Sasoo - Model IDs

Single source of truth for every LLM model string used across the backend.
Pair with services/pricing.py: every ID here must have a PRICING entry.

Model choice rationale (2026-08, Gemini-only stack):
  FLASH_LITE  - cheapest triage tier; screening + 파일명 생성.
  FLASH_HQ    - Gemini 3.8 Flash (GA, 2026-09-02). 이 앱이 기대는 두 축은 논문
                전체를 훑는 긴 문맥 검색과 PDF 이해다. 3.7 대비 GDP.pdf(전문 PDF
                문서 이해) 34.0→35.0%, 도표 추론(CharXiv, 도구 없이) 84.5→86.2%로
                3.7에서 내려갔던 도표 축이 3.6(85.2%) 위로 돌아왔고 단가는 같다.
                긴 문맥 검색(GDM-MRCR v2)은 3.8 카드 표에 없어 3.7(97.0%) 대비
                증감을 모른다. 수치는 DeepMind 모델 카드 표(2026-09-05 확인).
                3.7로 올렸던 근거(3.6 대비 MRCR 91.8→97.0%, GDP.pdf 22.0→34.0%)는
                main #51 커밋 메시지에 있다.
                3.8 가이드는 3.7보다 토큰을 더 쓴다고 경고한다. 실측(paper 43, 각 3회):
                출력 토큰 citation −2%, visual +13%, recipe +22%(중앙값), 비용 +2~13%,
                결함 0 (RESEARCH/2026-09-05-gemini-3-8-flash-ab.md, DEC-021).
                Used wherever we search a full paper or read a figure.
                recipe 포함 텍스트 5단계 전부 이 모델을 쓴다.
  PRO         - deepest reasoning (GPQA 94.3%); 5단계 텍스트 분석에는 미사용
                (A/B 후 승격 후보). 이미지 설명 플래너(viz/figure_gen.py)는 사용 중.
  LUNA        - gpt-5.6-luna. OpenAI 키 단독 사용자의 전 단계 기본 모델.
                minimal을 지원하지 않아 최저 effort가 low다(플랜 Task 0 실측).
  IMAGE       - Nano Banana 2 as the Gemini-side renderer; gpt-image-2
                (Arena text-to-image #1) is the default. Provider choice and
                fallback live in services/viz/figure_gen.py.

thinking_level은 low|medium|high만 쓴다. 3.7과 3.8 Flash는 minimal을 지원하지 않고,
명시하면 API가 400을 낸다(3.7은 ai.google.dev 2026-08-16 확인, 3.8은 2026-09-05
실호출로 같은 메시지 확인).
"""

# Text models
MODEL_FLASH_LITE = "gemini-3.5-flash-lite"
MODEL_FLASH_HQ = "gemini-3.8-flash"
MODEL_PRO = "gemini-3.1-pro-preview"

# 이전 세대 flash. 현재 어느 단계도 쓰지 않는다. DB에 3.6과 3.7이 만든 행이 남아 있어
# 단가 계산을 위해 상수와 PRICING 항목을 유지한다(services/test_model_pins.py가 잠근다).
MODEL_FLASH_PREV = "gemini-3.7-flash"

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
# recipe도 FLASH_HQ를 쓴다(아래 실측은 3.7 시절). 2026-08-16~17 사이 잠시 3.6에 묶어 뒀다가 풀었다.
# 묶은 근거는 "3.7만 폭주 반복에 빠진다"였는데, 전수 검사 결과 3.6도 같은 자리에서
# 같은 방식으로 폭주했다(3.6 recipe 행 6개 중 4개, 그중 하나는 $0.5662). 원인은
# 모델이 아니라 마지막 자리에 있던 자유서술 필드(score_rationale)였고, 그 필드를
# 없애면서 폭주가 갈 자리 자체가 사라졌다.
# 격리 실측(paper 45, 각 5회): 3.7이 검증된 파라미터를 회당 19.4개, 3.6은 14.0개.
# 비용은 3.7이 회당 $0.0318로 3.6($0.0386)보다 싸다.
# 잠금: services/test_model_pins.py, api/test_recipe_output_bounds.py
MODEL_RECIPE = MODEL_FLASH_HQ
MODEL_DEEP_DIVE = MODEL_FLASH_HQ     # 실효 운영값. PRO 승격은 품질/비용 A/B 후 결정
MODEL_VIZ_PLANNING = MODEL_FLASH_HQ  # 실효 운영값
MODEL_MERMAID = MODEL_FLASH_HQ       # 실효 운영값
MODEL_CHAT = MODEL_FLASH_HQ          # the only path the user watches live
MODEL_FIGURE_EXPLAIN = MODEL_FLASH_HQ
