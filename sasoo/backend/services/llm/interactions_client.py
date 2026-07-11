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
                return {
                    "text": interaction.output_text or "",
                    "model": model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "interaction_id": getattr(interaction, "id", None),
                }
            except Exception as exc:  # noqa: BLE001 - 재시도 후 재던짐
                last_err = exc
                if attempt < len(_RETRY_DELAYS):
                    import time
                    time.sleep(_RETRY_DELAYS[attempt])
        raise RuntimeError(f"Interactions API call failed after retries: {last_err}")

    return await asyncio.get_event_loop().run_in_executor(None, _sync_call)


async def upload_pdf_for_paper(paper_id: int, pdf_path: str) -> str:
    """PDF를 Files API에 업로드하고 papers 테이블에 uri/만료를 캐시한다."""
    from models.database import fetch_one, execute_update

    row = await fetch_one(
        "SELECT pdf_file_uri, pdf_file_expires_at FROM papers WHERE id = ?", (paper_id,)
    )
    now = datetime.now(timezone.utc)
    if row and row["pdf_file_uri"] and row["pdf_file_expires_at"]:
        try:
            expires = datetime.fromisoformat(row["pdf_file_expires_at"])
            if expires > now:
                return row["pdf_file_uri"]
        except ValueError:
            pass

    def _sync_upload():
        client = _get_client()
        uploaded = client.files.upload(file=pdf_path)
        return uploaded.uri

    uri = await asyncio.get_event_loop().run_in_executor(None, _sync_upload)
    await execute_update(
        "UPDATE papers SET pdf_file_uri = ?, pdf_file_expires_at = ? WHERE id = ?",
        (uri, (now + _FILE_TTL).isoformat(), paper_id),
    )
    return uri
