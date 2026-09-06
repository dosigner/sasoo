"""DEC-017 검증: 새 _DEEP_DIVE_SCHEMA·_DEEP_DIVE_INSTRUCTION으로 실논문 1회 실행.

paper 50(이론 논문)에 프로덕션 모델(gemini-3.7-flash, thinking=high)로
deep_dive를 1회 돌리고, 새 구조화 필드가 실제로 채워지는지 확인한다.
provider_compare의 키 로드·PDF 업로드 골격을 재사용한다.
"""

import json
import sys
from pathlib import Path

BACKEND = Path("/Users/dongj/dev/논문_사수_개발중/sasoo/backend")
sys.path.insert(0, str(BACKEND))

from tools.provider_compare import load_keys, load_paper, run_gemini  # noqa: E402
from api import analysis_routes as ar  # noqa: E402
from services.pricing import calc_cost  # noqa: E402

PAPER_ID = 50  # Network Architectures for Space-Optical — methodology=theoretical

def main() -> None:
    keys = load_keys()
    if not keys["gemini"]:
        raise SystemExit("gemini 키를 찾지 못했다")

    pdf, meta = load_paper(PAPER_ID)
    print(f"논문: {meta['title'][:70]} (paper {PAPER_ID})")
    print(f"PDF: {pdf.name}")

    result = run_gemini(
        pdf,
        ar._DEEP_DIVE_INSTRUCTION,
        ar._DEEP_DIVE_SCHEMA,
        ar._STAGE_THINKING["deep_dive"],
        keys["gemini"],
    )
    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])
    print(f"\n모델: {result['model']}, in={result['tokens_in']}, out={result['tokens_out']}, "
          f"cost=${cost:.4f}, {result['elapsed_s']}s")

    data = json.loads(result["text"])
    out_path = Path(__file__).parent / f"deep_dive_paper{PAPER_ID}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"저장: {out_path}\n")

    print("필드 채움 상태:")
    for key in ar._DEEP_DIVE_SCHEMA["properties"]:
        v = data.get(key)
        if isinstance(v, str):
            state = f"{len(v)}자" if v.strip() else "빈 문자열"
        elif isinstance(v, list):
            state = f"{len(v)}항목"
        else:
            state = "누락"
        print(f"  {key:28s} {state}")

if __name__ == "__main__":
    main()
