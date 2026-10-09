# 토의 1단계 말투 게이트 하네스(tone-probe/probe.py에서 파생). 규칙 문단은 RULES_FROM 파일의 _DISCUSSION_RULES_KO를 그대로 읽는다.
# 실제 채팅 경로(_chat_with_agent_impl)와 같은 순서로 system prompt를 조립하되, 행동 규칙 문단만 바꿔 끼운다.
# 실행: cd sasoo/backend && ./.venv/bin/python -I ../../.scratch/discussion/tone-probe/probe.py
import asyncio
import os
import json
import re
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "sasoo" / "backend"
sys.path.insert(0, str(BACKEND))
OUT = Path(__file__).resolve().parent

from models.database import connect_worker_db, fetch_all, fetch_one, get_paper_dir  # noqa: E402
from services.api_key_runtime import load_api_keys_from_settings  # noqa: E402
from services.agents import get_agent_for_domain  # noqa: E402
from services.analysis_results import get_latest_completed_phase_rows  # noqa: E402
from services.analysis_execution import _phase_result_snippet  # noqa: E402
from services.document_context import load_or_build_document_context  # noqa: E402
from services.llm.interactions_client import _SYSTEM_INSTRUCTION_KO, stream_interaction  # noqa: E402
from services.model_registry import active_provider, resolve as resolve_model  # noqa: E402
from services.pricing import calc_result_cost  # noqa: E402

