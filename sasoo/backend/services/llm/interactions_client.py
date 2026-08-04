"""Sasoo - LLM 호출 셔션(façade) — provider 라우팅.

역사적 이름을 유지한다(호출부 12곳이 이 경로를 import한다: analysis_routes,
figure_service, 리졸버 3종, subfigure_detector, naming_service, figure_gen,
gemini_parser, analysis_helpers, analysis_context, vlm_probe). 라우팅 규칙은
모델 접두사 하나다: gpt-* 는 openai_client, 그 외는 gemini_client.

provider 결정은 여기가 아니라 모델 선택 지점(model_registry.resolve 호출부)
에서 일어난다 — 셔션은 골라진 모델을 맞는 클라이언트로 나를 뿐이다.
"""

from services.llm import gemini_client, openai_client
from services.llm.gemini_client import (  # noqa: F401 - 하위호환 재노출
    Lane,
    _SYSTEM_INSTRUCTION_KO,
    upload_pdf_for_paper,
)


def _client_for(model: str):
    return openai_client if model.startswith("gpt-") else gemini_client


async def call_interaction(prompt, *, model, **kwargs) -> dict:
    return await _client_for(model).call_interaction(prompt, model=model, **kwargs)


async def stream_interaction(prompt, *, model, **kwargs):
    async for event in _client_for(model).stream_interaction(prompt, model=model, **kwargs):
        yield event
