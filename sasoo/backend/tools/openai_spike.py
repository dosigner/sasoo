"""OpenAI Responses API 실측 스파이크 — 스펙 개정 1 R8.

프로덕션 코드를 건드리지 않는 일회용 도구(extraction_audit 관례).
실행: OPENAI_API_KEY=... .venv/bin/python tools/openai_spike.py
각 검사는 독립적으로 실패할 수 있다 — 전부 돌고 결과를 JSON으로 출력한다.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL = os.environ.get("SPIKE_MODEL", "gpt-5.6-luna")

# 프로덕션 스키마를 그대로 가져와 strict:false 준수율을 본다 (R8-3)
from services.analysis_execution import _SCREENING_SCHEMA  # noqa: E402

RESULTS: dict = {"model": MODEL}


def check(name):
    def deco(fn):
        def run():
            try:
                RESULTS[name] = {"ok": True, "detail": fn()}
            except Exception as exc:  # noqa: BLE001 - 스파이크는 전 결과 수집이 목적
                RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                 "trace": traceback.format_exc(limit=3)}
        return run
    return deco


def _client():
    from openai import OpenAI
    return OpenAI()


@check("1_chain_previous_response_id")
def spike_chain():
    """store=True 체인: 첫 턴 텍스트가 후속 턴에 유지되는가 (R8-1)."""
    c = _client()
    r1 = c.responses.create(
        model=MODEL, store=True,
        input="비밀 코드는 SASOO-7291 이다. 기억해라. '확인'이라고만 답해라.",
    )
    r2 = c.responses.create(
        model=MODEL, store=True, previous_response_id=r1.id,
        input="아까 말한 비밀 코드가 뭐였지? 코드만 답해라.",
    )
    recalled = "SASOO-7291" in (r2.output_text or "")
    return {"r1_id": r1.id, "recalled_first_turn": recalled}


@check("2_reasoning_effort_values")
def spike_effort():
    """effort 지원 값 집합 — 특히 minimal (R8-2, R4 확정 조건)."""
    c = _client()
    out = {}
    for effort in ("minimal", "low", "medium", "high", "xhigh"):
        try:
            c.responses.create(model=MODEL, input="1+1은? 숫자만.",
                               reasoning={"effort": effort})
            out[effort] = "supported"
        except Exception as exc:  # noqa: BLE001
            out[effort] = f"rejected: {type(exc).__name__}"
    return out


@check("3_strict_false_schema")
def spike_schema():
    """프로덕션 스키마 그대로 strict:false 전송 → 파싱·준수 확인 (R8-3)."""
    c = _client()
    r = c.responses.create(
        model=MODEL,
        input="광섬유 브래그 격자 센서 논문이라고 가정하고 스크리닝 결과를 채워라.",
        text={"format": {"type": "json_schema", "name": "screening",
                         "schema": _SCREENING_SCHEMA, "strict": False}},
    )
    data = json.loads(r.output_text)
    missing = [k for k in _SCREENING_SCHEMA["required"] if k not in data]
    return {"parsed": True, "missing_required": missing}


@check("4_streaming_events")
def spike_stream():
    """스트리밍 이벤트명과 usage 수신 (R8-4)."""
    c = _client()
    events = set()
    usage = None
    with c.responses.stream(model=MODEL, input="하늘이 파란 이유를 두 문장으로.") as s:
        for ev in s:
            events.add(ev.type)
            if ev.type == "response.completed":
                usage = getattr(ev.response, "usage", None)
    return {"event_types": sorted(events),
            "usage_present": usage is not None,
            "output_tokens": getattr(usage, "output_tokens", None),
            "reasoning_tokens": getattr(
                getattr(usage, "output_tokens_details", None), "reasoning_tokens", None)}


@check("5_image_part")
def spike_image():
    """이미지 파트(base64 data URL) 입력 — 리졸버 경로 등가 (R8-7)."""
    import base64
    # 1x1 PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
        "h6FO1AAAAABJRU5ErkJggg==")
    c = _client()
    r = c.responses.create(model=MODEL, input=[{
        "role": "user",
        "content": [
            {"type": "input_image",
             "image_url": f"data:image/png;base64,{base64.b64encode(png).decode()}"},
            {"type": "input_text", "text": "이 이미지의 크기를 추정해라. 한 문장."},
        ]}])
    return {"answered": bool(r.output_text)}


@check("6_refusal_and_incomplete_shape")
def spike_incomplete():
    """max_output_tokens 도달 시 응답 형태 (R8-6)."""
    c = _client()
    r = c.responses.create(model=MODEL, input="1부터 500까지 세라.", max_output_tokens=32)
    return {"status": getattr(r, "status", None),
            "incomplete_reason": getattr(getattr(r, "incomplete_details", None), "reason", None)}


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("spike_")):
        pass  # check 데코레이터가 등록 시 즉시 실행하지 않으므로 아래에서 명시 호출
    for runner in (spike_chain, spike_effort, spike_schema, spike_stream,
                   spike_image, spike_incomplete):
        runner()
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
