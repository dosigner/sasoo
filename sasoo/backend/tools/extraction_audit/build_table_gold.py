"""S0 — 교차 검증 원장 + 육안 검수 결과로 `docs/table_gold.json`을 확정한다.

gold의 정의는 **라벨을 가진 표**다(`Table 1`, `Table I`). 라벨 없이 그림 패널 안에
들어 있는 격자(2026_SR_Agile p10의 Fig. 6-Cii 등)는 그림으로 이미 산출되므로 gold에
넣지 않는다 — 라벨 집합 지표(FP/FN)가 성립하지 않기 때문이다.

라벨 집합은 세 소스의 **합집합**으로 만든다. 소스마다 맹점이 다르기 때문이다:
  - A(PDF 블록)는 캡션이 표 본문 블록에 병합되면 못 본다 (2014_Saliency)
  - C(매니페스트)는 파서가 확률적으로 캡션을 빠뜨리면 못 본다 (2017_COMST의 Table II)
  - B(markdown)는 페이지 정보가 약하다
합집합이 육안 검수 결과와 12편 전부에서 일치함을 확인하고 고정한다(아래 VERIFIED).

실행:
    cd sasoo/backend && .venv/bin/python -m tools.extraction_audit.build_table_gold
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.extraction_audit.table_labels import parse_table_label_token  # noqa: E402

SOURCES_PATH = Path(__file__).resolve().parent / "table_gold_sources.json"
OUT_PATH = Path(__file__).resolve().parents[4] / "docs" / "table_gold.json"

# 2026-07-31 육안 검수 기록. 값은 렌더해서 확인한 페이지와 확인 내용.
VERIFIED: dict[str, dict[str, str]] = {
    "2013_IEEETIP_ClusterCoSaliency_Quantum": {
        "p10": "TABLE I (SEGMENTATION ACCURACY) 실재. 캡션이 표 위. 이 논문의 유일한 표.",
    },
    "2014_Saliency_Optimization_from_Robust_Backgr_706a9f8d": {
        "p4": "Table 1 실재. 캡션이 표 아래이고 표 본문 블록과 병합돼 소스 A가 못 봤다.",
        "p6": "Table 2 실재. 동일.",
    },
    "2017_COMST_OpticalComm_optical_communications": {
        "p5": "Table II 실재(캡션이 표 아래). 매니페스트(C)만 이 캡션을 빠뜨렸다 → gold는 8.",
    },
    "2012_ICSOS_SpaceOpticalNetworks_optics": {
        "p2": "표 없음. 2단 조판 텍스트 + 그림 1개. table_candidate 1건은 오탐.",
    },
    "2026_SR_AgileMultiskill_ai_ml": {
        "p4": "표 없음(전부 그림 패널).",
        "p6": "표 없음(전부 그림 패널).",
        "p10": "격자는 있으나 Fig. 6 (C)ii 안의 패널이고 표 라벨이 없다 → gold 제외.",
    },
}


def main() -> None:
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    gold: dict[str, dict] = {}

    for name, report in sources.items():
        entries: dict[str, dict] = {}
        # evidence는 페이지가 확실한 소스부터 채운다: A(PDF 블록) > C(매니페스트) > B(markdown).
        for key in ("source_a_pdf_blocks", "source_c_manifest", "source_b_markdown_caption_like"):
            for entry in report[key]:
                label = entry["label"]
                if label in entries:
                    continue
                entries[label] = {
                    "label": label,
                    "notation": entry["notation"],
                    "number": entry["number"],
                    "page": entry.get("page") or None,
                    "caption": entry.get("caption", ""),
                    "evidence_source": {"source_a_pdf_blocks": "pdf_blocks", "source_c_manifest": "manifest"}.get(
                        key, "markdown"
                    ),
                }

        def sort_key(label: str) -> tuple[int, str]:
            parsed = parse_table_label_token(label.split()[-1])
            return (parsed[1] if parsed else 99, label)

        ordered = sorted(entries, key=sort_key)
        gold[name] = {
            "labels": ordered,
            # 로마/아라비아 표기 차이를 흡수한 비교용 번호 집합.
            "numbers": sorted({entries[label]["number"] for label in ordered}),
            "evidence": [entries[label] for label in ordered],
            "sources_agree": report["agree"],
            "visual_review": VERIFIED.get(name, {}),
        }

    OUT_PATH.write_text(
        json.dumps(
            {
                "_comment": (
                    "표 추출 정확도의 정답 대장. 라벨을 가진 표만 센다. "
                    "생성: tools/extraction_audit/{collect_table_gold,build_table_gold}.py, "
                    "육안 검수 2026-07-31."
                ),
                "papers": gold,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    total = sum(len(item["labels"]) for item in gold.values())
    for name, item in gold.items():
        print(f"{name[:45]:<46} {len(item['labels']):>2}  {item['labels']}")
    print(f"\ngold 총 {total}개 라벨 / {len(gold)}편 → {OUT_PATH}")


if __name__ == "__main__":
    main()
