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


def _prune_degenerate(value, schema):
    """반복 루프에 오염된 값을 떨어낸다. 반환 (정리된 값, 살릴 수 있는가).

    되살리기와 같은 선을 지킨다 — required가 오염되면 떨어내지 않고 실패로 둔다.
    필수 필드를 지운 빈 껍데기를 성공으로 저장하는 게 실패보다 나쁘다.
    """
    if isinstance(value, str):
        return (None, False) if _is_degenerate_string(value) else (value, True)

    if isinstance(value, list):
        item_schema = (schema or {}).get("items") or {}
        kept = []
        for item in value:
            pruned, ok = _prune_degenerate(item, item_schema)
            if ok:
                kept.append(pruned)
        return kept, True

    if isinstance(value, dict):
        props = (schema or {}).get("properties") or {}
        required = (schema or {}).get("required") or []
        out = {}
        for key, item in value.items():
            item_schema = props.get(key, {})
            pruned, ok = _prune_degenerate(item, item_schema)
            if not ok:
                # 오염된 값을 지우면 필수가 빠진다 — 이 컨테이너는 못 살린다
                if key in required:
                    return None, False
                continue
            if (
                key in required
                and item_schema.get("type") == "array"
                and isinstance(pruned, list)
                and not pruned
            ):
                return None, False
            out[key] = pruned
        # 애초에 없던 required 키는 검사하지 않는다. 우리가 지운 게 아니고, 미완성
        # 항목을 버리는 것은 잘린 출력을 다루는 salvage_truncated_json의 몫이다.
        # 여기서 같이 버리면 오염과 무관한 항목까지 조용히 사라진다(실제로 id=346의
        # 파라미터가 source_tag 누락만으로 통째로 없어졌다).
        return out, True

    return value, True


def drop_degenerate_fields(text: str, schema: dict) -> Optional[str]:
    """반복 루프에 오염된 필드만 떨어낸 JSON을 돌려준다. 못 살리면 None.

    `_stage_result_defect`는 오염을 잡아 재시도를 걸지만, 재시도 결과가 또 오염돼도
    그대로 저장된다. 파싱 실패는 `_raw`/`_parse_error` 경로가 받아 주는데, 파싱은
    되면서 값만 오염된 출력은 받아 줄 경로가 없기 때문이다. 실제로 그렇게 저장된
    행이 DB에 3개 있었다(2026-08-17 조사, 전부 gemini-3.6-flash recipe).

    None을 주는 경우는 둘이다. 오염이 없어 손댈 게 없거나(호출부가 원본을 그대로
    쓴다), 오염된 값이 스키마 required라 떨어내면 빈 껍데기가 되거나.
    """
    try:
        parsed = json.loads(_clean_llm_json(text or ""))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not _has_degenerate_repetition(parsed):
        return None  # 멀쩡하다. 떨어낼 게 없다.

    pruned, ok = _prune_degenerate(parsed, schema or {})
    if not ok or not isinstance(pruned, dict):
        return None
    if _has_degenerate_repetition(pruned):
        return None  # 떨어내고도 오염이 남으면 신뢰할 수 없다
    return json.dumps(pruned, ensure_ascii=False)


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
