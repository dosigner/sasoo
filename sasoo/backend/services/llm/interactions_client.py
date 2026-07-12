"""Sasoo - Gemini Interactions API client layer.

generate_content을 대체한다. types.* 래퍼 없이 plain dict만 사용.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

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


async def call_interaction(
    prompt,
    *,
    model: str = "gemini-3.5-flash",
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    store: bool = True,
) -> dict:
    if not store and previous_interaction_id:
        raise ValueError("previous_interaction_id requires store=True")

    def _sync_call():
        client = _get_client()
        kwargs: dict = {
            "model": model,
            "input": prompt,
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
                tokens_out = getattr(usage, "total_output_tokens", 0) or 0
                # 비용 breakdown용으로만 기록 — output에 thinking 포함 여부가
                # 라이브 확인 전이므로 tokens_out에 합산하지 않는다.
                tokens_thought = getattr(usage, "total_thought_tokens", 0) or 0
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

    return await asyncio.get_event_loop().run_in_executor(None, _sync_call)


async def stream_interaction(
    prompt,
    *,
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
                    asyncio.run_coroutine_threadsafe(
                        q.put((
                            "done",
                            {
                                "tokens_in": getattr(usage, "total_input_tokens", 0) or 0,
                                "tokens_out": getattr(usage, "total_output_tokens", 0) or 0,
                                "tokens_thought": getattr(usage, "total_thought_tokens", 0) or 0,
                                "interaction_id": getattr(interaction, "id", None),
                            },
                        )),
                        loop,
                    )
        except Exception as exc:  # noqa: BLE001 - 소비자에게 전파
            asyncio.run_coroutine_threadsafe(q.put(("error", str(exc))), loop)
        finally:
            asyncio.run_coroutine_threadsafe(q.put(("__end__", None)), loop)

    loop.run_in_executor(None, _sync_stream)

    while True:
        kind, data = await q.get()
        if kind == "token":
            yield {"type": "token", "text": data}
        elif kind == "done":
            yield {"type": "done", **data}
        elif kind == "error":
            raise RuntimeError(f"Interactions API stream failed: {data}")
        else:  # "__end__"
            break


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

        uri = await asyncio.get_event_loop().run_in_executor(None, _sync_upload)
        now = datetime.now(timezone.utc)
        await execute_update(
            "UPDATE papers SET pdf_file_uri = ?, pdf_file_expires_at = ? WHERE id = ?",
            (uri, (now + _FILE_TTL).isoformat(), paper_id),
        )
        return uri
