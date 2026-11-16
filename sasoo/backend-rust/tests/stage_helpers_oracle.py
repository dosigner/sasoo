"""Record Python outputs of the shared stage helpers on synthetic inputs.

Usage: backend/.venv/bin/python -I tests/stage_helpers_oracle.py <backend_dir> <out_json>
"""
import json
import os
import sys
from pathlib import Path

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
backend, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.path.insert(0, str(backend))

from api import analysis_helpers as h  # noqa: E402
from services import analysis_execution as ae  # noqa: E402

loop_ko = "반복 " * 200
loop_words = ("alpha beta gamma " * 80).strip()
normal = " ".join(f"word{i}" for i in range(120))
mixed = normal + " " + ("loop again " * 60)
SCHEMA = {
    "type": "object",
    "required": ["title", "steps"],
    "properties": {
        "title": {"type": "string"},
        "note": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "object", "required": ["n", "text"],
                                             "properties": {"n": {"type": "integer"}, "text": {"type": "string"}}}},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}

texts = [
    "", "  ", '{"a": 1}', '```json\n{"a": 1}\n```', '```\n{"a":1}\n```  ', "```json\n{\"a\": 1}",
    "not json", '[1, 2]', '{"x": "' + loop_words + '"}', '{"x": ["ok", "' + loop_ko + '"]}',
    '{"x": "' + mixed + '"}', '{"x": "' + normal + '"}',
]
truncated = [
    '{"title": "t", "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "b"}, {"n": 3, "te',
    '{"title": "t", "steps": [{"n": 1, "text": "a"}, {"n": 2}], "tags": ["x", "y',
    '{"title": "t", "note": "abc", "steps": [{"n": 1, "te',
    '{"title": "제목", "steps": [{"n": 1, "text": "가\\"나"}, {"n": 2, "text": "다',
    '```json\n{"title": "t", "steps": [{"n": 1, "text": "a"}], "note": "cut',
    '{"steps": [{"n": 1, "text": "a"}], "title": "t"}',
    '{"title": "t"',
    '{"title": "t", "steps": []',
]
degenerate = [
    '{"title": "t", "note": "' + loop_words + '", "steps": [{"n": 1, "text": "a"}]}',
    '{"title": "' + loop_words + '", "steps": [{"n": 1, "text": "a"}]}',
    '{"title": "t", "steps": [{"n": 1, "text": "' + loop_words + '"}]}',
    '{"title": "t", "steps": [{"n": 1, "text": "a"}, {"n": 2, "text": "' + loop_words + '"}], "tags": ["' + loop_words + '"]}',
    '{"title": "t", "steps": [{"n": 1, "text": "a"}]}',
]
screenings = [
    None, "", "garbage", "{}", '{"relevance_score": null}', '{"relevance_score": ""}', '{"relevance_score": "0.2"}',
    '{"relevance_score": 0.1, "paper_type": "review"}',
    '{"relevance_score": 0.9, "paper_type": "review"}',
    '{"relevance_score": 0.9, "methodology_type": "review"}',
    '{"relevance_score": 0.9, "recipe_applicable": false, "deep_dive_applicable": false, "confidence": 0.5}',
    '{"relevance_score": 0.9, "recipe_applicable": false, "deep_dive_applicable": false, "confidence": 0.8}',
    '{"relevance_score": 0.9, "recipe_applicable": false, "confidence": "high"}',
    '{"relevance_score": 0.9, "recipe_applicable": true, "deep_dive_applicable": true}',
    '{"relevance_score": 0.4, "domain": " General ", "key_topics": ["a"]}',
    '{"relevance_score": 0.4, "domain": "unknown", "key_topics": ["a", "b"], "is_experimental": false}',
    '{"relevance_score": 0.4, "domain": "unknown", "key_topics": ["a", "b"]}',
    '{"relevance_score": 0.4, "domain": "optics"}',
    '```json\n{"relevance_score": 0.2}\n```',
    '{"relevance_score": true}',
]

cases = {
    "clean_llm_json": [{"input": t, "output": h._clean_llm_json(t)} for t in texts + truncated],
    "is_degenerate_string": [{"input": s, "output": h._is_degenerate_string(s)} for s in [loop_words, loop_ko.strip(), mixed, normal, "짧은 문장", "가나다라마" * 120]],
    "stage_result_defect": [{"input": t, "output": h._stage_result_defect(t)} for t in texts + truncated + degenerate],
    "salvage_truncated_json": [{"input": t, "output": h.salvage_truncated_json(t, SCHEMA)} for t in texts + truncated + degenerate],
    "drop_degenerate_fields": [{"input": t, "output": h.drop_degenerate_fields(t, SCHEMA)} for t in texts + truncated + degenerate],
    "is_error_result": [{"input": t, "output": h._is_error_result(t)} for t in texts + ['{"error": "x"}', '{"_parse_error": "y"}']],
    "screening_gate_decision": [
        {"input": s, "phase": p, "output": list(ae._screening_gate_decision(s, p))}
        for s in screenings for p in ("recipe", "deep_dive")
    ],
    "chain_restart_context": [
        {"input": prev, "output": ae._build_chain_restart_context(prev)}
        for prev in [[], ["", "a"], ["가" * 4100, '{"b": 2}'], ["x" * 3999, "y" * 4000, "z" * 4001]]
    ],
    "skip_reason": [{"input": t, "output": ae._skip_reason({"text": t})} for t in texts + [
        '{"skipped": true, "reason": "low_relevance_screening"}', '{"skipped": true}', '{"skipped": false, "reason": "x"}',
        '{"skipped": 1, "reason": ""}']],
    "parse_error_text": [{"raw": r, "reason": "응답이 완료되지 않았습니다", "output": json.dumps({"_raw": r, "_parse_error": "응답이 완료되지 않았습니다"})}
                         for r in ["", "부분 출력 {\"a\"", "tab\tand\nnewline"]],
    "schema": SCHEMA,
}
out.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
