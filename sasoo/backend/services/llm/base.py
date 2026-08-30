"""Sasoo - provider 중립 LLM 인터페이스.

Gemini(Interactions API)와 OpenAI(Responses API)를 같은 모양으로 다루기 위한
공통 타입. 두 provider의 개념은 1:1로 대응된다:

    서버측 체인   previous_interaction_id  <-> previous_response_id
    사고량 조절   thinking_level           <-> reasoning.effort

PDF 업로드는 공통 계약이 아니다 — OpenAI 경로는 파일을 업로드하지 않고
로컬 추출 텍스트를 첫 호출에 주입한다(스펙 개정 1 R1). upload_pdf_for_paper는
gemini_client 전용 함수로 남는다.

lane 분리와 세마포어는 provider와 무관하므로 각 구현이 services.concurrency의
공용 풀을 쓴다.
"""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# 모든 호출은 lane을 명시해야 한다 — 기본값을 두지 않는 것이 핵심이다.
#   "chat"     : 사용자가 실시간으로 기다리는 대화형 경로.
#   "pipeline" : 분석 파이프라인. 전용 풀 + 루프별 세마포어.
Lane = Literal["chat", "pipeline"]


@dataclass(slots=True)
class LLMResponse:
    """한 번의 LLM 호출 결과. provider가 무엇이든 이 모양으로 돌려준다."""

    text: str
    interaction_id: str | None
    tokens_in: int
    tokens_out: int
    model: str


@runtime_checkable
class LLMClient(Protocol):
    """provider 구현이 만족해야 하는 계약."""

    def available(self) -> bool:
        """API 키가 있어 호출 가능한 상태인지."""
        ...

    async def call(self, **kwargs) -> LLMResponse:
        ...

    async def stream(self, **kwargs):
        ...
