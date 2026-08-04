"""Sasoo - OpenAI Responses API 클라이언트.

gemini_client.call_interaction과 같은 시그니처·같은 반환 dict를 유지한다 —
셔션(interactions_client)이 분기 없이 위임하기 위해서다. 개념 번역:

    previous_interaction_id  ->  previous_response_id
    thinking_level           ->  reasoning.effort
    media_resolution         ->  (무시 - Gemini 전용)

PDF 업로드는 없다(스펙 개정 1 R1) — 체인 첫 호출에 로컬 추출 텍스트를
주입한다. usage.output_tokens는 reasoning 토큰을 이미 포함하므로(R7-2)
Gemini처럼 thought를 더하지 않는다.
"""

import asyncio
import logging
import os
import threading
from typing import Any

from services.concurrency import CHAT_EXECUTOR, PIPELINE_EXECUTOR, pipeline_llm_sem
from services.llm.base import Lane
from services.llm.gemini_client import _SYSTEM_INSTRUCTION_KO
from services.models import MODEL_LUNA

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [2, 8]  # 3회 시도 — gemini_client와 동일 정책
_RETRYABLE_CLIENT_STATUS = frozenset({408, 429})

# 키가 런타임에 바뀔 수 있으므로(설정 화면) api_key를 캐시 키로 둔다.
# gemini_client와 같은 이유·같은 구조 — TLS 핸드셰이크 누적 방지.
_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


def available() -> bool:
    """OPENAI_API_KEY가 있어 호출 가능한 상태인지."""
    return bool(os.environ.get("OPENAI_API_KEY"))


def _get_client():
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY not set")
    client = _clients.get(key)
    if client is None:
        with _clients_lock:
            client = _clients.get(key)
            if client is None:
                client = OpenAI(api_key=key)
                _clients[key] = client
    return client


def _is_retryable(exc: BaseException) -> bool:
    """재시도로 풀릴 수 있는 오류인지. openai SDK는 APIStatusError.status_code를 준다.

    408/429와 5xx만 재시도. 상태 코드가 없는 예외(네트워크 끊김)는 판단 근거가
    없으니 보수적으로 재시도한다 — gemini_client와 같은 정책.
    """
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        return True
    if status in _RETRYABLE_CLIENT_STATUS:
        return True
    return status >= 500


def _translate_parts(prompt) -> Any:
    """Gemini 파트 dict 리스트를 Responses API input으로 번역한다.

    str은 그대로(SDK가 user 메시지로 감싼다). 문서 파트는 지원하지 않는다 —
    OpenAI 체인은 파일이 아니라 텍스트 주입을 쓴다(스펙 R1). 조용히
    떨어뜨리면 빈 컨텍스트로 호출이 나가므로 ValueError로 시끄럽게 막는다.
    """
    if isinstance(prompt, str):
        return prompt
    content: list[dict[str, Any]] = []
    for part in prompt:
        kind = part.get("type")
        if kind == "text":
            content.append({"type": "input_text", "text": part["text"]})
        elif kind == "image":
            content.append({
                "type": "input_image",
                "image_url": f"data:{part['mime_type']};base64,{part['data']}",
            })
        else:
            raise ValueError(f"OpenAI 경로가 지원하지 않는 파트: {kind!r}")
    return [{"role": "user", "content": content}]


def _executor_for(lane: Lane):
    if lane == "chat":
        return CHAT_EXECUTOR
    if lane == "pipeline":
        return PIPELINE_EXECUTOR
    raise ValueError(f"unknown lane: {lane!r}")


async def call_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = MODEL_LUNA,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    store: bool = True,
    media_resolution: str | None = None,  # noqa: ARG001 - Gemini 전용, 시그니처 호환용
) -> dict:
    """한 번의 Responses API 호출. gemini_client.call_interaction과 동형.

    Raises:
        ValueError: store=False인데 previous_interaction_id를 넘긴 경우.
    """
    if not store and previous_interaction_id:
        raise ValueError("previous_interaction_id requires store=True")

    kwargs: dict[str, Any] = {
        "model": model,
        "input": _translate_parts(prompt),
        "instructions": system_instruction or _SYSTEM_INSTRUCTION_KO,
        "store": store,
    }
    if thinking_level:
        kwargs["reasoning"] = {"effort": thinking_level}
    if previous_interaction_id:
        kwargs["previous_response_id"] = previous_interaction_id
    if response_schema:
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": "sasoo_result",
                "schema": response_schema,
                "strict": False,  # 현행 스키마는 strict 제약(전 필드 required 등) 미충족
            }
        }

    def _do_call():
        resp = _get_client().responses.create(**kwargs)
        usage = getattr(resp, "usage", None)
        output_details = getattr(usage, "output_tokens_details", None)
        input_details = getattr(usage, "input_tokens_details", None)
        return {
            "text": getattr(resp, "output_text", "") or "",
            "model": model,
            # output_tokens는 reasoning 포함(R7-2) — 재합산 금지
            "tokens_in": getattr(usage, "input_tokens", 0) or 0,
            "tokens_out": getattr(usage, "output_tokens", 0) or 0,
            "tokens_thought": getattr(output_details, "reasoning_tokens", 0) or 0,  # 정보용
            "interaction_id": getattr(resp, "id", None),
            # 정보용(Task 12 캐시 적중률 집계) — gemini_client에는 대응 개념이 없다.
            "tokens_cached": getattr(input_details, "cached_tokens", 0) or 0,
        }

    loop = asyncio.get_running_loop()
    last_exc: Exception | None = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            if lane == "pipeline":
                async with pipeline_llm_sem():
                    return await loop.run_in_executor(PIPELINE_EXECUTOR, _do_call)
            return await loop.run_in_executor(_executor_for(lane), _do_call)
        except Exception as exc:  # noqa: BLE001 - CancelledError는 BaseException이라 통과
            last_exc = exc
            if attempt >= len(_RETRY_DELAYS) or not _is_retryable(exc):
                raise
            delay = _RETRY_DELAYS[attempt]
            logger.warning("openai call failed (%s), retrying in %ss", exc, delay)
            await asyncio.sleep(delay)

    raise last_exc  # 도달 불가 — 루프가 반드시 return 또는 raise 한다


