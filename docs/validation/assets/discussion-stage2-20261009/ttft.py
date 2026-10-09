"""평소 턴의 첫 토큰 지연: 같은 백엔드에서 persist 켬(2단계 경로)과 끔(1단계와 같은 무저장 경로)을 번갈아 잰다."""
import json, sqlite3, statistics, sys, time
import httpx

DB, PAPER = sys.argv[1], 999006
BASE = "http://127.0.0.1:18765/api/analysis"
Q = "한 문장으로만 답해줘: 이 논문이 실험한 데이터셋 이름은?"

def turn(persist):
    t0 = time.perf_counter()
    first = None
    with httpx.stream("POST", f"{BASE}/{PAPER}/chat", json={"message": Q, "persist": persist, "history": []}, timeout=120) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if ev["type"] == "token" and first is None:
                first = time.perf_counter() - t0
            if ev["type"] in ("done", "error"):
                return first, ev
    return first, None

out = {}
for provider in ("openai", "gemini"):
    con = sqlite3.connect(DB); con.execute("UPDATE settings SET value=? WHERE key='ai_provider'", (provider,)); con.commit(); con.close()
    rows = {True: [], False: []}
    cost = 0.0
    for i in range(5):
        for persist in (False, True) if i % 2 == 0 else (True, False):
            first, ev = turn(persist)
            rows[persist].append(first)
            cost += (ev or {}).get("cost_usd") or 0
            print(provider, "persist" if persist else "nopersist", f"{first:.2f}s", (ev or {}).get("type"), flush=True)
        # 매 쌍 뒤 기록을 지워 맥락 크기를 같게 둔다.
        httpx.delete(f"{BASE}/{PAPER}/discussion")
    out[provider] = {
        "persist_median": statistics.median(rows[True]), "nopersist_median": statistics.median(rows[False]),
        "persist": rows[True], "nopersist": rows[False], "cost_usd": cost,
    }
print(json.dumps(out, indent=1))
