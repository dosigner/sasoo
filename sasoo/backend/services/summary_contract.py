from collections.abc import Mapping
import json


_SOURCE_REFS_SCHEMA = {
    "type": "array", "maxItems": 4, "items": {"type": "string"},
}
_SECTION_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "section_title": {"type": "string"},
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "explanation": {"type": "string"},
        "source_refs": {**_SOURCE_REFS_SCHEMA, "minItems": 1},
    },
    "required": ["section_title", "question", "answer", "explanation", "source_refs"],
}
_TRANSFER_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string"},
        "paper_condition": {"type": "string"},
        "condition_basis": {"type": "string", "enum": ["reported", "inferred", "not_reported"]},
        "check_before_transfer": {"type": "string"},
        "source_refs": _SOURCE_REFS_SCHEMA,
    },
    "required": ["item", "paper_condition", "condition_basis", "check_before_transfer", "source_refs"],
}
_SUMMARY_FIELDS = {"section_answers", "transfer_checks"}


def parse_summary_json(text: str) -> dict[str, object]:
    def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        fields: dict[str, object] = {}
        for key, value in pairs:
            if key in fields:
                raise ValueError(f"심층 분석 응답에 중복된 키가 있습니다: {key}")
            fields[key] = value
        return fields

    payload = json.loads(text, object_pairs_hook=unique_fields)
    if not isinstance(payload, dict):
        raise ValueError("심층 분석 응답이 객체가 아닙니다")
    pending: list[object] = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and any(ord(char) < 32 and char not in "\t\n\r" for char in value):
            raise ValueError("심층 분석 응답에 표시할 수 없는 제어 문자가 있습니다")
    return payload


def validate_summary_extensions(data: Mapping[str, object], *, require: bool = False) -> bool:
    if "_parse_error" in data or "error" in data:
        raise ValueError("심층 분석 응답 형식을 확인하지 못했어요")
    present = _SUMMARY_FIELDS.intersection(data)
    if not present and not require:
        return False
    if present != _SUMMARY_FIELDS:
        raise ValueError("요약 확장 필드가 누락됐습니다")
    rules = {
        "section_answers": (12, ("section_title", "question", "answer", "explanation")),
        "transfer_checks": (8, ("item", "paper_condition", "check_before_transfer")),
    }
    for name, (maximum, fields) in rules.items():
        entries = data[name]
        if not isinstance(entries, list) or len(entries) > maximum:
            raise ValueError(f"{name} 배열 형식 또는 항목 수가 잘못됐습니다")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"{name} 항목이 객체가 아닙니다")
            for field in fields:
                value = entry.get(field)
                if not isinstance(value, str) or (field != "explanation" and not value.strip()):
                    raise ValueError(f"{name}.{field} 문자열이 잘못됐습니다")
            refs = entry.get("source_refs")
            if not isinstance(refs, list) or len(refs) > 4:
                raise ValueError(f"{name}.source_refs 배열이 잘못됐습니다")
            if not all(isinstance(ref, str) and ref.strip() for ref in refs):
                raise ValueError(f"{name}.source_refs 출처가 잘못됐습니다")
            if name == "section_answers":
                if not refs:
                    raise ValueError("핵심 답변에 출처가 필요합니다")
            else:
                basis = entry.get("condition_basis")
                if basis not in ("reported", "inferred", "not_reported"):
                    raise ValueError("적용 조건의 근거 성격이 잘못됐습니다")
                if basis != "not_reported" and not refs:
                    raise ValueError("명시 또는 추론 조건에 출처가 필요합니다")
    return True