async def stream_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = MODEL_LUNA,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    store: bool = False,
):
    """토큰 단위 스트리밍. gemini_client.stream_interaction과 같은 이벤트 계약.

    `{"type":"token","text":str}`를 토큰마다 yield하고, 마지막에
    `{"type":"done","tokens_in":int,"tokens_out":int,"tokens_thought":int,
    "interaction_id":str|None}`을 yield한다. gemini_client의 done 이벤트에는
    "model"·"tokens_cached" 키가 없으므로(대응 개념이 없음) 여기서도 넣지
    않는다 — call_interaction과 달리 이 done dict는 gemini와 바이트 단위로
    같은 키 집합이어야 셔션이 분기 없이 위임할 수 있다.

    SDK 스트림이 `response.completed` 없이 예외 없이 끝나면(gemini_client와
    같은 이유의 폴백) `tokens_in/out/thought=0, interaction_id=None`인 폴백
    done을 yield한다 — 안 그러면 프론트 onDone(비용 집계·액션 버튼)이 영영
    호출되지 않는다.

    동기 SDK 스트림은 스레드 풀에서 돌리고 asyncio.Queue로 브릿지해 이벤트
    루프를 막지 않는다(gemini_client와 같은 관용구, 큐 전달 방식만 다르다 —
    call_soon_threadsafe + put_nowait). 채팅은 stateless(store=False, 히스토리를
    텍스트로 조립)라 previous_interaction_id 같은 체인 인자는 받지 않는다.

    done 이전에 발생한 예외는 소비자에게 그대로 재던진다(폴백 done은 나가지
    않는다) — 채팅 라우트의 "첫 토큰 전 실패만 재시도" 정책(analysis_routes.py
    event_generator)이 이 예외에 의존한다.

    lane="pipeline"이면 gemini_client와 동형으로 스트림이 살아있는 전체 구간
    동안 `pipeline_llm_sem()` 슬롯 하나를 점유한다(429 방지, call_interaction의
    pipeline 분기와 동일 정책). chat lane은 세마포어를 쓰지 않는다.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "input": _translate_parts(prompt),
        "instructions": system_instruction or _SYSTEM_INSTRUCTION_KO,
        "store": store,
    }
    if thinking_level:
        kwargs["reasoning"] = {"effort": thinking_level}

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _produce():
        try:
            with _get_client().responses.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        loop.call_soon_threadsafe(
                            queue.put_nowait, {"type": "token", "text": event.delta})
                    elif event.type == "response.completed":
                        usage = getattr(event.response, "usage", None)
                        output_details = getattr(usage, "output_tokens_details", None)
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "type": "done",
                            # output_tokens는 reasoning 포함(R7-2) — 재합산 금지
                            "tokens_in": getattr(usage, "input_tokens", 0) or 0,
                            "tokens_out": getattr(usage, "output_tokens", 0) or 0,
                            "tokens_thought": getattr(output_details, "reasoning_tokens", 0) or 0,
                            "interaction_id": getattr(event.response, "id", None),
                        })
        except Exception as exc:  # noqa: BLE001 - 소비자에게 전달해 재시도 정책이 판단
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    # pipeline lane은 스트림이 살아있는 동안 세마포어 슬롯 하나를 점유한다
    # (gemini_client.stream_interaction과 동형 — 현재 루프 전용 세마포어라
    # 크로스루프 바인딩 문제가 없다).
    sem = pipeline_llm_sem() if lane == "pipeline" else None
    if sem is not None:
        await sem.acquire()
    try:
        future = loop.run_in_executor(_executor_for(lane), _produce)
        try:
            done_seen = False
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    if not done_seen:
                        yield {
                            "type": "done",
                            "tokens_in": 0,
                            "tokens_out": 0,
                            "tokens_thought": 0,
                            "interaction_id": None,
                        }
                    break
                if isinstance(item, Exception):
                    raise item
                if item.get("type") == "done":
                    done_seen = True
                yield item
        finally:
            await future
    finally:
        if sem is not None:
            sem.release()
