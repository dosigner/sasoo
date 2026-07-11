"""
Sasoo - Gemini LLM Client
Shared google-genai wrapper with API-key loading, retries, and usage tracking.

Used by: naming_service, subfigure_detector, agents/generator.
(The main analysis pipeline uses api/analysis_helpers.py instead.)

Models:
  - gemini-3-flash-preview  : naming, vision (sub-figure detection)
  - gemini-3.1-pro-preview  : agent profile generation
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from google import genai
from google.genai import types

from services.pricing import calc_cost
from services.crypto import decrypt_value

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

from models.database import DB_PATH, CONFIG_PATH

# Model identifiers (re-exported from the single source of truth)
from services.models import MODEL_FLASH, MODEL_PRO  # noqa: F401

# Thinking budget by level
THINKING_BUDGETS: dict[str, int] = {
    "minimal": 1024,
    "medium": 4096,
    "high": 8192,
}


# ---------------------------------------------------------------------------
# Token / Cost tracking
# ---------------------------------------------------------------------------

@dataclass
class UsageRecord:
    """Single API call usage."""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    phase: str


@dataclass
class UsageTracker:
    """Cumulative token usage across a session."""
    records: list[UsageRecord] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)
        logger.info(
            "Gemini usage | model=%s phase=%s in=%d out=%d cost=$%.6f latency=%dms",
            record.model,
            record.phase,
            record.input_tokens,
            record.output_tokens,
            record.cost_usd,
            record.latency_ms,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "total_calls": len(self.records),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "by_phase": self._by_phase(),
        }

    def _by_phase(self) -> dict[str, dict[str, Any]]:
        phases: dict[str, dict[str, Any]] = {}
        for r in self.records:
            if r.phase not in phases:
                phases[r.phase] = {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            p = phases[r.phase]
            p["calls"] += 1
            p["input_tokens"] += r.input_tokens
            p["output_tokens"] += r.output_tokens
            p["cost_usd"] = round(p["cost_usd"] + r.cost_usd, 6)
        return phases


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_api_key() -> str:
    """
    Load Gemini API key from multiple sources (priority order):
    1. Environment variable GEMINI_API_KEY
    2. SQLite database settings table
    3. Legacy config.json file
    """
    import os
    import sqlite3

    # 1. Check environment variable first
    env_key = os.environ.get("GEMINI_API_KEY", "")
    if env_key:
        return env_key

    # 2. Check database settings
    db_path = DB_PATH
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute(
                "SELECT value FROM settings WHERE key = 'gemini_api_key'"
            )
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                key = decrypt_value(str(row[0]))
                if key:
                    return key
        except Exception as e:
            logger.warning(f"Failed to load API key from database: {e}")

    # 3. Fall back to config.json (legacy)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            key = decrypt_value(str(config.get("gemini_api_key", "")))
            if key:
                return key
        except Exception as e:
            logger.warning(f"Failed to load config.json: {e}")

    raise ValueError(
        "Gemini API key not found. Set it via:\n"
        "  1. Environment variable GEMINI_API_KEY\n"
        "  2. Settings page in the app\n"
        "  3. config.json file in library folder"
    )




def _extract_json(text: str) -> dict:
    """
    Parse JSON from model output.
    Handles responses wrapped in ```json ... ``` fences.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = cleaned.index("\n")
        cleaned = cleaned[first_newline + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse JSON from model output: %s", exc)
        logger.debug("Raw output:\n%s", text)
        return {"_raw": text, "_parse_error": str(exc)}


# ---------------------------------------------------------------------------
# GeminiClient
# ---------------------------------------------------------------------------

class GeminiClient:
    """
    Async client for all Gemini model interactions in Sasoo.

    Usage:
        client = GeminiClient()
        response = await client._call(model=MODEL_FLASH, contents=prompt)
        text = client._response_text(response)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or _load_api_key()
        self._client = genai.Client(api_key=self._api_key)
        self.usage = UsageTracker()

    # ------------------------------------------------------------------
    # Internal: generic call
    # ------------------------------------------------------------------

    async def _call(
        self,
        *,
        model: str,
        contents: list[types.Content] | list[types.Part] | str,
        system_instruction: Optional[str] = None,
        thinking_level: str = "medium",
        phase: str = "unknown",
        response_mime_type: Optional[str] = None,
    ) -> types.GenerateContentResponse:
        """
        Low-level call to Gemini with thinking budget, usage tracking,
        and automatic retries on transient errors.
        """
        thinking_config = types.ThinkingConfig(
            thinking_budget=THINKING_BUDGETS.get(thinking_level, 4096),
        )

        generation_config_kwargs: dict[str, Any] = {
            "thinking_config": thinking_config,
            "temperature": 1.0,  # Required when thinking is enabled
        }
        if response_mime_type:
            generation_config_kwargs["response_mime_type"] = response_mime_type

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            **generation_config_kwargs,
        )

        start = time.monotonic()
        last_error: Optional[Exception] = None

        for attempt in range(3):
            try:
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Gemini call attempt %d/%d failed: %s",
                    attempt + 1,
                    3,
                    exc,
                )
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
        else:
            raise RuntimeError(
                f"Gemini call failed after 3 attempts: {last_error}"
            ) from last_error

        latency_ms = (time.monotonic() - start) * 1000

        # Extract usage metadata
        input_tokens = 0
        output_tokens = 0
        if response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0

        cost = calc_cost(model, input_tokens, output_tokens)
        self.usage.add(UsageRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=round(latency_ms, 1),
            phase=phase,
        ))

        return response

    def _response_text(self, response: types.GenerateContentResponse) -> str:
        """Extract text from a Gemini response, concatenating all text parts."""
        parts = []
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text:
                            parts.append(part.text)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Image-based generation (for sub-figure detection etc.)
    # ------------------------------------------------------------------

    async def generate_with_image(
        self,
        prompt: str,
        image_base64: str,
        image_mime_type: str = "image/png",
        model: str = MODEL_FLASH,
        system_prompt: Optional[str] = None,
        thinking_level: str = "minimal",
        phase: str = "vision",
    ) -> str:
        """
        Generate text response from image + prompt.

        Args:
            prompt: Text prompt describing what to analyze.
            image_base64: Base64-encoded image data.
            image_mime_type: MIME type of the image.
            model: Model to use (default: Flash for speed).
            system_prompt: Optional system instruction.
            thinking_level: Thinking budget level.
            phase: Phase name for usage tracking.

        Returns:
            Generated text response.
        """
        # Decode base64 to bytes
        image_bytes = base64.b64decode(image_base64)

        parts: list[types.Part] = [
            types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type),
            types.Part.from_text(text=prompt),
        ]

        content = [types.Content(parts=parts, role="user")]

        response = await self._call(
            model=model,
            contents=content,
            system_instruction=system_prompt,
            thinking_level=thinking_level,
            phase=phase,
        )

        return self._response_text(response)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_usage_summary(self) -> dict[str, Any]:
        """Return cumulative usage summary."""
        return self.usage.summary()
