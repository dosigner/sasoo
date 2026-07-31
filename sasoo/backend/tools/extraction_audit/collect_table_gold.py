"""S0 — 표 정답(gold) 라벨을 3개 소스에서 뽑아 교차 검증한다.

세 소스가 일치하는 논문은 자동 확정, 하나라도 어긋나면 PDF 렌더 육안 확인 대상이다.

  (A) PDF 텍스트 블록  : PyMuPDF `get_text("blocks")` → 장식 제거 → NFKC → 확장 라벨 규칙
                         → `_label_is_followed_by_caption_body`로 본문 언급 배제
  (B) markdown 본문     : 같은 확장 규칙. 줄머리 캡션형과 문중 언급형을 나눠 센다
  (C) 매니페스트        : `captions` + `pages[].caption_blocks`, 확장 규칙으로 재판정

실행:
    cd sasoo/backend && .venv/bin/python -m tools.extraction_audit.collect_table_gold
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.document_manifest import _label_is_followed_by_caption_body  # noqa: E402
from tools.extraction_audit.table_labels import (  # noqa: E402
    canonical_label,
    match_table_label,
    normalize,
    parse_table_label_token,
)

LIBRARY = Path(__file__).resolve().parents[2] / "library"
OUT_PATH = Path(__file__).resolve().parents[4] / "docs" / "table_gold.json"

# 문중 언급까지 잡으려면 문두 고정 패턴을 쓸 수 없다.
_INLINE_LABEL = re.compile(r"(?<![A-Za-z])(?:Table|TABLE|Tbl\.?)\s*([A-Za-z0-9]{1,7})\b")


def _iter_papers() -> list[Path]:
    return sorted(d for d in LIBRARY.iterdir() if (d / ".odl_manifest.json").exists() and any(d.glob("*.pdf")))


def source_a_pdf_blocks(pdf_path: Path) -> list[dict]:
    """PDF 텍스트 블록에서 표 캡션으로 보이는 것을 모은다."""
    found: list[dict] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page_index in range(len(doc)):
            for block in doc[page_index].get_text("blocks"):
                if len(block) < 7 or block[6] != 0:
                    continue
                text = re.sub(r"\s+", " ", str(block[4] or "")).strip()
                if not text:
                    continue
                matched = match_table_label(normalize(text))
                if matched is None:
                    continue
                notation, number, suffix, end = matched
                if not _label_is_followed_by_caption_body(normalize(text)[end:]):
                    continue  # 본문 언급
                found.append(
                    {
                        "label": canonical_label(notation, number, suffix),
                        "notation": notation,
                        "number": number,
                        "page": page_index + 1,
                        "caption": text[:160],
                    }
                )
    finally:
        doc.close()
    return found


def source_b_markdown(md_path: Path) -> dict[str, list[dict]]:
    """markdown에서 표 라벨을 캡션형/언급형으로 나눠 모은다."""
    caption_like: list[dict] = []
    mention: list[dict] = []
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    page = 0
    for line in text.splitlines():
        page_marker = re.match(r"^---\s*Page\s+(\d+)\s*---", line.strip())
        if page_marker:
            page = int(page_marker.group(1))
            continue
        stripped_line = normalize(line)
        head = match_table_label(stripped_line)
        if head is not None:
            notation, number, suffix, end = head
            entry = {
                "label": canonical_label(notation, number, suffix),
                "number": number,
                "notation": notation,
                "page": page,
                "caption": line.strip()[:160],
            }
            (caption_like if _label_is_followed_by_caption_body(stripped_line[end:]) else mention).append(entry)
            continue
        for match in _INLINE_LABEL.finditer(stripped_line):
            parsed = parse_table_label_token(match.group(1))
            if parsed is None:
                continue
            notation, number, suffix = parsed
            mention.append(
                {
                    "label": canonical_label(notation, number, suffix),
                    "number": number,
                    "notation": notation,
                    "page": page,
                    "caption": stripped_line[max(0, match.start() - 20) : match.end() + 60],
                }
            )
    return {"caption_like": caption_like, "mention": mention}


def source_c_manifest(manifest: dict) -> list[dict]:
    """매니페스트 캡션을 확장 규칙으로 재판정한다."""
    found: list[dict] = []
    blocks = list(manifest.get("captions") or [])
    for page in manifest.get("pages") or []:
        for block in page.get("caption_blocks") or []:
            blocks.append({**block, "page_number": block.get("page_number") or page.get("page_number")})
    for block in blocks:
        text = str(block.get("text") or "")
        normalized = normalize(text)
        matched = match_table_label(normalized)
        if matched is None:
            continue
        notation, number, suffix, end = matched
        if not _label_is_followed_by_caption_body(normalized[end:]):
            continue
        found.append(
            {
                "label": canonical_label(notation, number, suffix),
                "notation": notation,
                "number": number,
                "page": block.get("page_number"),
                "caption": text[:160],
                "id": block.get("id"),
            }
        )
    return found


def _label_set(entries: list[dict]) -> set[str]:
    return {entry["label"] for entry in entries}


def main() -> None:
    report: dict[str, dict] = {}
    print(f"{'논문':<46} {'A(PDF)':<22} {'B(md캡션)':<22} {'C(매니페스트)':<22} 판정")
    for paper_dir in _iter_papers():
        pdf_path = next(paper_dir.glob("*.pdf"))
        manifest = json.loads((paper_dir / ".odl_manifest.json").read_text(encoding="utf-8"))
        md_candidates = sorted(paper_dir.glob("*.odl-reference.md")) or sorted(
            p for p in paper_dir.glob("*.md") if not p.name.startswith(".")
        )

        a = source_a_pdf_blocks(pdf_path)
        b = source_b_markdown(md_candidates[0]) if md_candidates else {"caption_like": [], "mention": []}
        c = source_c_manifest(manifest)

        sets = {"A": _label_set(a), "B": _label_set(b["caption_like"]), "C": _label_set(c)}
        b_mention = _label_set(b["mention"])
        agree = sets["A"] == sets["B"] == sets["C"]

        report[paper_dir.name] = {
            "source_a_pdf_blocks": a,
            "source_b_markdown_caption_like": b["caption_like"],
            "source_b_markdown_mentions": sorted(b_mention),
            "source_c_manifest": c,
            "label_sets": {key: sorted(value) for key, value in sets.items()},
            "agree": agree,
        }
        print(
            f"{paper_dir.name[:45]:<46} "
            f"{','.join(sorted(sets['A'])) or '-':<22.22} "
            f"{','.join(sorted(sets['B'])) or '-':<22.22} "
            f"{','.join(sorted(sets['C'])) or '-':<22.22} "
            f"{'일치' if agree else '검수필요'}  (본문언급: {','.join(sorted(b_mention)) or '-'})"
        )

    dump_path = Path(__file__).resolve().parent / "table_gold_sources.json"
    dump_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n소스 원장: {dump_path}")
    print(f"확정 gold는 육안 검수 후 {OUT_PATH} 로 쓴다.")


if __name__ == "__main__":
    main()
