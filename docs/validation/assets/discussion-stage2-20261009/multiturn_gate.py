# 토의 2단계 다중 턴 말투 게이트. 1단계 gate.py의 발화와 인용 정규식을 쓰되, 단일 턴 대신
# 실행 중인 백엔드의 실제 채팅 경로(persist, 서버 기록으로 맥락 조립)에 5턴을 차례로 보낸다.
# 실행: BASE=http://127.0.0.1:18765 DB=<백엔드 DB 사본> python multiturn_gate.py
import asyncio
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:18765") + "/api/analysis"
DB = os.environ["DB"]
REPEATS = int(os.environ.get("REPEATS", "3"))
OUT = Path(__file__).resolve().parent

FOLLOWUP = "방금 비판한 내용 중 첫 번째 근거는 논문 어디에 있어?"
CASES = {
    999006: [
        ("correct", "OT 경로를 쓰면 diffusion 경로보다 샘플링에 필요한 함수 평가 횟수(NFE)가 줄어든다는 게 이 논문의 주장이지?"),
        ("overclaim", "Flow Matching은 모든 생성 모델 과제에서 diffusion보다 항상 낫다는 거지?"),
        ("wrong", "이 논문은 학습 중에 ODE를 직접 풀어서 likelihood를 최대화하는 방식이지?"),
        ("critique", "OT 경로가 diffusion 경로보다 낫다는 이 논문의 해석을 비판적으로 따져 줘."),
        ("followup", FOLLOWUP),
    ],
    999004: [
        ("correct", "다운링크 WFS 측정을 여러 lookback frame에 걸쳐 모아서 대기층별 위상을 분해하는 방식이지?"),
        ("overclaim", "LITEUP을 쓰면 PAA 조건과 상관없이 항상 이상적인 uplink 보정(UL)만큼 성능이 나온다는 거지?"),
        ("wrong", "이 방법은 위성이 보내는 beacon을 따로 측정해서 uplink 위상을 구하는 거지?"),
        ("critique", "LITEUP이 기존 방식보다 낫다는 이 논문의 해석을 비판적으로 따져 줘."),
        ("followup", FOLLOWUP),
    ],
}
CITE = re.compile(r"(p\.\s?\d+|pp\.\s?\d+|\d+\s?(페이지|쪽)|Fig(ure)?\.?\s?\d+|그림\s?\d+|Table\s?\d+|표\s?\d+|Section\s?\d+|§\s?\d+|\d+(\.\d+)?\s?절|Eq\.?\s?\(?\d+|식\s?\(?\d+)", re.I)


async def turn(client, paper_id, message):
    text, done, first = [], None, None
    t0 = time.perf_counter()
    async with client.stream("POST", f"{BASE}/{paper_id}/chat", json={"message": message}) as r:
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if ev["type"] == "token":
                first = first or time.perf_counter() - t0
                text.append(ev["content"])
            elif ev["type"] in ("done", "error"):
                done = ev
    body = "".join(text)
    return {
        "text": body, "event": done.get("type") if done else None,
        "tokens_in": (done or {}).get("tokens_in"), "cost_usd": (done or {}).get("cost_usd"),
        "first_token_s": round(first, 2) if first else None, "citations": len(CITE.findall(body)), "chars": len(body),
    }


async def conversation(client, paper_id, provider, rep):
    await client.delete(f"{BASE}/{paper_id}/discussion")
    turns = []
    for index, (kind, message) in enumerate(CASES[paper_id], 1):
        r = await turn(client, paper_id, message)
        r.update(paper_id=paper_id, provider=provider, rep=rep, turn=index, kind=kind, message=message)
        print(f"{provider} {paper_id} rep{rep} t{index} {kind:9s} in={r['tokens_in']} cite={r['citations']} ${r['cost_usd']}", flush=True)
        turns.append(r)
    saved = (await client.get(f"{BASE}/{paper_id}/discussion")).json()["messages"]
    turns[-1]["saved_rows"] = [(m["kind"], m["status"]) for m in saved]
    return turns


async def main():
    results = []
    async with httpx.AsyncClient(timeout=180) as client:
        for provider in ("openai", "gemini"):
            con = sqlite3.connect(DB)
            con.execute("UPDATE settings SET value=? WHERE key='ai_provider'", (provider,))
            con.commit()
            con.close()
            for rep in range(1, REPEATS + 1):
                # 논문이 다르면 토의도 따로라 두 논문은 동시에 돌린다.
                for turns in await asyncio.gather(*(conversation(client, pid, provider, rep) for pid in CASES)):
                    results += turns
    total = round(sum(r["cost_usd"] or 0 for r in results), 5)
    (OUT / "results-multiturn.json").write_text(json.dumps({"meta": {"date": "2026-10-09", "total_cost_usd": total}, "results": results}, ensure_ascii=False, indent=1))
    print("total_cost_usd", total)


asyncio.run(main())
