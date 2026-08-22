"""반복 루프에 오염된 필드를 떨어내는 경로.

2026-08-17 조사에서 나온 자리다. `_stage_result_defect`는 오염을 정확히 잡아
재시도를 걸지만, **재시도 결과는 다시 검사하지 않고 그대로 저장**한다. 파싱
실패는 `_raw`/`_parse_error` 경로가 받아 주는데, 파싱은 되면서 값만 오염된
출력은 받아 줄 경로가 없어 정상 결과로 저장된다.

실제로 DB에 그렇게 저장된 행이 3개 있다(전부 gemini-3.6-flash, recipe):
  id=355 paper 45  score_rationale 3,713자  "하겠음임 하겠음임 하겠음임..."
  id=362 paper 48  score_rationale 3,059자  "서비스 규칙 준수함원 문맥 유지함..."
  id=346           parameters[0].unit       배열 항목 안쪽 필드도 오염된다

규칙: **오염된 값은 저장하지 않는다.** 다만 되살리기와 같은 선을 지킨다 —
필수 필드가 오염됐으면 떨어내지 않고 실패로 둔다. 필수 필드를 지운 빈 껍데기를
성공으로 저장하는 게 실패보다 나쁘다.
"""

import json

from api.analysis_helpers import drop_degenerate_fields

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "parameters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "source_tag": {"type": "string"},
                },
                "required": ["name", "value", "source_tag"],
            },
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "score_rationale": {"type": "string"},
    },
    "required": ["title", "parameters", "steps"],
}

# id=355(paper 45)에서 실제로 저장된 꼬리 패턴
KO_FILLER = "점수는 0.82임 Boundary가 적절함. 명확함 인정함임 " + "하겠음임 " * 400
# row-368(3.7)에서 실제로 나온 꼬리 패턴
EN_FILLER = "Score rationale here. " + "(Fin). (End). Done! " * 300


def _doc(**overrides):
    doc = {
        "title": "레시피",
        "parameters": [
            {"name": "wavelength", "value": "1550", "unit": "nm", "source_tag": "explicit"},
            {"name": "power", "value": "10", "unit": "mW", "source_tag": "explicit"},
        ],
        "steps": ["1단계", "2단계"],
        "score_rationale": "핵심 파라미터가 명확해 0.85를 부여함.",
    }
    doc.update(overrides)
    return json.dumps(doc, ensure_ascii=False)


def test_returns_none_when_nothing_is_polluted():
    """멀쩡한 결과는 건드리지 않는다 — 호출부가 원본을 그대로 쓰게 None을 준다."""
    assert drop_degenerate_fields(_doc(), SCHEMA) is None


def test_drops_polluted_optional_top_level_field():
    """score_rationale은 스키마 required가 아니다. 오염되면 통째로 뺀다."""
    cleaned = drop_degenerate_fields(_doc(score_rationale=KO_FILLER), SCHEMA)
    assert cleaned is not None
    d = json.loads(cleaned)
    assert "score_rationale" not in d


def test_keeps_every_other_field_intact():
    """오염 필드만 빼고 나머지는 한 글자도 바뀌면 안 된다."""
    cleaned = drop_degenerate_fields(_doc(score_rationale=EN_FILLER), SCHEMA)
    d = json.loads(cleaned)
    assert d["title"] == "레시피"
    assert d["steps"] == ["1단계", "2단계"]
    assert len(d["parameters"]) == 2
    assert d["parameters"][0] == {
        "name": "wavelength", "value": "1550", "unit": "nm", "source_tag": "explicit",
    }


def test_drops_polluted_key_inside_array_item_but_keeps_the_item():
    """id=346이 밟은 자리. unit은 항목 required가 아니라 키만 떨어내고 항목은 남긴다."""
    doc = json.loads(_doc())
    doc["parameters"][0]["unit"] = KO_FILLER
    cleaned = drop_degenerate_fields(json.dumps(doc, ensure_ascii=False), SCHEMA)
    assert cleaned is not None
    d = json.loads(cleaned)
    assert len(d["parameters"]) == 2
    assert "unit" not in d["parameters"][0]
    assert d["parameters"][0]["name"] == "wavelength"
    assert d["parameters"][0]["value"] == "1550"


def test_returns_none_when_a_required_top_level_field_is_polluted():
    """필수 필드를 지우면 빈 껍데기가 된다. 그때는 떨어내지 않고 실패로 둔다."""
    assert drop_degenerate_fields(_doc(title=KO_FILLER), SCHEMA) is None


def test_drops_the_whole_item_when_a_required_key_inside_it_is_polluted():
    """항목 required가 오염되면 그 항목만 버리고 나머지는 살린다.

    되살리기의 `_prune_incomplete_items`와 같은 선이다 — required를 못 채운
    항목은 버리되, 파라미터 하나 때문에 레시피 전체를 버리지는 않는다.
    """
    doc = json.loads(_doc())
    doc["parameters"][0]["value"] = EN_FILLER
    cleaned = drop_degenerate_fields(json.dumps(doc, ensure_ascii=False), SCHEMA)
    assert cleaned is not None
    d = json.loads(cleaned)
    assert [p["name"] for p in d["parameters"]] == ["power"]


def test_returns_none_when_every_item_of_a_required_array_is_polluted():
    """다 버리고 나면 필수 배열이 빈다. 그때는 빈 껍데기를 저장하지 않는다."""
    doc = json.loads(_doc())
    for p in doc["parameters"]:
        p["value"] = EN_FILLER
    assert drop_degenerate_fields(json.dumps(doc, ensure_ascii=False), SCHEMA) is None


def test_returns_none_when_text_is_not_parseable():
    """파싱조차 안 되면 이 경로가 아니다 — 되살리기 경로가 맡는다."""
    assert drop_degenerate_fields('{"title": "쓰다 만', SCHEMA) is None


def test_drops_polluted_string_inside_a_string_array():
    """steps 같은 문자열 배열도 오염될 수 있다. 오염 항목만 뺀다."""
    cleaned = drop_degenerate_fields(_doc(steps=["1단계", EN_FILLER, "3단계"]), SCHEMA)
    assert cleaned is not None
    assert json.loads(cleaned)["steps"] == ["1단계", "3단계"]


def test_returns_none_when_pruning_would_empty_a_required_array():
    """필수 배열이 통째로 비면 되살리기와 같은 이유로 저장하지 않는다."""
    assert drop_degenerate_fields(_doc(steps=[EN_FILLER, KO_FILLER]), SCHEMA) is None


def test_leaves_a_clean_but_incomplete_item_alone():
    """오염되지 않은 항목은 required가 비어 있어도 건드리지 않는다.

    id=346이 밟은 자리다. 그 행의 유일한 파라미터는 `source_tag`가 애초에 없고
    `unit`만 오염돼 있었다. 없던 키는 우리가 지운 게 아니므로 이 함수의 일이
    아니다 — 오염만 떨어내고 항목은 남겨야 한다. 미완성 항목을 버리는 것은
    `salvage_truncated_json`(잘린 출력)의 몫이지 여기가 아니다.
    """
    doc = json.loads(_doc())
    doc["parameters"] = [{"name": "model_architecture", "value": "Eagle-2 VLM", "unit": KO_FILLER}]
    cleaned = drop_degenerate_fields(json.dumps(doc, ensure_ascii=False), SCHEMA)
    assert cleaned is not None
    params = json.loads(cleaned)["parameters"]
    assert len(params) == 1
    assert params[0] == {"name": "model_architecture", "value": "Eagle-2 VLM"}
