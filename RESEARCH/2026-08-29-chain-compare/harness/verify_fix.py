"""DEC-018 검증: 폭주했던 VLA 4편을 새 프롬프트·스키마로 Gemini 체인 재실행.

chain_compare_multi의 러너를 재사용한다. analysis_routes를 소스에서 다시 읽으므로
DEC-018 수정(comparison_scope enum, "명시해" 제거, 명명 규약 규칙 12)이 자동 반영된다.
"""

import sys
from pathlib import Path

sys.path.insert(0, "/Users/dongj/.claude/jobs/63a3bb36/tmp")
import chain_compare_multi as m  # noqa: E402

m.OUT = Path("/Users/dongj/.claude/jobs/63a3bb36/tmp/vla_out_fixed")
m.OUT.mkdir(exist_ok=True)

# 수정이 반영됐는지 실행 전에 단언한다.
assert "comparison_scope" in m.SCHEMAS["deep_dive"]["properties"]
assert "평가임을 명시해" not in m.PROMPTS["deep_dive"]
assert "aperture_diameter" in m.PROMPTS["recipe"]  # 규칙 12
assert m.CAPS["deep_dive"] == 16_000

keys = m.load_keys()
for paper in ("palme", "openvla", "octo", "pi0"):
    try:
        m.run_gemini(keys["gemini"], paper, m.PDF_DIR / f"{paper}.pdf")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR {paper}: {exc!r}", flush=True)

total = sum(r["cost_usd"] for r in m.LEDGER)
print(f"\n총 비용 ${total:.4f}, 호출 {len(m.LEDGER)}건", flush=True)
