"""Sasoo - Gemini Interactions API client layer.

generate_content을 대체한다. types.* 래퍼 없이 plain dict만 사용.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from services.concurrency import CHAT_EXECUTOR, PIPELINE_EXECUTOR, pipeline_llm_sem

logger = logging.getLogger(__name__)

# 모든 호출은 lane을 명시해야 한다 — 기본값을 두지 않는 것이 핵심이다.
# asyncio 기본 풀을 암묵적으로 쓰다가 파이프라인 팬아웃이 풀을 채우면
# 채팅 SSE가 스레드를 못 잡고 무한 대기하는 사고(2026-07-11)의 재발 방지.
#   "chat"     : 사용자가 실시간으로 기다리는 대화형 경로. 전용 풀, 세마포어 없음.
#   "pipeline" : 분석 파이프라인. 전용 풀 + 루프별 pipeline_llm_sem()으로 동시 호출 제한.
Lane = Literal["chat", "pipeline"]


def _executor_for(lane: Lane):
    if lane == "chat":
        return CHAT_EXECUTOR
    if lane == "pipeline":
        return PIPELINE_EXECUTOR
    raise ValueError(f"unknown lane: {lane!r}")


async def _run_on_lane(lane: Lane, fn):
    loop = asyncio.get_running_loop()
    if lane == "pipeline":
        # 현재 루프 전용 세마포어(크로스루프 바인딩 방지 — concurrency.pipeline_llm_sem 참조).
        async with pipeline_llm_sem():
            return await loop.run_in_executor(PIPELINE_EXECUTOR, fn)
    return await loop.run_in_executor(_executor_for(lane), fn)

_SYSTEM_INSTRUCTION_KO = (
    "너는 Sasoo(사수)라는 한국어 AI 연구 보조원이야. "
    "모든 출력 텍스트를 반드시 한국어로 작성해. "
    "JSON key 이름만 영어로 유지하고, 모든 value(문장, 설명, 리스트 항목 등)는 한국어로 써. "
    "영어로 쓰지 마."
)

_RETRY_DELAYS = [2, 8]  # 3회 시도, 지수 백오프
_FILE_TTL = timedelta(hours=47)  # Files API 48h에서 1h 여유

_upload_locks: dict[int, asyncio.Lock] = {}


def _get_client():
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def _apply_media_resolution(prompt, media_resolution: str | None):
    """image 파트에 media_resolution(resolution)을 주입한 새 input을 반환.

    media_resolution이 없거나 prompt가 파트 리스트가 아니면 원본을 그대로 반환한다.
    Interactions API의 ImageContentParam.resolution(low/medium/high/ultra_high)에
    대응한다 — 저해상 입력으로 이미지 토큰을 줄이는 통로. 이미지가 없는 기존
    호출부(예: 채팅 텍스트 호출)는 무영향이며, 원본 파트 dict은 변형하지 않는다.
    """
    if not media_resolution or not isinstance(prompt, list):
        return prompt
    new_parts = []
    changed = False
    for part in prompt:
        if isinstance(part, dict) and part.get("type") == "image" and "resolution" not in part:
            part = {**part, "resolution": media_resolution}
            changed = True
        new_parts.append(part)
    return new_parts if changed else prompt


async def call_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = "gemini-3.5-flash",
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    store: bool = True,
    media_resolution: str | None = None,
) -> dict:
    if not store and previous_interaction_id:
        raise ValueError("previous_interaction_id requires store=True")

    def _sync_call():
        client = _get_client()
        kwargs: dict = {
            "model": model,
            "input": _apply_media_resolution(prompt, media_resolution),
            "system_instruction": system_instruction or _SYSTEM_INSTRUCTION_KO,
            "store": store,
        }
        if thinking_level:
            kwargs["generation_config"] = {"thinking_level": thinking_level}
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id
        if response_schema:
            # VERIFY(확인됨): structured-output.md.txt 기준 response_format 단일 객체.
            kwargs["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": response_schema,
            }

        last_err: Exception | None = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                interaction = client.interactions.create(**kwargs)
                usage = getattr(interaction, "usage", None)
                # VERIFY(확인됨): interactions.md.txt 기준 usage.total_input_tokens / total_output_tokens.
                tokens_in = getattr(usage, "total_input_tokens", 0) or 0
                # 라이브 실측: total_output_tokens는 thinking 미포함, 과금은
                # 출력 단가 — 합산해 청구 기준으로 반환한다.
                tokens_thought = getattr(usage, "total_thought_tokens", 0) or 0
                tokens_out = (getattr(usage, "total_output_tokens", 0) or 0) + tokens_thought
                return {
                    "text": interaction.output_text or "",
                    "model": model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "tokens_thought": tokens_thought,
                    "interaction_id": getattr(interaction, "id", None),
                }
            except Exception as exc:  # noqa: BLE001 - 재시도 후 재던짐
                last_err = exc
                if attempt < len(_RETRY_DELAYS):
                    import time
                    time.sleep(_RETRY_DELAYS[attempt])
        raise RuntimeError(f"Interactions API call failed after retries: {last_err}")

    return await _run_on_lane(lane, _sync_call)


async def stream_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = "gemini-3.5-flash",
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    store: bool = True,
):
    """Interactions API 스트리밍 래퍼.

    `{"type":"token","text":str}`를 토큰마다 yield하고, 마지막에
    `{"type":"done","tokens_in":int,"tokens_out":int,"tokens_thought":int,"interaction_id":str|None}`
    를 yield한다. sync SDK 스트림은 스레드에서 돌리고 asyncio.Queue로 브릿지해
    이벤트 루프를 막지 않는다(기존 채팅 엔드포인트의 관용구 이동).
    스트림 중 오류는 RuntimeError로 전파한다.
    SDK 스트림이 interaction.completed 이벤트 없이 정상 종료하면 폴백 done
    (`tokens_in/out/thought=0, interaction_id=None`)을 yield해 소비자가
    항상 종료 신호를 받도록 보장한다.
    """
    if not store and previous_interaction_id:
        raise ValueError("previous_interaction_id requires store=True")

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def _sync_stream():
        try:
            client = _get_client()
            kwargs: dict = {
                "model": model,
                "input": prompt,
                "system_instruction": system_instruction or _SYSTEM_INSTRUCTION_KO,
                "store": store,
                "stream": True,
            }
            if thinking_level:
                kwargs["generation_config"] = {"thinking_level": thinking_level}
            if previous_interaction_id:
                kwargs["previous_interaction_id"] = previous_interaction_id

            for event in client.interactions.create(**kwargs):
                # VERIFY(확인됨, streaming.md.txt): 텍스트 토큰은
                # event.event_type == "step.delta" + event.delta.type == "text" + event.delta.text.
                event_type = getattr(event, "event_type", None)
                if event_type == "step.delta":
                    delta = getattr(event, "delta", None)
                    if delta is not None and getattr(delta, "type", None) == "text":
                        text = getattr(delta, "text", "") or ""
                        if text:
                            asyncio.run_coroutine_threadsafe(q.put(("token", text)), loop)
                elif event_type == "interaction.completed":
                    # VERIFY(확인됨, streaming.md.txt): 종료는 interaction.completed +
                    # event.interaction.usage.total_input_tokens / total_output_tokens /
                    # total_thought_tokens, id는 event.interaction.id.
                    interaction = getattr(event, "interaction", None)
                    usage = getattr(interaction, "usage", None)
                    # 라이브 실측: total_output_tokens는 thinking 미포함, 과금은
                    # 출력 단가 — 합산해 청구 기준으로 반환한다.
                    _tokens_thought = getattr(usage, "total_thought_tokens", 0) or 0
                    asyncio.run_coroutine_threadsafe(
                        q.put((
                            "done",
                            {
                                "tokens_in": getattr(usage, "total_input_tokens", 0) or 0,
                                "tokens_out": (getattr(usage, "total_output_tokens", 0) or 0)
                                + _tokens_thought,
                                "tokens_thought": _tokens_thought,
                                "interaction_id": getattr(interaction, "id", None),
                            },
                        )),
                        loop,
                    )
        except Exception as exc:  # noqa: BLE001 - 소비자에게 전파
            asyncio.run_coroutine_threadsafe(q.put(("error", str(exc))), loop)
        finally:
            asyncio.run_coroutine_threadsafe(q.put(("__end__", None)), loop)

    # pipeline lane은 스트림이 살아있는 동안 세마포어 슬롯 하나를 점유한다.
    # 현재 루프 전용 세마포어를 쓴다(크로스루프 바인딩 방지).
    sem = pipeline_llm_sem() if lane == "pipeline" else None
    if sem is not None:
        await sem.acquire()
    try:
        loop.run_in_executor(_executor_for(lane), _sync_stream)

        done_seen = False
        while True:
            kind, data = await q.get()
            if kind == "token":
                yield {"type": "token", "text": data}
            elif kind == "done":
                done_seen = True
                yield {"type": "done", **data}
            elif kind == "error":
                raise RuntimeError(f"Interactions API stream failed: {data}")
            else:  # "__end__"
                if not done_seen:
                    # SDK 스트림이 interaction.completed 없이 정상 종료한 경우
                    # (예: 서버가 종료 이벤트를 누락) — done 없이 조용히 끝나면
                    # 프론트 onDone(비용 집계·액션 버튼)이 영영 호출되지 않는다.
                    # 폴백 done을 yield해 소비자가 항상 종료를 인지하게 한다.
                    yield {
                        "type": "done",
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "tokens_thought": 0,
                        "interaction_id": None,
                    }
                break
    finally:
        if sem is not None:
            sem.release()


async def _cached_pdf_uri(paper_id: int) -> str | None:
    """캐시된 pdf_file_uri가 아직 유효하면 반환, 아니면 None."""
    from models.database import fetch_one

    row = await fetch_one(
        "SELECT pdf_file_uri, pdf_file_expires_at FROM papers WHERE id = ?", (paper_id,)
    )
    if row and row["pdf_file_uri"] and row["pdf_file_expires_at"]:
        now = datetime.now(timezone.utc)
        try:
            expires = datetime.fromisoformat(row["pdf_file_expires_at"])
            if expires > now:
                return row["pdf_file_uri"]
        except (ValueError, TypeError):
            pass
    return None


async def upload_pdf_for_paper(paper_id: int, pdf_path: str) -> str:
    """PDF를 Files API에 업로드하고 papers 테이블에 uri/만료를 캐시한다.

    같은 paper_id에 대한 동시 호출은 paper별 락으로 직렬화해 중복 업로드를 막는다.
    """
    from models.database import execute_update

    cached = await _cached_pdf_uri(paper_id)
    if cached:
        return cached

    lock = _upload_locks.setdefault(paper_id, asyncio.Lock())
    async with lock:
        # double-checked locking: 락 대기 중 다른 호출이 이미 업로드했을 수 있음
        cached = await _cached_pdf_uri(paper_id)
        if cached:
            return cached

        def _sync_upload():
            client = _get_client()
            uploaded = client.files.upload(file=pdf_path)
            return uploaded.uri

        uri = await asyncio.get_running_loop().run_in_executor(PIPELINE_EXECUTOR, _sync_upload)
        now = datetime.now(timezone.utc)
        await execute_update(
            "UPDATE papers SET pdf_file_uri = ?, pdf_file_expires_at = ? WHERE id = ?",
            (uri, (now + _FILE_TTL).isoformat(), paper_id),
        )
        return uri
