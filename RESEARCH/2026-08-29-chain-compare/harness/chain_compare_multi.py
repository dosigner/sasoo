"""VLA 논문 6편 × 양사 체인 실측 (2026-08-29 후속).

paper 45 실측과 같은 프로덕션 프롬프트·스키마 체인을 ai_ml 도메인으로 돌린다.
차이점(기록):
- 라이브러리 밖 논문이라 figure_desc와 스크리닝·인용 digest는 비운다.
- effort 사다리는 전날 확정 권고를 쓴다: 양사 visual low, recipe medium, deep_dive high.
- deep_dive에 max_output_tokens 16,000을 건다(권고안 검증 겸 폭주 예산 방어,
  현행 프로덕션에는 없는 상한).
"""

import inspect
import json
import re
import sys
import time
from pathlib import Path

BACKEND = Path("/Users/dongj/dev/논문_사수_개발중/sasoo/backend")
sys.path.insert(0, str(BACKEND))

from api import analysis_routes as ar  # noqa: E402
from api.analysis_context import build_chain_system_instruction  # noqa: E402
from services.agents import get_agent_for_domain  # noqa: E402
from services.pricing import calc_cost  # noqa: E402
from tools.provider_compare import load_keys  # noqa: E402

PDF_DIR = Path("/Users/dongj/.claude/jobs/63a3bb36/tmp/vla_pdfs")
OUT = Path("/Users/dongj/.claude/jobs/63a3bb36/tmp/vla_out")
OUT.mkdir(exist_ok=True)

PAPERS = ["rt2", "rt1", "palme", "openvla", "octo", "pi0"]
LUNA = "gpt-5.6-luna"
LUNA_RATES = (0.20, 1.20)
LEVEL_KEY = "undergrad"
RECIPE_CAP = 24_000
DEEP_DIVE_CAP = 16_000
EFFORT = {"visual": "low", "recipe": "medium", "deep_dive": "high"}  # 양사 공통 권고 사다리


def extract_recipe_instruction() -> str:
    src = inspect.getsource(ar)
    body = re.search(r'instruction = f"""(이 연구 논문에서.*?)"""\n\n    prompt_chain', src, re.S)
    hint = re.search(
        r'elif domain in \("ai_ml", "neural", "computer_science"\):\n\s+domain_hint = """\n(.*?)"""',
        src, re.S,
    )
    assert body and hint, "지시문 추출 실패"
    return body.group(1).replace("{domain_hint}", "\n" + hint.group(1))


PROMPTS = {
    "visual": f"{ar._VISUAL_INSTRUCTION}\n\n위 논문 PDF를 직접 보고 시각 요소를 분석해줘.",
    "recipe": extract_recipe_instruction()
    + "\n\n위 논문 PDF와 이전 분석을 바탕으로 실험 레시피를 추출해줘.",
    "deep_dive": f"{ar._DEEP_DIVE_INSTRUCTION}\n\n위 논문 PDF와 앞선 체인 단계(시각·레시피) 결과를 "
    "바탕으로 포괄적인 심층 분석을 제공해줘.",
}
SCHEMAS = {"visual": ar._VISUAL_SCHEMA, "recipe": ar._RECIPE_SCHEMA, "deep_dive": ar._DEEP_DIVE_SCHEMA}
CAPS = {"recipe": RECIPE_CAP, "deep_dive": DEEP_DIVE_CAP}

_agent = get_agent_for_domain("ai_ml")
SYS = {
    st: build_chain_system_instruction(
        persona_prompt=ar._build_persona_prompt(_agent, st),
        research_context="", focus=None, level_key=LEVEL_KEY,
    )
    for st in PROMPTS
}

LEDGER: list[dict] = []


def record(paper, provider, stage, effort, usage, elapsed, text):
    (OUT / f"{paper}_{provider}_{stage}.json").write_text(text or "")
    row = {"paper": paper, "provider": provider, "stage": stage, "effort": effort,
           "elapsed_s": round(elapsed, 1), **usage}
    LEDGER.append(row)
    (OUT / "ledger.json").write_text(json.dumps(LEDGER, ensure_ascii=False, indent=2))
    print(json.dumps(row, ensure_ascii=False), flush=True)


