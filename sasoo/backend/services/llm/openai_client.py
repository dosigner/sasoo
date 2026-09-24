"""Sasoo - OpenAI Responses API 클라이언트.

gemini_client.call_interaction과 같은 시그니처·같은 반환 dict를 유지한다 —
셔션(interactions_client)이 분기 없이 위임하기 위해서다. 개념 번역:

    previous_interaction_id  ->  previous_response_id
    thinking_level           ->  reasoning.effort
    media_resolution         ->  (무시 - Gemini 전용)

Local PDF bytes are sent as inline input_file parts. Output token totals already
include reasoning tokens, so they are never added a second time.
"""

import asyncio
import base64
import hashlib
import logging
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, TypedDict

import anyio
from openai.types.responses import Response
from openai.types.responses.input_token_count_params import InputTokenCountParams

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


class PDFInputError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def load_pdf_part(pdf_path: Path) -> dict[str, str]:
    """Read a bounded local PDF and keep its source hash outside the wire input."""
    size = pdf_path.stat().st_size
    if not 0 < size < 50_000_000:
        raise PDFInputError(f"PDF size must be between 1 and 49,999,999 bytes: {size}")
    data = pdf_path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) >= 50_000_000:
        raise PDFInputError(f"Invalid PDF input: {pdf_path.name}")
    return {
        "type": "document", "mime_type": "application/pdf",
        "filename": pdf_path.name, "data": base64.b64encode(data).decode("ascii"),
        "detail": "high", "sha256": hashlib.sha256(data).hexdigest(),
    }


def _translate_parts(prompt) -> Any:
    """Translate local media parts; provider-owned document URIs are rejected."""
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
        elif kind == "document":
            if (part.get("uri") is not None or part.get("mime_type") != "application/pdf"
                    or not part.get("data") or not part.get("filename")):
                raise PDFInputError(f"OpenAI requires an inline PDF document: {kind!r}")
            content.append({
                "type": "input_file", "filename": part["filename"],
                "file_data": f"data:application/pdf;base64,{part['data']}",
                "detail": "high",
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


def _build_request(
    prompt: str | list[dict[str, str]],
    *,
    model: str,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    strict_schema: bool = False,
) -> InputTokenCountParams:
    """Build the model-input fields shared by count, create, and stream."""
    kwargs: InputTokenCountParams = {
        "model": model,
        "input": _translate_parts(prompt),
        "instructions": system_instruction or _SYSTEM_INSTRUCTION_KO,
    }
    if thinking_level:
        kwargs["reasoning"] = {"effort": thinking_level}
    if previous_interaction_id:
        kwargs["previous_response_id"] = previous_interaction_id
    if response_schema:
        wire_schema = deepcopy(response_schema) if strict_schema else response_schema
        if strict_schema:
            pending = [wire_schema]
            while pending:
                node = pending.pop()
                properties = node.get("properties", {})
                if node.get("type") == "object":
                    node["additionalProperties"] = False
                    node["required"] = list(properties)
                pending.extend(properties.values())
                if "items" in node:
                    pending.append(node["items"])
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": "sasoo_result",
                "schema": wire_schema,
                "strict": strict_schema,
            }
        }
    return kwargs


async def count_input_tokens(
    prompt: str | list[dict[str, str]],
    *,
    model: str,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    strict_schema: bool = False,
) -> int:
    """Count the same model input used by generation, without creating a response."""
    kwargs = _build_request(
        prompt, model=model, system_instruction=system_instruction,
        thinking_level=thinking_level, previous_interaction_id=previous_interaction_id,
        response_schema=response_schema, strict_schema=strict_schema,
    )

    def _count() -> int:
        return _get_client().responses.input_tokens.count(**kwargs).input_tokens

    return await anyio.to_thread.run_sync(_count)


class ResponseMetadata(TypedDict):
    model: str
    response_model: str | None
    response_status: str | None
    incomplete: bool
    incomplete_reason: str | None
    service_tier: str | None
    tokens_in: int | None
    tokens_out: int | None
    tokens_thought: int | None
    tokens_cached: int | None
    tokens_cache_write: int | None
    interaction_id: str | None
    usage_complete: bool


