"""양사 체인 실측: gemini-3.7-flash vs gpt-5.6-luna, paper 45.

프로덕션 체인 의미를 그대로 재현한다:
  visual(첫 호출, PDF 포함) → recipe(지시문만, 서버 상태 체인) → deep_dive(digest 주입)
- 프롬프트·스키마·시스템 프롬프트는 analysis_routes에서 그대로 가져온다
  (recipe 지시문은 소스에서 정규식으로 축자 추출 — 복붙 drift 방지).
- effort 사다리: Gemini low/medium/high, Luna low/medium/xhigh (provider_compare 관례).
- 프로브: deep_dive를 Gemini medium, Luna high로 한 번 더(각자 recipe 상태에서 분기).
- 단계별 tokens_in/out(+thinking/reasoning, 캐시), 경과, 비용을 원장에 남긴다.
"""

import inspect
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

BACKEND = Path("/Users/dongj/dev/논문_사수_개발중/sasoo/backend")
sys.path.insert(0, str(BACKEND))

from api import analysis_routes as ar  # noqa: E402
from api.analysis_context import build_chain_system_instruction  # noqa: E402
from services.agents import get_agent_for_domain  # noqa: E402
from services.pricing import calc_cost  # noqa: E402
from tools.provider_compare import load_keys, load_paper  # noqa: E402

PAPER_ID = 45
LEVEL_KEY = "undergrad"  # paper 45의 실제 설정값
LUNA = "gpt-5.6-luna"
LUNA_RATES = (0.20, 1.20)  # $/M in, out (2026-07-30 인하 후)
OUT = Path(__file__).parent / "chain_compare"
OUT.mkdir(exist_ok=True)

GEMINI_EFFORT = {"visual": "low", "recipe": "medium", "deep_dive": "high"}
LUNA_EFFORT = {"visual": "low", "recipe": "medium", "deep_dive": "xhigh"}
RECIPE_CAP = 24_000


# ---------------- 프롬프트 재료 (프로덕션과 동일 경로) ----------------

def recipe_instruction() -> str:
    """analysis_routes 소스에서 recipe 지시문과 optics 힌트를 축자 추출."""
    src = inspect.getsource(ar)
    body = re.search(r'instruction = f"""(이 연구 논문에서.*?)"""\n\n    prompt_chain', src, re.S)
    hint = re.search(
        r'if domain in \("optics", "photonics"\):\n\s+domain_hint = """\n(.*?)"""', src, re.S
    )
    assert body and hint, "recipe 지시문 추출 실패 — 소스가 바뀌었다"
    return body.group(1).replace("{domain_hint}", "\n" + hint.group(1))


def load_db_context():
    conn = sqlite3.connect(BACKEND / "library" / "sasoo.db")
    conn.row_factory = sqlite3.Row
    figs = conn.execute(
        "SELECT figure_num, quality, confidence, resolver_version FROM figures "
        "WHERE paper_id=? ORDER BY id", (PAPER_ID,),
    ).fetchall()
    tabs = conn.execute(
        "SELECT table_num, confidence, parse_method, resolver_version FROM tables "
        "WHERE paper_id=? ORDER BY id", (PAPER_ID,),
    ).fetchall()
    texts = {}
    for ph in ("screening", "citation"):
        row = conn.execute(
            "SELECT result FROM analysis_results WHERE paper_id=? AND phase=? "
            "ORDER BY id DESC LIMIT 1", (PAPER_ID, ph),
        ).fetchone()
        texts[ph] = row["result"] if row else ""
    conn.close()
    return figs, tabs, texts


def figure_desc_of(figs, tabs) -> str:
    if not figs and not tabs:
        return ""
    desc = f"\n\nExtracted {len(figs)} resolved figures and {len(tabs)} resolved tables from the paper."
    for f in figs:
        desc += (
            f"\n- {f['figure_num']}: quality={f['quality']}, "
            f"confidence={f['confidence']}, resolver={f['resolver_version']}"
        )
    for t in tabs[:10]:
        desc += (
            f"\n- {t['table_num']}: confidence={t['confidence']}, "
            f"method={t['parse_method']}, resolver={t['resolver_version']}"
        )
    return desc


def build_stage_prompts():
    figs, tabs, texts = load_db_context()
    visual = (
        f"{ar._VISUAL_INSTRUCTION}\n\n위 논문 PDF를 직접 보고 시각 요소를 분석해줘."
        + figure_desc_of(figs, tabs)
    )
    recipe = (
        recipe_instruction() + "\n\n위 논문 PDF와 이전 분석을 바탕으로 실험 레시피를 추출해줘."
    )
    digest = ar._stateless_digest(texts["screening"], texts["citation"])
    deep = (
        f"{ar._DEEP_DIVE_INSTRUCTION}\n\n위 논문 PDF와 앞선 체인 단계(시각·레시피) 결과, 그리고 아래 "
        "스크리닝·인용 분석 digest를 바탕으로 포괄적인 심층 분석을 제공해줘."
    )
    if digest:
        deep += f"\n\n--- 스크리닝·인용 분석 digest ---\n{digest}"
    return {"visual": visual, "recipe": recipe, "deep_dive": deep}


def stage_system_instruction(stage: str) -> str:
    agent = get_agent_for_domain("optics")
    return build_chain_system_instruction(
        persona_prompt=ar._build_persona_prompt(agent, stage),
        research_context="",  # 설정 DB의 실제 값(빈 문자열)
        focus=None,
        level_key=LEVEL_KEY,
    )


SCHEMAS = {
    "visual": ar._VISUAL_SCHEMA,
    "recipe": ar._RECIPE_SCHEMA,
    "deep_dive": ar._DEEP_DIVE_SCHEMA,
}

LEDGER: list[dict] = []