import ast
_ROUTES = Path(os.environ["RULES_FROM"]).read_text()
_node = next(n for n in ast.parse(_ROUTES).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_DISCUSSION_RULES_KO")
PROMPTS = {"STAGE1": ast.literal_eval(_node.value)}
REPEATS = int(os.environ.get("REPEATS", "3"))

CASES = {
    999006: [
        ("correct", "OT 경로를 쓰면 diffusion 경로보다 샘플링에 필요한 함수 평가 횟수(NFE)가 줄어든다는 게 이 논문의 주장이지?"),
        ("overclaim", "Flow Matching은 모든 생성 모델 과제에서 diffusion보다 항상 낫다는 거지?"),
        ("wrong", "이 논문은 학습 중에 ODE를 직접 풀어서 likelihood를 최대화하는 방식이지?"),
        ("idea", "오디오 스펙트로그램 생성에 FM-OT를 적용해 보려는데, 먼저 뭘 확인해야 할까?"),
        ("symbol", "σ_min이 뭐야?"),
        ("chitchat", "오늘 이 논문 읽느라 좀 지쳤어."),
        ("critique", "OT 경로가 diffusion 경로보다 낫다는 이 논문의 해석을 비판적으로 따져 줘."),
    ],
    999004: [
        ("correct", "다운링크 WFS 측정을 여러 lookback frame에 걸쳐 모아서 대기층별 위상을 분해하는 방식이지?"),
        ("overclaim", "LITEUP을 쓰면 PAA 조건과 상관없이 항상 이상적인 uplink 보정(UL)만큼 성능이 나온다는 거지?"),
        ("wrong", "이 방법은 위성이 보내는 beacon을 따로 측정해서 uplink 위상을 구하는 거지?"),
        ("idea", "우리 지상국 망원경은 500 mm인데 이 방법을 적용하려면 뭘 먼저 확인해야 해?"),
        ("symbol", "θ₀가 뭐야?"),
        ("chitchat", "광학 논문은 늘 수식이 많아서 힘들어."),
        ("critique", "LITEUP이 기존 방식보다 낫다는 이 논문의 해석을 비판적으로 따져 줘."),
    ],
}

PHASES = ["screening", "citation", "visual", "recipe", "deep_dive"]
LABELS = {
    "screening": "스크리닝 결과",
    "citation": "인용 분석 결과",
    "visual": "시각 분석 결과",
    "recipe": "레시피 추출 결과",
    "deep_dive": "심층 분석 결과",
}
CITE = re.compile(r"(p\.\s?\d+|\d+\s?페이지|Fig(ure)?\.?\s?\d+|그림\s?\d+|Table\s?\d+|표\s?\d+|Section\s?\d+|\d+(\.\d+)?\s?절|Eq\.?\s?\(?\d+|식\s?\(?\d+)", re.I)


async def build_context(paper_id: int) -> tuple[str, str]:
    """_chat_with_agent_impl의 1~4단계와 같은 조립. (context_block, persona)"""
    paper = await fetch_one("SELECT * FROM papers WHERE id = ?", (paper_id,))
    chat_context = ""
    try:
        document_context = load_or_build_document_context(get_paper_dir(paper["folder_name"]))
        chat_context = str(document_context.get("phase_inputs", {}).get("chat", ""))
    except (FileNotFoundError, RuntimeError):
        pass
    rows = await get_latest_completed_phase_rows(paper_id, phases=PHASES)
    agent = get_agent_for_domain(paper["domain"] or "general")
    persona = f"너는 {agent.profile.display_name_ko}({agent.profile.display_name}) 에이전트야. 성격: {agent.profile.personality}."
    info = f"논문: {paper['title']}"
    for key, label in (("authors", "저자"), ("year", "연도"), ("journal", "저널")):
        if paper.get(key):
            info += f"\n{label}: {paper[key]}"
    parts = [info]
    if chat_context:
        parts.append(f"\n--- 논문 컨텍스트 ---\n{chat_context}")
    for phase in PHASES:
        if phase in rows:
            parts.append(f"\n--- {LABELS[phase]} ---\n{_phase_result_snippet(rows[phase], 3000)}")
    return "\n".join(parts), persona


async def run_one(model, effort, system_prompt, message):
    text, done = [], None
    t0 = time.perf_counter()
    first = None
    async for ev in stream_interaction(f"사용자: {message}", lane="chat", model=model, thinking_level=effort,
                                       system_instruction=system_prompt, store=False):
        if ev["type"] == "token":
            first = first or time.perf_counter() - t0
            text.append(ev["text"])
        elif ev["type"] == "done":
            done = ev
    body = "".join(text)
    return {
        "text": body,
        "tokens_in": done.get("tokens_in") if done else None,
        "tokens_out": done.get("tokens_out") if done else None,
        "cost_usd": calc_result_cost(done, model=model) if done else None,
        "first_token_s": round(first, 2) if first else None,
        "total_s": round(time.perf_counter() - t0, 2),
        "citations": len(CITE.findall(body)),
        "chars": len(body),
    }


async def main():
    await connect_worker_db()
    rows = await fetch_all("SELECT key, value FROM settings WHERE key IN ('gemini_api_key', 'openai_api_key')")
    await load_api_keys_from_settings({r["key"]: r["value"] for r in rows}, True)
    provider = os.environ.get("PROVIDER") or await active_provider()
    choice = resolve_model("chat", provider)
    print(f"provider={provider} model={choice.model} effort={choice.effort}", flush=True)

    results = []
    sem = asyncio.Semaphore(3)
    for paper_id, cases in CASES.items():
        context, persona = await build_context(paper_id)

        async def task(pid=paper_id, ctx=context, per=persona, kind=None, msg=None, pkey=None):
            system_prompt = f"{_SYSTEM_INSTRUCTION_KO}\n\n{per}\n\n{PROMPTS[pkey]}\n\n{ctx}"
            async with sem:
                r = await run_one(choice.model, choice.effort, system_prompt, msg)
            r.update(paper_id=pid, kind=kind, message=msg, prompt=pkey)
            print(f"{pid} {kind:9s} {pkey} cite={r['citations']} chars={r['chars']} ${r['cost_usd']}", flush=True)
            return r

        only = [k for k in os.environ.get("ONLY", "").split(",") if k] or list(PROMPTS)
        kinds = [k for k in os.environ.get("KINDS", "").split(",") if k]
        results += await asyncio.gather(*(task(kind=k, msg=m, pkey=p) for k, m in cases if not kinds or k in kinds for p in only for _ in range(REPEATS)))

    meta = {"provider": provider, "model": choice.model, "effort": choice.effort, "date": "2026-10-09",
            "total_cost_usd": round(sum(r["cost_usd"] or 0 for r in results), 5), "prompts": PROMPTS}
    (OUT / os.environ.get("OUTFILE", "results.json")).write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1))
    print("total_cost_usd", meta["total_cost_usd"])


asyncio.run(main())
os._exit(0)  # 채팅 풀 스레드가 남아 종료가 멈추는 것을 피한다