def _response_metadata(response: Response | None, *, model: str) -> ResponseMetadata:
    """Preserve provider usage; missing counts must not become zero-cost success."""
    usage = getattr(response, "usage", None)
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    status = getattr(response, "status", None)
    tokens_in = getattr(usage, "input_tokens", None)
    tokens_out = getattr(usage, "output_tokens", None)
    return {
        "model": model,
        "response_model": getattr(response, "model", None),
        "response_status": status,
        "incomplete": response is None or status in ("incomplete", "failed", "cancelled"),
        "incomplete_reason": (
            "missing_completion" if response is None
            else getattr(getattr(response, "incomplete_details", None), "reason", None)
        ),
        "service_tier": getattr(response, "service_tier", None),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_thought": getattr(output_details, "reasoning_tokens", None),
        "tokens_cached": getattr(input_details, "cached_tokens", None),
        "tokens_cache_write": getattr(input_details, "cache_write_tokens", None),
        "interaction_id": getattr(response, "id", None),
        "usage_complete": tokens_in is not None and tokens_out is not None,
    }


async def call_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = MODEL_LUNA,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    strict_schema: bool = False,
    store: bool = True,
    media_resolution: str | None = None,
    max_output_tokens: int | None = None,
    single_attempt: bool = False,
    service_tier: str | None = None,
) -> dict:
    """Generate once, with optional validation controls over tier and retries."""
    if not store and previous_interaction_id:
        raise ValueError("previous_interaction_id requires store=True")
    kwargs = {**_build_request(
        prompt, model=model, system_instruction=system_instruction,
        thinking_level=thinking_level, previous_interaction_id=previous_interaction_id,
        response_schema=response_schema, strict_schema=strict_schema,
    ), "store": store}
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    if service_tier is not None:
        kwargs["service_tier"] = service_tier

    def _do_call():
        client = _get_client()
        if single_attempt:
            client = client.with_options(max_retries=0)
        resp = client.responses.create(**kwargs)
        return {
            "text": getattr(resp, "output_text", "") or "",
            **_response_metadata(resp, model=model),
        }

    loop = asyncio.get_running_loop()
    last_exc: Exception | None = None
    retry_delays = [] if single_attempt else _RETRY_DELAYS
    for attempt in range(len(retry_delays) + 1):
        try:
            if lane == "pipeline":
                async with pipeline_llm_sem():
                    return await loop.run_in_executor(PIPELINE_EXECUTOR, _do_call)
            return await loop.run_in_executor(_executor_for(lane), _do_call)
        except Exception as exc:  # noqa: BLE001 - CancelledError는 BaseException이라 통과
            last_exc = exc
            if not _is_retryable(exc):
                # gemini_client와 동형 래핑 — 셔션 배선 이후 소비자(analysis_routes 등)가
                # 두 provider를 구분 없이 다루므로 예외 타입도 맞춰야 한다.
                raise RuntimeError(
                    f"OpenAI call failed (non-retryable): {exc}"
                ) from exc
            if attempt < len(retry_delays):
                delay = retry_delays[attempt]
                logger.warning("openai call failed (%s), retrying in %ss", exc, delay)
                await asyncio.sleep(delay)

    raise RuntimeError(f"OpenAI call failed after retries: {last_exc}") from last_exc


async def stream_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = MODEL_LUNA,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    store: bool = False,
    max_output_tokens: int | None = None,
    single_attempt: bool = False,
    service_tier: str | None = None,
):
    """Yield token/done events; absent completion keeps usage unknown and fails closed."""
    kwargs = {**_build_request(
        prompt, model=model, system_instruction=system_instruction,
        thinking_level=thinking_level,
    ), "store": store}
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    if service_tier is not None:
        kwargs["service_tier"] = service_tier

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _produce():
        try:
            client = _get_client()
            if single_attempt:
                client = client.with_options(max_retries=0)
            with client.responses.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        loop.call_soon_threadsafe(
                            queue.put_nowait, {"type": "token", "text": event.delta})
                    elif event.type in ("response.completed", "response.incomplete", "response.failed"):
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "type": "done",
                            **_response_metadata(event.response, model=model),
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
                            **_response_metadata(None, model=model),
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
