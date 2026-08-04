"""Sasoo - LLM 호출 셔션(façade).

역사적 이름을 유지한다 — 호출부 12곳(analysis_routes, figure_service,
리졸버 3종, subfigure_detector, naming_service, figure_gen, gemini_parser,
analysis_helpers, analysis_context, vlm_probe)이 이 모듈 경로를 import한다.

지금은 gemini_client 재노출뿐이다. provider 라우팅(모델 접두사 기반)은
openai_client가 준비된 뒤 이 파일에 들어온다 — 그 전까지 동작은 바이트
단위로 동일해야 한다.
"""

from services.llm.gemini_client import (  # noqa: F401
    Lane,
    _SYSTEM_INSTRUCTION_KO,
    call_interaction,
    stream_interaction,
    upload_pdf_for_paper,
)
