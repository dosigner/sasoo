"""DEC-021 후속: 3.7이 폭주했던 VLA 6편을 현행 프로덕션 프롬프트·스키마·상한으로 Gemini 3.8 체인 재실행.
chain_compare_multi(2026-08-29 하네스)의 run_gemini를 재사용한다. 모델만 MODEL_FLASH_HQ를 따른다."""
import sys, json, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv("/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.env")
sys.path.insert(0, str(Path(__file__).parent))
import chain_compare_multi as m

assert m.GEMINI_MODEL == "gemini-3.8-flash", m.GEMINI_MODEL
assert len(m.SCHEMAS["deep_dive"]["required"]) == 12            # DEC-020
assert "comparison_scope" in m.SCHEMAS["deep_dive"]["properties"]  # DEC-018
assert m.CAPS["deep_dive"] == 16_000 and m.EFFORT["deep_dive"] == "high"
m.OUT.mkdir(parents=True, exist_ok=True)
print(f"model={m.GEMINI_MODEL} papers={m.PAPERS} out={m.OUT}", flush=True)

keys = m.load_keys()
t0 = time.time()
for paper in m.PAPERS:
    try:
        m.run_gemini(keys["gemini"], paper, m.PDF_DIR / f"{paper}.pdf")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR {paper}: {exc!r}", flush=True)
total = sum(r["cost_usd"] for r in m.LEDGER)
print(f"\n총 비용 ${total:.4f}, 호출 {len(m.LEDGER)}건, {time.time()-t0:.0f}s", flush=True)
