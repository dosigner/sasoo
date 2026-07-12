"""
Sasoo - LLM client helpers.
Shared utilities for calling Gemini APIs.
"""

import json


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