def record(provider, stage, effort, usage, elapsed, text, tag=""):
    name = f"{provider}_{stage}{('_' + tag) if tag else ''}"
    (OUT / f"{name}.json").write_text(text or "")
    row = {"provider": provider, "stage": stage, "effort": effort,
           "elapsed_s": round(elapsed, 1), **usage}
    LEDGER.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)


# ---------------- Gemini (Interactions API, 프로덕션 체인과 동일) ----------------

def run_gemini_chain(key: str, pdf: Path, prompts: dict):
    from google import genai

    client = genai.Client(api_key=key)
    up = client.files.upload(file=str(pdf))
    for _ in range(30):
        if client.files.get(name=up.name).state.name == "ACTIVE":
            break
        time.sleep(2)

    def call(stage, prev_id, thinking, cap=None, tag=""):
        if prev_id is None:
            contents = [
                {"type": "document", "uri": up.uri, "mime_type": "application/pdf"},
                {"type": "text", "text": prompts[stage]},
            ]
        else:
            contents = prompts[stage]
        gen_cfg = {"thinking_level": thinking}
        if cap:
            gen_cfg["max_output_tokens"] = cap
        started = time.time()
        it = client.interactions.create(
            model="gemini-3.7-flash",
            input=contents,
            system_instruction=stage_system_instruction(stage),
            store=True,
            generation_config=gen_cfg,
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": SCHEMAS[stage]},
            **({"previous_interaction_id": prev_id} if prev_id else {}),
        )
        elapsed = time.time() - started
        u = getattr(it, "usage", None)
        thought = getattr(u, "total_thought_tokens", 0) or 0
        tin = getattr(u, "total_input_tokens", 0) or 0
        tout = (getattr(u, "total_output_tokens", 0) or 0) + thought
        usage = {
            "tokens_in": tin, "tokens_out": tout, "tokens_thought": thought,
            "status": str(getattr(it, "status", "")),
            "cost_usd": round(calc_cost("gemini-3.7-flash", tin, tout), 4),
        }
        record("gemini", stage, thinking, usage, elapsed, it.output_text or "", tag)
        return getattr(it, "id", None)

    v_id = call("visual", None, GEMINI_EFFORT["visual"])
    r_id = call("recipe", v_id, GEMINI_EFFORT["recipe"], cap=RECIPE_CAP)
    call("deep_dive", r_id, GEMINI_EFFORT["deep_dive"])
    call("deep_dive", r_id, "medium", tag="probe_medium")


# ---------------- Luna (Responses API, previous_response_id 체인) ----------------

def run_luna_chain(key: str, pdf: Path, prompts: dict):
    from openai import OpenAI

    client = OpenAI(api_key=key, timeout=900)
    with open(pdf, "rb") as fh:
        up = client.files.create(file=fh, purpose="user_data")

    def call(stage, prev_id, effort, cap=None, tag=""):
        if prev_id is None:
            content = [
                {"type": "input_file", "file_id": up.id},
                {"type": "input_text", "text": prompts[stage]},
            ]
        else:
            content = [{"type": "input_text", "text": prompts[stage]}]
        started = time.time()
        resp = client.responses.create(
            model=LUNA,
            instructions=stage_system_instruction(stage),
            input=[{"role": "user", "content": content}],
            reasoning={"effort": effort},
            text={"format": {"type": "json_schema", "name": "sasoo_result",
                             "schema": SCHEMAS[stage], "strict": False}},
            store=True,
            **({"previous_response_id": prev_id} if prev_id else {}),
            **({"max_output_tokens": cap} if cap else {}),
        )
        elapsed = time.time() - started
        u = resp.usage
        tin = getattr(u, "input_tokens", 0) or 0
        tout = getattr(u, "output_tokens", 0) or 0
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        reasoning = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0
        usage = {
            "tokens_in": tin, "tokens_out": tout, "tokens_reasoning": reasoning,
            "tokens_in_cached": cached, "status": str(getattr(resp, "status", "")),
            "cost_usd": round(tin / 1e6 * LUNA_RATES[0] + tout / 1e6 * LUNA_RATES[1], 4),
        }
        record("luna", stage, effort, usage, elapsed, resp.output_text or "", tag)
        return resp.id

    v_id = call("visual", None, LUNA_EFFORT["visual"])
    r_id = call("recipe", v_id, LUNA_EFFORT["recipe"], cap=RECIPE_CAP)
    call("deep_dive", r_id, LUNA_EFFORT["deep_dive"])
    call("deep_dive", r_id, "high", tag="probe_high")


def main():
    keys = load_keys()
    assert keys["gemini"] and keys["openai"], "키 부족"
    pdf, meta = load_paper(PAPER_ID)
    print(f"논문: {meta['title'][:70]}", flush=True)
    prompts = build_stage_prompts()
    for st, p in prompts.items():
        print(f"프롬프트 길이 {st}: {len(p)}자", flush=True)

    errors = []
    for name, fn in (("gemini", run_gemini_chain), ("luna", run_luna_chain)):
        try:
            fn(keys[name if name == "gemini" else "openai"], pdf, prompts)
        except Exception as exc:  # noqa: BLE001 - 한쪽 실패가 다른 쪽 실측을 막지 않게
            errors.append(f"{name}: {exc!r}")
            print(f"ERROR {name}: {exc!r}", flush=True)

    (OUT / "ledger.json").write_text(json.dumps(LEDGER, ensure_ascii=False, indent=2))
    total = sum(r["cost_usd"] for r in LEDGER)
    print(f"\n총 비용: ${total:.4f}, 호출 {len(LEDGER)}건, 오류 {len(errors)}건", flush=True)
    for e in errors:
        print("실패:", e, flush=True)


if __name__ == "__main__":
    main()
