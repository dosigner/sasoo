"""
Sasoo - LLM client helpers.
Shared utilities for calling the Gemini API.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from services.concurrency import PIPELINE_EXECUTOR, PIPELINE_LLM_SEM
from services.models import MODEL_FLASH

logger = logging.getLogger(__name__)

# Transient failures (rate limits, 5xx) are common enough that a single-shot
# call drops whole analysis phases. There is no cross-vendor fallback anymore,
# so this retry is the only thing standing between a blip and a failed run.
_MAX_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTION_KO = (
    "너는 Sasoo(사수)라는 한국어 AI 연구 보조원이야. "
    "모든 출력 텍스트를 반드시 한국어로 작성해. "
    "JSON key 이름만 영어로 유지하고, 모든 value(문장, 설명, 리스트 항목 등)는 한국어로 써. "
    "영어로 쓰지 마."
)


# ---------------------------------------------------------------------------
# LLM Client Helpers
# ---------------------------------------------------------------------------

def _get_gemini_client():
    """Lazy-load Gemini client."""
    try:
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        client = genai.Client(api_key=api_key)
        return client
    except ImportError:
        raise RuntimeError("google-genai package not installed")


# ---------------------------------------------------------------------------
# Gemini call helper
# ---------------------------------------------------------------------------

async def _call_gemini(
    prompt: str,
    model: str = MODEL_FLASH,
    thinking_level: str | None = None,
    image_paths: list[str] | None = None,
) -> dict:
    """
    Call Gemini API and return parsed response with token counts.
    Runs synchronous SDK call in executor to avoid blocking.
    Retries transient failures with exponential backoff.

    thinking_level: "minimal" (1024), "medium" (4096), "high" (8192), or None.
    image_paths: Optional list of absolute paths to images to include in the request.
    """
    def _sync_call():
        from google.genai import types as _gtypes
        client = _get_gemini_client()

        config_kwargs: dict = {
            "system_instruction": _SYSTEM_INSTRUCTION_KO,
        }
        if thinking_level:
            budgets = {"minimal": 1024, "medium": 4096, "high": 8192}
            config_kwargs["thinking_config"] = _gtypes.ThinkingConfig(
                thinking_budget=budgets.get(thinking_level, 4096),
            )
            config_kwargs["temperature"] = 1.0  # Required when thinking is enabled

        # Build multimodal content if image_paths provided
        if image_paths:
            parts: list[_gtypes.Part] = []
            for img_path in image_paths:
                img_file = Path(img_path)
                if img_file.exists():
                    img_bytes = img_file.read_bytes()
                    suffix = img_file.suffix.lower()
                    mime_map = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                    }
                    mime_type = mime_map.get(suffix, "image/png")
                    parts.append(_gtypes.Part.from_bytes(data=img_bytes, mime_type=mime_type))
            parts.append(_gtypes.Part.from_text(text=prompt))
            contents = [_gtypes.Content(parts=parts, role="user")]
        else:
            contents = prompt

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=_gtypes.GenerateContentConfig(**config_kwargs),
        )
        text = response.text or ""
        # Extract usage if available
        usage = getattr(response, "usage_metadata", None)
        tokens_in = getattr(usage, "prompt_token_count", 0) if usage else 0
        tokens_out = getattr(usage, "candidates_token_count", 0) if usage else 0
        return {
            "text": text,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    loop = asyncio.get_running_loop()
    last_error: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            # The semaphore bounds how many phase calls are in flight at once;
            # the dedicated pool keeps them off the executor chat depends on.
            async with PIPELINE_LLM_SEM:
                return await loop.run_in_executor(PIPELINE_EXECUTOR, _sync_call)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Gemini call failed (model=%s, attempt %d/%d): %s",
                model, attempt + 1, _MAX_ATTEMPTS, exc,
            )
            if attempt < _MAX_ATTEMPTS - 1:
                await asyncio.sleep(2 ** attempt)

    raise RuntimeError(
        f"Gemini call failed after {_MAX_ATTEMPTS} attempts (model={model}): {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _clean_llm_json(text: str) -> str:
    """
    Strip markdown code fences from LLM JSON responses.
    LLMs often return ```json ... ``` wrapped responses.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove opening fence (```json or ```)
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _is_error_result(text: str) -> bool:
    """Check if an LLM result text indicates an error."""
    if not text or not text.strip():
        return True
    try:
        data = json.loads(text)
        return "_parse_error" in data or "error" in data
    except (json.JSONDecodeError, TypeError):
        return False
