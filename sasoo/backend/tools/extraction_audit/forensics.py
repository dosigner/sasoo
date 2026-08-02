"""S2 — 표 후보 포렌식. 후보 원장을 덤프하고 bbox를 크롭해 PNG로 저장한다.

코드만 보고 오탐의 정체를 추측하지 않는다. 그림 작업에서 캡션 151건을 전수 분류하니
규칙이 저절로 드러난 것과 같은 절차다 — 크롭을 눈으로 보면 확정된다.

좌표계 주의(계약 10): 매니페스트 bbox는 좌하단 원점 [x0, y_bottom, x1, y_top],
PyMuPDF는 좌상단 원점이다. 뒤집지 않으면 페이지 반대편을 크롭하게 된다.

실행:
    cd sasoo/backend && .venv/bin/python -m tools.extraction_audit.forensics 2014_Saliency
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.extraction_audit.measure import make_scratch_dir, prepare_manifest  # noqa: E402
from services.table_candidates import build_table_candidates  # noqa: E402

LIBRARY = Path(__file__).resolve().parents[2] / "library"
OUT = Path(__file__).resolve().parent / "_out" / "crops"


def main() -> None:
    needle = sys.argv[1] if len(sys.argv) > 1 else ""
    for paper_dir in sorted(LIBRARY.iterdir()):
        if not (paper_dir / ".odl_manifest.json").exists() or needle.lower() not in paper_dir.name.lower():
            continue
        pdf_path = next(paper_dir.glob("*.pdf"), None)
        if pdf_path is None:
            continue
        manifest = prepare_manifest(paper_dir, pdf_path)
        scratch = make_scratch_dir(paper_dir, manifest, pdf_path)
        candidates = build_table_candidates(manifest, pdf_path=pdf_path, paper_dir=scratch)
        out_dir = OUT / paper_dir.name[:24]
        out_dir.mkdir(parents=True, exist_ok=True)
        document = fitz.open(str(pdf_path))
        print(f"\n=== {paper_dir.name}  후보 {len(candidates)}개")
        print(f"{'id':<26}{'page':>5} {'source':<22}{'grid':>9}{'nonempty':>9}{'mean':>6}{'ruled':>6}  caption")
        for candidate in candidates:
            grid = candidate.get("text_grid") or []
            rows = len(grid)
            columns = max((len(row) for row in grid), default=0)
            non_empty = sum(1 for row in grid for cell in row if str(cell).strip())
            print(
                f"{candidate['id']:<26}{candidate['page_number']:>5} {candidate['source_kind']:<22}"
                f"{f'{rows}x{columns}':>9}{non_empty:>9}"
                f"{str(candidate['has_meaningful_grid'])[0]:>6}{str(candidate['plausible_ruled_bbox'])[0]:>6}  "
                f"{candidate.get('best_caption_id') or '-'}"
            )
            page = document[candidate["page_number"] - 1]
            page_height = float(page.rect.height)
            x0, y_bottom, x1, y_top = candidate["bbox"]
            rect = fitz.Rect(x0, page_height - y_top, x1, page_height - y_bottom)
            name = candidate["id"].replace(":", "_")
            page.get_pixmap(dpi=100, clip=rect).save(str(out_dir / f"{name}.png"))
        document.close()
        print(f"크롭: {out_dir}")


if __name__ == "__main__":
    main()
