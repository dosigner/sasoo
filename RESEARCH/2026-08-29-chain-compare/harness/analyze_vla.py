"""VLA 실측 원장 집계: 논문별 토큰·비용·지연, 수렴 지표."""

import json
from pathlib import Path

OUT = Path("/Users/dongj/.claude/jobs/63a3bb36/tmp/vla_out")
PAGES = {"rt2": 26, "rt1": 31, "palme": 18, "openvla": 37, "octo": 17, "pi0": 17}

ledger = json.loads((OUT / "ledger.json").read_text())

def chain(paper, provider):
    return [r for r in ledger if r["paper"] == paper and r["provider"] == provider]

print("=== 논문별 체인 합계 (in/out/비용$/시간s) ===")
for paper in PAGES:
    line = f"{paper:8s} {PAGES[paper]:3d}쪽"
    for pv in ("gemini", "luna"):
        rows = chain(paper, pv)
        if len(rows) < 3:
            line += f" | {pv}: 미완({len(rows)}건)"
            continue
        tin = sum(r["tokens_in"] for r in rows)
        tout = sum(r["tokens_out"] for r in rows)
        cost = sum(r["cost_usd"] for r in rows)
        el = sum(r["elapsed_s"] for r in rows)
        inc = sum(1 for r in rows if r["status"] not in ("completed", "InteractionStatus.COMPLETED"))
        line += f" | {pv}: {tin:>7,}/{tout:>6,} ${cost:.3f} {el:5.0f}s" + (f" 비정상{inc}" if inc else "")
    print(line)

print("\n=== 단계별 상태 이상(incomplete 등) ===")
for r in ledger:
    if r["status"] not in ("completed", "InteractionStatus.COMPLETED"):
        print(r["paper"], r["provider"], r["stage"], r["status"], "out=", r["tokens_out"])

print("\n=== 수렴 지표 ===")
def load(paper, pv, stage):
    f = OUT / f"{paper}_{pv}_{stage}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except Exception:
        return "PARSE_FAIL"

for paper in PAGES:
    gv, lv = load(paper, "gemini", "visual"), load(paper, "luna", "visual")
    gr, lr = load(paper, "gemini", "recipe"), load(paper, "luna", "recipe")
    gd, ld = load(paper, "gemini", "deep_dive"), load(paper, "luna", "deep_dive")
    bits = [paper]
    if isinstance(gv, dict) and isinstance(lv, dict):
        bits.append(f"그림 {gv.get('figure_count')}/{lv.get('figure_count')} 표 {gv.get('tables_found')}/{lv.get('tables_found')}")
    if isinstance(gr, dict) and isinstance(lr, dict):
        gp = {p["name"].lower() for p in gr.get("parameters", []) if isinstance(p, dict) and p.get("name")}
        lp = {p["name"].lower() for p in lr.get("parameters", []) if isinstance(p, dict) and p.get("name")}
        inter = len(gp & lp)
        union = len(gp | lp) or 1
        bits.append(f"파라미터 {len(gp)}/{len(lp)} 이름교집합 {inter}/{union}")
    for label, d in (("g", gd), ("l", ld)):
        if isinstance(d, dict):
            filled = sum(1 for k in ("problem_definition", "as_is", "to_be", "solution",
                                     "method_summary", "key_results") if (d.get(k) or "").strip())
            bits.append(f"dd_{label} 서술 {filled}/6 약점 {len(d.get('weaknesses') or [])}")
        elif d == "PARSE_FAIL":
            bits.append(f"dd_{label} JSON파싱실패")
    print(" | ".join(bits))