def run_gemini(key, paper, pdf):
    from google import genai
    client = genai.Client(api_key=key)
    up = client.files.upload(file=str(pdf))
    for _ in range(45):
        if client.files.get(name=up.name).state.name == "ACTIVE":
            break
        time.sleep(2)
    prev = None
    for stage in ("visual", "recipe", "deep_dive"):
        if prev is None:
            contents = [
                {"type": "document", "uri": up.uri, "mime_type": "application/pdf"},
                {"type": "text", "text": PROMPTS[stage]},
            ]
        else:
            contents = PROMPTS[stage]
        gen_cfg = {"thinking_level": EFFORT[stage]}
        if stage in CAPS:
            gen_cfg["max_output_tokens"] = CAPS[stage]
        started = time.time()
        it = client.interactions.create(
            model="gemini-3.7-flash", input=contents, system_instruction=SYS[stage],
            store=True, generation_config=gen_cfg,
            response_format={"type": "text", "mime_type": "application/json", "schema": SCHEMAS[stage]},
            **({"previous_interaction_id": prev} if prev else {}),
        )
        elapsed = time.time() - started
        u = getattr(it, "usage", None)
        thought = getattr(u, "total_thought_tokens", 0) or 0
        tin = getattr(u, "total_input_tokens", 0) or 0
        tout = (getattr(u, "total_output_tokens", 0) or 0) + thought
        record(paper, "gemini", stage, EFFORT[stage], {
            "tokens_in": tin, "tokens_out": tout, "tokens_thought": thought,
            "status": str(getattr(it, "status", "")),
            "cost_usd": round(calc_cost("gemini-3.7-flash", tin, tout), 4),
        }, elapsed, it.output_text or "")
        prev = getattr(it, "id", None)


def run_luna(key, paper, pdf):
    from openai import OpenAI
    client = OpenAI(api_key=key, timeout=900)
    with open(pdf, "rb") as fh:
        up = client.files.create(file=fh, purpose="user_data")
    prev = None
    for stage in ("visual", "recipe", "deep_dive"):
        if prev is None:
            content = [
                {"type": "input_file", "file_id": up.id},
                {"type": "input_text", "text": PROMPTS[stage]},
            ]
        else:
            content = [{"type": "input_text", "text": PROMPTS[stage]}]
        started = time.time()
        resp = client.responses.create(
            model=LUNA, instructions=SYS[stage],
            input=[{"role": "user", "content": content}],
            reasoning={"effort": EFFORT[stage]},
            text={"format": {"type": "json_schema", "name": "sasoo_result",
                             "schema": SCHEMAS[stage], "strict": False}},
            store=True,
            **({"previous_response_id": prev} if prev else {}),
            **({"max_output_tokens": CAPS[stage]} if stage in CAPS else {}),
        )
        elapsed = time.time() - started
        u = resp.usage
        tin = getattr(u, "input_tokens", 0) or 0
        tout = getattr(u, "output_tokens", 0) or 0
        record(paper, "luna", stage, EFFORT[stage], {
            "tokens_in": tin, "tokens_out": tout,
            "tokens_reasoning": getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0,
            "tokens_in_cached": getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0,
            "status": str(getattr(resp, "status", "")),
            "cost_usd": round(tin / 1e6 * LUNA_RATES[0] + tout / 1e6 * LUNA_RATES[1], 4),
        }, elapsed, resp.output_text or "")
        prev = resp.id


def main():
    keys = load_keys()
    assert keys["gemini"] and keys["openai"], "키 부족"
    errors = []
    for paper in PAPERS:
        pdf = PDF_DIR / f"{paper}.pdf"
        for provider, fn, key in (("gemini", run_gemini, keys["gemini"]),
                                  ("luna", run_luna, keys["openai"])):
            try:
                fn(key, paper, pdf)
            except Exception as exc:  # noqa: BLE001 - 한 조합 실패가 전체를 막지 않게
                errors.append(f"{paper}/{provider}: {exc!r}")
                print(f"ERROR {paper}/{provider}: {exc!r}", flush=True)
    total = sum(r["cost_usd"] for r in LEDGER)
    print(f"\n총 비용 ${total:.4f}, 호출 {len(LEDGER)}건, 오류 {len(errors)}건", flush=True)
    for e in errors:
        print("실패:", e, flush=True)


if __name__ == "__main__":
    main()
