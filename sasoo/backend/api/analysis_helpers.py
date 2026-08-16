"""
Sasoo - LLM client helpers.
Shared utilities for calling Gemini APIs.
"""

import json
import zlib
from typing import Optional


# ---------------------------------------------------------------------------
# System instruction
# ---------------------------------------------------------------------------

from services.llm.interactions_client import _SYSTEM_INSTRUCTION_KO  # noqa: F401 - 단일 소스 재노출


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


# ---------------------------------------------------------------------------
# Degenerate repetition detection
# ---------------------------------------------------------------------------

# 반복 루프에 빠진 출력은 소수 단어의 순열이 수백 번 되풀이되므로
# 단어 다양성이 극단적으로 낮다. 자연어(한국어·영어)는 50단어 창에서
# 고유 비율이 통상 0.4 이상이라 0.15는 안전한 여유를 가진다.
_DEGEN_WINDOW = 50
_DEGEN_UNIQUE_RATIO = 0.15
_DEGEN_MIN_CHARS = 300
_DEGEN_ZLIB_MIN_BYTES = 500
_DEGEN_ZLIB_RATIO = 0.05


def _is_degenerate_string(text: str) -> bool:
    """문자열이 LLM 반복 루프(degenerate repetition) 출력인지 판정한다."""
    if len(text) < _DEGEN_MIN_CHARS:
        return False
    raw = text.encode("utf-8")
    # 공백 없이 이어지는 반복까지 잡는 언어 무관 검사 — 루프 출력은 극단적으로 잘 압축된다
    if len(raw) >= _DEGEN_ZLIB_MIN_BYTES:
        if len(zlib.compress(raw, 6)) / len(raw) < _DEGEN_ZLIB_RATIO:
            return True
    words = text.split()
    if len(words) < _DEGEN_WINDOW:
        return False
    # 정상 서술 뒤에 루프가 붙는 경우가 있어 슬라이딩 창으로 국소 구간을 본다
    step = _DEGEN_WINDOW // 2
    for i in range(0, len(words) - _DEGEN_WINDOW + 1, step):
        window = words[i:i + _DEGEN_WINDOW]
        if len(set(window)) / len(window) < _DEGEN_UNIQUE_RATIO:
            return True
    return False


def _has_degenerate_repetition(data) -> bool:
    """파싱된 JSON 값 전체를 훑어 반복 루프에 오염된 문자열 필드를 찾는다."""
    if isinstance(data, str):
        return _is_degenerate_string(data)
    if isinstance(data, dict):
        return any(_has_degenerate_repetition(v) for v in data.values())
    if isinstance(data, list):
        return any(_has_degenerate_repetition(v) for v in data)
    return False


def _stage_result_defect(text: str) -> Optional[str]:
    """스테이지 결과 텍스트의 재시도 사유를 찾는다. 정상이면 None.

    JSON 파싱 실패뿐 아니라, 파싱은 되지만 필드 값 안에서 반복 루프가
    발생한 경우(스키마 강제 출력을 통과하는 오염)도 잡는다."""
    try:
        parsed = json.loads(_clean_llm_json(text or ""))
    except (json.JSONDecodeError, TypeError):
        return "JSON parse failed"
    if _has_degenerate_repetition(parsed):
        return "degenerate repetition detected"
    return None


def _last_complete_value_cut(text: str):
    """값 경계에서 자를 수 있는 마지막 위치와 그때 열려 있던 컨테이너를 찾는다.

    반환: (cut_index, open_stack) 또는 None. cut_index 앞까지가 온전한 JSON 조각이고,
    open_stack을 뒤에서부터 닫으면 파싱 가능한 문서가 된다.
    """
    stack: list[str] = []
    in_string = False
    escape = False
    best: tuple[int, list[str]] | None = None

    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                return None
            stack.pop()
            # 컨테이너 하나가 온전히 닫혔다 — 여기까지는 확실히 유효하다
            best = (i + 1, list(stack))
        elif ch == ",":
            # 직전 값이 끝났다는 뜻 — 쉼표 앞에서 자른다
            best = (i, list(stack))
    return best


def _prune_incomplete_items(value, schema):
    """스키마의 required를 못 채운 배열 항목을 버린다. 값을 채워 넣지는 않는다."""
    if not isinstance(schema, dict):
        return value
    if schema.get("type") == "array" and isinstance(value, list):
        item_schema = schema.get("items") or {}
        required = item_schema.get("required") or []
        kept = []
        for item in value:
            if required and not (isinstance(item, dict) and all(k in item for k in required)):
                continue
            kept.append(_prune_incomplete_items(item, item_schema))
        return kept
    if schema.get("type") == "object" and isinstance(value, dict):
        props = schema.get("properties") or {}
        return {k: _prune_incomplete_items(v, props.get(k, {})) for k, v in value.items()}
    return value


def salvage_truncated_json(text: str, schema: dict) -> Optional[str]:
    """출력 상한에 걸려 잘린 JSON에서 온전히 끝난 부분만 되살린다.

    되살릴 수 없으면 None. 그때는 호출부가 기존처럼 재시도하거나 실패로 둔다.

    규칙 하나뿐이다. **쓰다 만 값은 절대 채우지 않는다.** 값 경계에서만 자르고,
    스키마의 required를 못 채운 항목은 버린다. 필수 필드가 잘려 나갔거나 필수
    배열이 비면 되살리지 않는다 — 빈 껍데기를 성공으로 저장하는 게 실패보다 나쁘다.
    """
    cleaned = _clean_llm_json(text or "")
    if not cleaned.strip():
        return None
    try:
        json.loads(cleaned)
        return None  # 멀쩡하다. 되살릴 게 없다.
    except (json.JSONDecodeError, TypeError):
        pass

    cut = _last_complete_value_cut(cleaned)
    if cut is None:
        return None
    index, stack = cut
    closers = "".join("}" if ch == "{" else "]" for ch in reversed(stack))
    try:
        parsed = json.loads(cleaned[:index] + closers)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None

    parsed = _prune_incomplete_items(parsed, schema)

    props = (schema or {}).get("properties") or {}
    for key in (schema or {}).get("required") or []:
        if key not in parsed:
            return None
        if (props.get(key, {}).get("type") == "array") and not parsed[key]:
            return None
    return json.dumps(parsed, ensure_ascii=False)


def _is_error_result(text: str) -> bool:
    """Check if an LLM result text indicates an error."""
    if not text or not text.strip():
        return True
    try:
        data = json.loads(text)
        return "_parse_error" in data or "error" in data
    except (json.JSONDecodeError, TypeError):
        return False
