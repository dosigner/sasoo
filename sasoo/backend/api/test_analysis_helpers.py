"""잘린 LLM JSON에서 온전히 끝난 부분만 되살리는 경로.

2026-08-16 실측에서 나온 자리다. recipe 단계가 파라미터 26개와 필수 필드를 모두
제대로 쓴 뒤, 마지막 자유서술 필드(score_rationale)의 닫는 따옴표를 못 내고
"Done. Fin. OK. Bye."를 출력 상한까지 반복했다. 유효한 결과가 앞에 다 있는데
파싱 실패 하나로 통째로 버려졌고, 같은 요청을 그대로 재시도해 같은 방식으로
또 무너졌다(2배 과금).

되살리기의 유일한 규칙: **쓰다 만 값은 절대 채우지 않는다.** 값 경계에서만
자르므로 살아남은 항목은 전부 모델이 끝까지 쓴 것이다. 필수 필드가 하나라도
잘려 나갔으면 되살리지 않고 실패로 둔다.
"""

import json

from api.analysis_helpers import salvage_truncated_json

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


def _param(i):
    return f'{{"name": "p{i}", "value": "{i}", "source_tag": "explicit"}}'


def _truncated_in_trailing_field():
    params = ", ".join(_param(i) for i in range(3))
    return (
        '{\n  "title": "T",\n'
        f'  "parameters": [{params}],\n'
        '  "steps": ["s1", "s2"],\n'
        '  "score_rationale": "근거를 적다가 닫지 못했다. Done. Fin. OK. Bye. Done. Fin.'
    )


def test_salvages_a_payload_truncated_in_a_trailing_optional_field():
    out = salvage_truncated_json(_truncated_in_trailing_field(), SCHEMA)
    assert out is not None, "필수 필드가 다 있는데도 되살리지 못했다"
    d = json.loads(out)
    assert d["title"] == "T"
    assert [p["name"] for p in d["parameters"]] == ["p0", "p1", "p2"]
    assert d["steps"] == ["s1", "s2"]
    # 쓰다 만 필드는 채우지 않고 버린다
    assert "score_rationale" not in d


def test_drops_a_half_written_item_but_keeps_the_complete_ones():
    params = ", ".join(_param(i) for i in range(2))
    text = (
        '{\n  "title": "T",\n'
        '  "steps": ["s1"],\n'
        f'  "parameters": [{params}, {{"name": "p2", "value": "2"'
    )
    out = salvage_truncated_json(text, SCHEMA)
    assert out is not None
    d = json.loads(out)
    # p2는 source_tag가 없다. 채워 넣지 말고 버려야 한다.
    assert [p["name"] for p in d["parameters"]] == ["p0", "p1"]


def test_refuses_when_a_required_field_was_lost():
    # steps가 나오기 전에 잘렸다. 되살리면 필수 필드가 빈 채로 성공처럼 보인다.
    text = '{\n  "title": "T",\n  "parameters": [' + _param(0) + ', {"name": "p1", "val'
    assert salvage_truncated_json(text, SCHEMA) is None


def test_refuses_when_a_required_array_would_be_empty():
    # 완성된 파라미터가 하나도 없다. 성공처럼 저장하면 안 된다.
    text = '{\n  "title": "T",\n  "steps": ["s1"],\n  "parameters": [{"name": "p0", "val'
    assert salvage_truncated_json(text, SCHEMA) is None


def test_leaves_already_valid_json_alone():
    good = json.dumps({"title": "T", "parameters": [json.loads(_param(0))], "steps": ["s"]})
    assert salvage_truncated_json(good, SCHEMA) is None


def test_refuses_garbage():
    assert salvage_truncated_json("이건 JSON이 아니다", SCHEMA) is None
    assert salvage_truncated_json("", SCHEMA) is None
